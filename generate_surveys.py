#!/usr/bin/env python3
"""
generate_surveys.py
-------------------
Generates Salesforce LSC OfflineMobile Survey Flow XML from:

  --csv    Structured CSV  (one row per question, multi-page, branching supported)
  --veeva  Veeva CRM export (auto-detects Format A or B, tab or comma delimiter)

────────────────────────────────────────────────────────────────
CSV columns:
  survey_name, survey_developer_name,
  welcome_text, thankyou_label, thankyou_text,
  page_label, page_developer_name, page_order,
  question_text, question_developer_name, question_type,
  question_order, required, choices, slider_min, slider_max,
  branch_on_answer, branch_to_page

  question_type values: ShortText, FreeText, Date, DateTime, Number, Slider,
                        RadioButton, Picklist, MultiselectPicklist, Rating, CSAT, StackRank,
                        Description
  choices format: pipe-separated  e.g. Yes|No|Maybe

────────────────────────────────────────────────────────────────
Veeva FORMAT A — Survey_Question_vod__c export (question definitions):
  SURVEY_VOD__C              groups questions into surveys
  TEXT_VOD__C                question text (QTN:/QTB: prefix stripped)
  ANSWER_CHOICE_VOD__C       "ChoiceA;1;ChoiceB;0" format (weights auto-handled)
  ORDER_VOD__C               question order
  REQUIRED_VOD__C            1 = required, 0 = optional
  MIN_SCORE_VOD__C / MAX_SCORE_VOD__C
  SURVEY_NAME_VOD__C / SURVEY_DEVELOPER_NAME_VOD__C  (optional, fall back to ID)

Veeva FORMAT B — Survey_Question_Response_vod__c export (response records):
  SURVEY_TARGET_VOD__C       groups questions into surveys
  QUESTION_TEXT_VOD__C       question text
  SURVEY_QUESTION_VOD__C     dedup key (same question answered N times → kept once)
  ANSWER_CHOICE_VOD__C, ORDER_VOD__C, REQUIRED_VOD__C  (same as Format A)

  Format and delimiter (tab / comma) are auto-detected from file headers.

  Optional --names CSV maps Veeva survey IDs to friendly metadata:
    survey_id, survey_name, survey_developer_name,
    welcome_text, thankyou_label, thankyou_text

────────────────────────────────────────────────────────────────
Choice weights:
  Veeva encodes weights as  ChoiceA;1;ChoiceB;0
  If all weights for a question are equal  → weights dropped (no scoring)
  If weights differ                        → <score> element added per choice

────────────────────────────────────────────────────────────────
Usage:
  python3 generate_surveys.py --csv surveys.csv
  python3 generate_surveys.py --csv surveys.csv --out ./flows
  python3 generate_surveys.py --veeva veeva_export.csv
  python3 generate_surveys.py --veeva veeva_export.csv --names survey_names.csv
  python3 generate_surveys.py --csv surveys.csv --deploy lsdev1
"""

import argparse, csv, io, json, re, subprocess, sys
from collections import OrderedDict
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
try:
    from veeva_to_lsc import transform as veeva_transform
    _HAS_VEEVA_XLSX = True
except ImportError:
    _HAS_VEEVA_XLSX = False


# Maps question_type → (data_type, field_type, extension_name)
# data_type=None for DisplayText (Description) — no <dataType> element emitted.
TYPE_MAP = {
    "ShortText":            ("String",   "ComponentInput",        "survey:runtimeShortText"),
    "FreeText":             ("String",   "InputField",             None),
    "Date":                 ("Date",     "InputField",             None),
    "DateTime":             ("Date",     "InputField",             None),   # LSC fallback: DateTime → Date
    "Number":               ("Number",   "InputField",             None),
    "Slider":               ("Number",   "ComponentInput",        "survey:cmpInputRuntimeSlider"),
    "RadioButton":          ("String",   "ComponentChoice",       "survey:runtimeRadioButton"),
    "Picklist":             ("String",   "ComponentChoice",       "survey:runtimePicklist"),
    "MultiselectPicklist":  ("String",   "MultiSelectCheckboxes",  None),
    "Rating":               ("Number",   "ComponentChoice",       "survey:runtimeRating"),
    "CSAT":                 ("Number",   "ComponentChoice",       "survey:runtimeRating"),   # fallback: CSAT → Rating
    "StackRank":            ("String",   "ComponentChoice",       "survey:runtimePicklist"), # fallback: StackRank → Picklist
    "Description":          ("String",    "InputField",             None),   # LSC: DisplayText unsupported → FreeText InputField
}

CHOICE_TYPES = {"RadioButton", "Picklist", "MultiselectPicklist", "StackRank", "Rating", "CSAT"}
YES_NO       = {"yes", "no", "כן", "לא"}


# ─── Shared utilities ─────────────────────────────────────────────────────────

def slugify(text, max_len=40):
    s = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return ("x_" + s if s and s[0].isdigit() else s)[:max_len]


def _clean_text(text):
    """Strip QTN:/QTB: prefixes and normalize whitespace."""
    text = re.sub(r"^QT[NB][^:]*:\s*", "", text.strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text.replace("\n", " ")).strip()


def _parse_choice_pairs(raw):
    """
    Parse Veeva 'ChoiceA;1;ChoiceB;0' → [(text, weight), ...]
    If all weights are equal → weight set to None (dropped downstream).
    """
    if not raw or not raw.strip():
        return []
    parts = [p.strip() for p in raw.split(";")]
    pairs = [(parts[i], parts[i + 1] if i + 1 < len(parts) else "0")
             for i in range(0, len(parts), 2) if parts[i]]
    all_same = len(set(w for _, w in pairs)) <= 1
    return [(text, None if all_same else w) for text, w in pairs]


def _infer_veeva_type(choice_pairs):
    """Infer SF question type from Veeva choice list."""
    if not choice_pairs:
        return "FreeText"
    texts = [t.lower() for t, _ in choice_pairs]
    if len(choice_pairs) <= 2 and set(texts) <= YES_NO:
        return "RadioButton"
    if len(choice_pairs) <= 3:
        return "RadioButton"
    return "Picklist"


# ─── CSV parser ───────────────────────────────────────────────────────────────

def parse_csv(csv_path):
    """Parse structured CSV → raw surveys dict (multi-page, branching supported).
    csv_path may be a file path string or a file-like object (e.g. StringIO).
    """
    surveys = OrderedDict()

    if hasattr(csv_path, "read"):
        f_ctx = csv_path
        rows = list(csv.DictReader(f_ctx))
    else:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))

    for row in rows:
        row = {k: (v or "").strip() for k, v in row.items() if k}

        s_key = row["survey_developer_name"]
        if s_key not in surveys:
            surveys[s_key] = {
                "survey_name":           row["survey_name"],
                "survey_developer_name": s_key,
                "welcome_text":          row.get("welcome_text", ""),
                "thankyou_label":        row.get("thankyou_label", "Thank You"),
                "thankyou_text":         row.get("thankyou_text", ""),
                "pages":                 OrderedDict(),
            }

        p_key = row["page_developer_name"]
        pages = surveys[s_key]["pages"]
        if p_key not in pages:
            pages[p_key] = {
                "label":          row["page_label"],
                "developer_name": p_key,
                "order":          int(row.get("page_order", 1) or 1),
                "questions":      [],
            }

        q_type = row["question_type"]
        if q_type not in TYPE_MAP:
            print(f"[SKIP] Unknown type '{q_type}' on '{row['question_developer_name']}'",
                  file=sys.stderr)
            continue

        vis_raw = row.get("visibility_rule", "").strip()
        if "==" in vis_raw:
            vq_dev, vval = vis_raw.split("==", 1)
            visibility_rule = {"question_dev": vq_dev.strip(), "operator": "EqualTo", "value": vval.strip()}
        else:
            visibility_rule = None

        pages[p_key]["questions"].append({
            "text":             row["question_text"],
            "developer_name":   row["question_developer_name"],
            "type":             q_type,
            "question_order":   int(row.get("question_order", 1) or 1),
            "required":         row.get("required", "false").lower(),
            "choices_pipe":     row.get("choices", "").strip(),
            "choices_weights":  "",
            "slider_min":       row.get("slider_min", "1") or "1",
            "slider_max":       row.get("slider_max", "10") or "10",
            "branch_on_answer": row.get("branch_on_answer", "").strip(),
            "branch_to_page":   row.get("branch_to_page", "").strip(),
            "branch_rules":     row.get("branch_rules", "").strip(),
            "visibility_rule":  visibility_rule,
        })

    return surveys


# ─── Veeva parser ─────────────────────────────────────────────────────────────

def _load_names(names_path):
    mapping = {}
    with open(names_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            mapping[row["survey_id"]] = row
    return mapping


def _detect_veeva_format(headers):
    """Return 'B' for response export, 'A' for question-definition export."""
    if "SURVEY_TARGET_VOD__C" in headers or "QUESTION_TEXT_VOD__C" in headers:
        return "B"
    return "A"


def parse_source(veeva_path, names_path=None):
    """
    Parse a Veeva export (Format A or B, tab or comma) → raw surveys dict
    compatible with _build_surveys().
    """
    survey_names = _load_names(names_path) if names_path else {}

    with open(veeva_path, encoding="utf-8-sig") as f:
        content = f.read()

    delimiter = "\t" if "\t" in content.split("\n")[0] else ","
    reader    = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    fmt       = _detect_veeva_format(reader.fieldnames or [])
    print(f"Detected Veeva format: {'Question definitions (A)' if fmt == 'A' else 'Response records (B)'}")

    surveys        = OrderedDict()
    seen_questions = {}  # survey_id → set of dedup keys (Format B only)

    for row in reader:
        row = {k: (v or "").strip() for k, v in row.items() if k}

        if fmt == "A":
            survey_id  = row.get("SURVEY_VOD__C", "").strip()
            q_text_raw = row.get("TEXT_VOD__C", "")
            dedup_key  = None
        else:
            survey_id  = row.get("SURVEY_TARGET_VOD__C", "").strip()
            q_text_raw = row.get("QUESTION_TEXT_VOD__C", "")
            dedup_key  = row.get("SURVEY_QUESTION_VOD__C", "").strip() or None

        if not survey_id:
            continue

        if survey_id not in surveys:
            meta = survey_names.get(survey_id, {})
            # Format A may carry name columns inline; Format B relies on --names
            s_name = (row.get("SURVEY_NAME_VOD__C", "").strip()
                      or meta.get("survey_name", survey_id))
            s_dev  = (row.get("SURVEY_DEVELOPER_NAME_VOD__C", "").strip()
                      or meta.get("survey_developer_name", slugify(survey_id, 60)))
            surveys[survey_id] = {
                "survey_name":           s_name,
                "survey_developer_name": s_dev,
                "welcome_text":          meta.get("welcome_text", row.get("WELCOME_TEXT_VOD__C", "")),
                "thankyou_label":        meta.get("thankyou_label", row.get("THANK_YOU_HEADER_VOD__C", "Thank You")) or "Thank You",
                "thankyou_text":         meta.get("thankyou_text", row.get("THANK_YOU_TEXT_VOD__C", "")),
                "pages":                 OrderedDict(),
            }
            seen_questions[survey_id] = set()

        # Format B: deduplicate — same question answered by many accounts
        if dedup_key:
            if dedup_key in seen_questions[survey_id]:
                continue
            seen_questions[survey_id].add(dedup_key)

        q_text = _clean_text(q_text_raw)
        if not q_text:
            continue

        choice_pairs = _parse_choice_pairs(row.get("ANSWER_CHOICE_VOD__C", ""))
        q_type       = _infer_veeva_type(choice_pairs)
        q_dev        = slugify(q_text, 40) or f"q_{row.get('NAME', '').lower()}"
        order        = int(row.get("ORDER_VOD__C", 0) or 0)
        required     = "true" if row.get("REQUIRED_VOD__C", "0") == "1" else "false"

        # All Veeva questions land on a single page (Veeva has no page concept)
        p_key = "p_page_1"
        if p_key not in surveys[survey_id]["pages"]:
            surveys[survey_id]["pages"][p_key] = {
                "label":          "Page 1",
                "developer_name": p_key,
                "order":          1,
                "questions":      [],
            }

        surveys[survey_id]["pages"][p_key]["questions"].append({
            "text":              q_text,
            "developer_name":    q_dev,
            "type":              q_type,
            "question_order":    order,
            "required":          required,
            "choices_pipe":      "|".join(t for t, _ in choice_pairs),
            "choices_weights":   "|".join(w if w is not None else "" for _, w in choice_pairs),
            "slider_min":        row.get("MIN_SCORE_VOD__C", "1") or "1",
            "slider_max":        row.get("MAX_SCORE_VOD__C", "10") or "10",
            "branch_on_answer":  "",
            "branch_to_page":    "",
            "condition_raw":     row.get("CONDITION_VOD__C", "").strip(),
            "condition_label":   row.get("INACTIVE_CONDITION_VOD__C", "").strip(),
        })

    # Post-process: deduplicate dev names, then resolve visibility conditions
    for s in surveys.values():
        for p in s["pages"].values():
            p["questions"].sort(key=lambda q: q["question_order"])

            # Deduplicate developer_names
            seen_devs = {}
            for q in p["questions"]:
                base = q["developer_name"]
                if base in seen_devs:
                    seen_devs[base] += 1
                    q["developer_name"] = f"{base}_{seen_devs[base]}"
                else:
                    seen_devs[base] = 0

            # Build label → developer_name map for condition resolution.
            # Format A: INACTIVE_CONDITION_VOD__C holds the label e.g. "Q00"
            # Format B: INACTIVE_CONDITION_VOD__C is 0/1 (active flag only, no label).
            #   Fallback: scan all questions' choices to find which question
            #   contains the answer value referenced in each condition string,
            #   then synthesise the Qnn label from that question's ORDER.
            label_to_dev = {}
            for q in p["questions"]:
                lbl = q.get("condition_label", "")
                if lbl and not lbl.isdigit():
                    label_to_dev[lbl] = q["developer_name"]

            if not label_to_dev:
                # Format B: build answer-value → developer_name index from choices
                value_to_dev = {}
                for q in p["questions"]:
                    for choice in q.get("choices_pipe", "").split("|"):
                        choice = choice.strip()
                        if choice:
                            value_to_dev[choice] = q["developer_name"]
                # For each condition, extract the answer value and look it up
                for q in p["questions"]:
                    raw_cond = q.get("condition_raw", "")
                    if raw_cond:
                        m = re.match(r'^(\w+)\s*=\s*"([^"]*)"$', raw_cond.strip())
                        if m:
                            label, value = m.group(1), m.group(2)
                            if value in value_to_dev:
                                label_to_dev[label] = value_to_dev[value]

            # Resolve each question's condition_raw into a structured visibility_rule
            for q in p["questions"]:
                q["visibility_rule"] = _parse_condition(q.get("condition_raw", ""), label_to_dev)

    return surveys


def _parse_condition(condition_raw, label_to_dev):
    """
    Parse Veeva CONDITION_VOD__C into a structured visibility rule.

    Input:  'Q00="Do not plan to stock"'
    Output: {"question_dev": "which_brand_...", "operator": "EqualTo", "value": "Do not plan to stock"}
    Returns None if condition is empty or cannot be resolved.
    """
    if not condition_raw:
        return None
    m = re.match(r'^(\w+)\s*=\s*"([^"]*)"$', condition_raw.strip())
    if not m:
        return None
    label, value = m.group(1), m.group(2)
    q_dev = label_to_dev.get(label)
    if not q_dev:
        return None
    return {"question_dev": q_dev, "operator": "EqualTo", "value": value}


# ─── Shared build & generate ──────────────────────────────────────────────────

def _build_surveys(surveys):
    """
    Shared finalisation for both CSV and Veeva paths:
    - resolves TYPE_MAP attributes
    - builds choice elements with optional scores
    - sorts pages and questions
    - builds decisions for branching
    - sets page connectors
    """
    result = []
    for s in surveys.values():
        # Use a 6-char hash of the full dev name so even territory variants
        # (adoption_ladder_d_onchaem1 vs adoption_ladder_f_onchaem1) get
        # distinct prefixes without truncation collisions.
        import hashlib
        _full = s["survey_developer_name"]
        _h6 = hashlib.md5(_full.encode()).hexdigest()[:6]
        s_dev = slugify(_full, 10).strip("_") + "_" + _h6
        pages = sorted(s["pages"].values(), key=lambda p: p["order"])
        for p in pages:
            p["questions"].sort(key=lambda q: q["question_order"])

            resolved = []
            for q in p["questions"]:
                q_type = q["type"]
                if q_type not in TYPE_MAP:
                    print(f"[SKIP] Unknown type '{q_type}' on '{q['developer_name']}'",
                          file=sys.stderr)
                    continue
                data_type, field_type, ext = TYPE_MAP[q_type]
                q_dev = q["developer_name"]

                choices = []
                if q_type in CHOICE_TYPES:
                    if q_type in ("Rating", "CSAT"):
                        # Auto-generate numeric star choices from slider_min to slider_max
                        lo = int(q.get("slider_min", "1") or "1")
                        hi = int(q.get("slider_max", "5") or "5")
                        q_slug = slugify(q_dev, 14).strip("_") or "q"
                        for i, val in enumerate(range(lo, hi + 1)):
                            choices.append({
                                "name":  f"c_{s_dev}_{q_slug}_{val}_{i}",
                                "text":  str(val),
                                "score": None,
                            })
                    elif q.get("choices_pipe"):
                        texts       = [c.strip() for c in q["choices_pipe"].split("|") if c.strip()]
                        weights_raw = q.get("choices_weights", "") or ""
                        wlist       = [w.strip() for w in weights_raw.split("|")] if weights_raw else []
                        has_scores  = any(w for w in wlist)
                        q_slug = slugify(q_dev, 14).strip("_") or f"q{i}"
                        for i, text in enumerate(texts):
                            w = wlist[i] if i < len(wlist) else ""
                            t_slug = slugify(text, 14).strip("_") or f"opt{i}"
                            choices.append({
                                "name":  f"c_{s_dev}_{q_slug}_{t_slug}_{i}",
                                "text":  text,
                                "score": w if has_scores else None,
                            })

                import html as _html
                q_text = q["text"]
                # fieldText is xml-encoded in the flow; Salesforce caps "User Input Prompt" at
                # 1000 chars of the encoded value.  The wrapper adds ~40 encoded chars, leaving
                # ~960 for the encoded text.  Trim until it fits.
                _MAX_ENCODED = 960
                while len(_html.escape(q_text, quote=False)) > _MAX_ENCODED:
                    q_text = q_text[:int(len(q_text) * 0.9)]
                    print(f"[TRUNCATE] '{q_dev}' → {len(q_text)} raw chars", file=sys.stderr)

                # Parse branch_rules JSON if present (produced by veeva_to_lsc multi-page branching)
                raw_br = q.get("branch_rules", "")
                if isinstance(raw_br, str) and raw_br.strip():
                    try:
                        branch_rules = json.loads(raw_br)
                    except Exception:
                        branch_rules = []
                elif isinstance(raw_br, list):
                    branch_rules = raw_br
                else:
                    branch_rules = []

                # Enrich each rule with the choice's API name so the template can emit
                # <elementReference> instead of <stringValue> — required by OfflineMobile runtime.
                if branch_rules and choices:
                    choice_by_text = {c["text"]: c["name"] for c in choices}
                    branch_rules = [
                        dict(r, choice_api_name=choice_by_text.get(r.get("answer", ""), ""))
                        for r in branch_rules
                    ]

                resolved.append({
                    "text":             q_text,
                    "developer_name":   q_dev,
                    "type":             q_type,
                    "data_type":        data_type,
                    "field_type":       field_type,
                    "extension_name":   ext,
                    "field_text":       f"<p>{q_text}</p>",
                    "required":         q["required"],
                    "order":            q["question_order"],
                    "slider_min":       q.get("slider_min", "1") or "1",
                    "slider_max":       q.get("slider_max", "10") or "10",
                    "choices":          choices,
                    "branch_on_answer": q.get("branch_on_answer", ""),
                    "branch_to_page":   q.get("branch_to_page", ""),
                    "branch_rules":     branch_rules,
                    "visibility_rule":  q.get("visibility_rule"),
                })
            p["questions"] = resolved

        # Page connectors and branching decisions
        next_page = {p["developer_name"]: (pages[i + 1]["developer_name"] if i + 1 < len(pages) else None)
                     for i, p in enumerate(pages)}
        # Collect answer-branch destination pages that should NOT auto-chain to next page
        terminal_branch_pages = set()
        for p in pages:
            for q in p["questions"]:
                for rule in (q.get("branch_rules") or []):
                    terminal_branch_pages.add(rule["page"])

        decisions = []
        for p in pages:
            # Check for multi-rule branching (branch_rules list on a question)
            multi_branch_q = next((q for q in p["questions"] if q.get("branch_rules")), None)
            if multi_branch_q:
                rules = multi_branch_q["branch_rules"]  # list of {answer, page}
                d_name = f"d_{p['developer_name']}_branch"
                # default connector = first page after the last answer-page in order
                all_branch_pages = [r["page"] for r in rules]
                last_branch_page = all_branch_pages[-1]
                last_idx = next((i for i, pg in enumerate(pages)
                                 if pg["developer_name"] == last_branch_page), None)
                if last_idx is not None and last_idx + 1 < len(pages):
                    default_next = pages[last_idx + 1]["developer_name"]
                else:
                    # No page follows the last branch page — use the first branch page as
                    # fallback. Salesforce Flow requires a defaultConnector on every decision;
                    # without it the runtime ends the flow immediately regardless of rules.
                    default_next = all_branch_pages[0] if all_branch_pages else None
                decisions.append({
                    "name":               d_name,
                    "label":              f"{p['label']} Branch",
                    "rules":              rules,          # multi-rule list
                    "default_connector":  default_next,
                    "default_label":      "Other",
                    "question_reference": multi_branch_q["developer_name"],
                    # single-rule compat keys (unused when rules present)
                    "branch_answer":      "",
                    "branch_to":          "",
                })
                p["connector"] = d_name
                continue

            # Single-rule branching (branch_on_answer / branch_to_page on a question)
            branch_q = next((q for q in p["questions"]
                             if q["branch_on_answer"] and q["branch_to_page"]), None)
            if not branch_q:
                # Terminal branch pages: chain them in page-order so every page is
                # reachable via a sequential connector and shows in the Survey Builder
                # "Select page" dropdown. The builder only traverses <connector> /
                # <defaultConnector> links — pages reachable only via decision rule
                # connectors don't appear in the page picker.
                if p["developer_name"] not in terminal_branch_pages:
                    p["connector"] = next_page[p["developer_name"]]
                else:
                    # Ordered list of branch pages as they appear in the pages array
                    branch_list = [pg["developer_name"] for pg in pages
                                   if pg["developer_name"] in terminal_branch_pages]
                    idx = branch_list.index(p["developer_name"]) if p["developer_name"] in branch_list else -1
                    if idx >= 0 and idx + 1 < len(branch_list):
                        p["connector"] = branch_list[idx + 1]
                    else:
                        p["connector"] = None
                continue

            d_name       = f"d_{p['developer_name']}_branch"
            default_next = next_page[p["developer_name"]]
            if default_next == branch_q["branch_to_page"]:
                branch_idx   = next((i for i, pg in enumerate(pages)
                                     if pg["developer_name"] == branch_q["branch_to_page"]), None)
                default_next = pages[branch_idx + 1]["developer_name"] \
                               if branch_idx is not None and branch_idx + 1 < len(pages) else None
            decisions.append({
                "name":               d_name,
                "label":              f"{p['label']} Branch",
                "rules":              [],   # empty → template uses branch_answer/branch_to
                "branch_answer":      branch_q["branch_on_answer"],
                "branch_to":          branch_q["branch_to_page"],
                "default_connector":  default_next,
                "default_label":      f"Not {branch_q['branch_on_answer']}",
                "question_reference": branch_q["developer_name"],
            })
            p["connector"] = d_name

        s["pages"]            = pages
        s["decisions"]        = decisions
        s["all_questions"]    = [q for p in pages for q in p["questions"]]
        s["page_options_map"] = json.dumps(
            {p["developer_name"]: {"isMovable": True, "isDeletable": True} for p in pages},
            separators=(",", ":")
        )
        result.append(s)

    return result


def generate(surveys, output_dir, template_dir):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(template_dir),
                      autoescape=False, trim_blocks=True, lstrip_blocks=True)
    tpl = env.get_template("survey_flow.xml.j2")

    written = []
    for s in surveys:
        path = out / f"{s['survey_developer_name']}.flow-meta.xml"
        path.write_text(tpl.render(**s), encoding="utf-8")
        print(f"  [OK] {path.name}  ({len(s['all_questions'])} questions, {len(s['pages'])} page(s))")
        written.append(s["survey_developer_name"])

    return written


def deploy(flow_names, target_org, project_dir):
    args = []
    for name in flow_names:
        args += ["--metadata", f"Flow:{name}"]
    subprocess.run(
        ["sf", "project", "deploy", "start", "--target-org", target_org] + args,
        cwd=project_dir, check=True,
    )


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Generate Salesforce LSC OfflineMobile Survey Flow XML",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 generate_surveys.py --csv surveys.csv
  python3 generate_surveys.py --csv surveys.csv --out ./flows
  python3 generate_surveys.py --veeva veeva_export.csv
  python3 generate_surveys.py --veeva veeva_export.csv --names survey_names.csv
  python3 generate_surveys.py --csv surveys.csv --deploy lsdev1
        """)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--csv",   help="Structured CSV (new survey authoring)")
    group.add_argument("--veeva", help="Veeva CRM export (Format A or B, auto-detected)")
    group.add_argument("--xlsx",  help="Veeva SURVEY_DATA.xlsx (two-tab export — auto-transforms then generates)")
    p.add_argument("--names",         default=None,
                   help="CSV mapping Veeva survey IDs to friendly names")
    p.add_argument("--out",           default="./flows",
                   dest="output_dir", help="Output folder for .flow-meta.xml files (default: ./flows)")
    p.add_argument("--template-dir",  default=None)
    p.add_argument("--deploy",        default=None, metavar="ORG",
                   help="Deploy to Salesforce org after generating (e.g. --deploy lsdev1)")
    p.add_argument("--project-dir",   default=".")
    args = p.parse_args()

    _base   = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    tpl_dir = args.template_dir or str(_base / "templates")

    if args.xlsx:
        if not _HAS_VEEVA_XLSX:
            print("ERROR: veeva_to_lsc.py not found alongside generate_surveys.py", file=sys.stderr)
            sys.exit(1)
        print(f"Transforming {args.xlsx} via veeva_to_lsc …")
        df = veeva_transform(args.xlsx, output_path=None)
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        raw = parse_csv(buf)
    elif args.csv:
        raw = parse_csv(args.csv)
    else:
        raw = parse_source(args.veeva, args.names)

    surveys = _build_surveys(raw)
    print(f"\nSurveys found: {[s['survey_developer_name'] for s in surveys]}\n")

    written = generate(surveys, args.output_dir, tpl_dir)

    if args.deploy:
        deploy(written, args.deploy, str(Path(args.project_dir).resolve()))
    else:
        names = " ".join(f"Flow:{n}" for n in written)
        print(f"\nsf project deploy start --target-org {args.deploy or 'lsdev1'} --metadata {names}")


if __name__ == "__main__":
    main()
