"""
veeva_to_lsc.py — Transform Veeva Survey export (SURVEY_DATA.xlsx) to LSC survey generator CSV format.

Input:  SURVEY_DATA.xlsx  (two tabs: SURVEY_VOD, SURVEY_QUESTION_VOD)
Output: veeva_surveys_lsc.csv  (ready to upload into the LSC survey generator)
"""

import re
import sys
import pandas as pd
from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Convert display name to snake_case developer name."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s_]", "", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip("_")
    text = text[:80]
    if text and text[0].isdigit():
        text = "s_" + text
    return text


def strip_question_prefix(text: str) -> str:
    """Remove Veeva question prefix markers like QTN:, QTB-1), QTP: etc."""
    text = text.strip()
    # Remove leading prefix like "QTN:", "QTB:", "QTB-1)", "QTP:", "QTP-2."
    text = re.sub(r"^QT[NBPC][^:)\.\s]*[:\)\.\s]+\s*", "", text, flags=re.IGNORECASE)
    # Remove leading "(For the representative to answer)" style notes
    text = re.sub(r"^\(For the representative to answer\)\s*", "", text, flags=re.IGNORECASE)
    # Normalize newlines to space
    text = text.replace("\n", " ").replace("\r", " ").strip()
    return text


def parse_choices(answer_choice: str):
    """
    Veeva format: Label;weight;Label;weight;...
    Returns (labels: list[str], is_bitmask: bool)
      - labels: choice labels with whitespace stripped
      - is_bitmask: True if any weight != '0' (indicates bitmask multi-select scoring)
    """
    if not answer_choice or not answer_choice.strip():
        return [], False
    parts = [p.strip() for p in answer_choice.split(";")]
    labels  = [parts[i] for i in range(0, len(parts), 2) if parts[i].strip()]
    weights = [parts[i] for i in range(1, len(parts), 2)]
    is_bitmask = any(w != "0" for w in weights if w)
    return labels, is_bitmask


def infer_question_type(row) -> str:
    """
    Infer LSC question_type from Veeva fields.
    Priority order:
      1. Disclaimer flag              -> Description
      2. No choices                   -> FreeText
      3. Any weight != 0 (bitmask)    -> MultiselectPicklist
      4. 2 choices, all weight 0      -> RadioButton
      5. 3+ choices, all weight 0     -> Picklist  (capped at 20 during build)
    """
    is_disclaimer = str(row.get("SURVEY_DISCLAIMER__C", "0")) == "1"
    text = str(row.get("TEXT_VOD__C", "")).lower()
    choices_raw = str(row.get("ANSWER_CHOICE_VOD__C", "")).strip()

    if is_disclaimer or text.startswith("disclaimer"):
        return "Description"

    if not choices_raw:
        return "FreeText"

    labels, is_bitmask = parse_choices(choices_raw)

    if is_bitmask:
        return "MultiselectPicklist"

    if len(labels) <= 2:
        return "RadioButton"

    return "Picklist"


def parse_condition(condition: str):
    # Parse Veeva CONDITION_VOD__C: Q01="some answer value"
    # Returns (q_label, answer_value) or (None, "") if unparseable.
    # q_label matches SOURCE_ID_VOD__C exactly, e.g. "Q01".
    if not condition or not condition.strip():
        return None, ""
    m = re.search(r'(Q\d+)\s*=\s*["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]', condition)
    if m:
        return m.group(1), m.group(2).strip()
    return None, ""


# ── main transform ────────────────────────────────────────────────────────────

def transform(xlsx_path, output_path):
    xl = pd.ExcelFile(xlsx_path)
    df1 = pd.read_excel(xl, sheet_name="SURVEY_VOD", dtype=str).fillna("")
    df2 = pd.read_excel(xl, sheet_name="SURVEY_QUESTION_VOD", dtype=str).fillna("")

    # ── Step 1: build NAME → unique developer name and NAME → welcome text ──
    #
    # Tab 2 SURVEY_VOD__C already contains the display name (not the ID), so we
    # key everything by name.  Duplicate names (same display name, different IDs
    # = territory splits) each get a suffix from their record ID so their
    # questions don't mix.  Non-ASCII names that slugify to blank get an
    # ID-based fallback.

    # Count how many distinct IDs share each display name
    name_id_map = {}  # name → list of IDs
    for _, r in df1.iterrows():
        name_id_map.setdefault(r["NAME"], []).append(r["ID"])

    survey_dev_lookup  = {}   # name → developer_name  (unique names only)
    survey_dev_by_id   = {}   # id   → developer_name  (used for dup names)
    welcome_by_name    = {}   # name → welcome text     (unique names only)
    welcome_by_id      = {}   # id   → welcome text     (used for dup names)

    for _, r in df1.iterrows():
        sid  = r["ID"]
        name = r["NAME"]
        dc1  = r.get("DC1__C", "").strip()
        welcome_text = dc1 if dc1 else f"Welcome to the {name} survey. Please answer all questions."

        s = slugify(name).strip("_")
        if not s:
            s = f"survey_{sid[-8:].lower()}"

        ids_for_name = name_id_map[name]
        if len(ids_for_name) > 1:
            unique_s = f"{s}_{sid[-6:].lower()}"
        else:
            unique_s = s

        survey_dev_by_id[sid]  = unique_s[:80]
        welcome_by_id[sid]     = welcome_text

        # For non-dup names, also keep a name-keyed entry for Tab 2 lookup
        if len(ids_for_name) == 1:
            survey_dev_lookup[name] = unique_s[:80]
            welcome_by_name[name]   = welcome_text

    # ── Step 2: build survey-level welcome text — Tab 2 uses names not IDs ──
    # For duplicate-name surveys, Tab 2 questions are already pre-merged in
    # the Veeva export (SURVEY_VOD__C stores the name, not the ID), so we
    # cannot distinguish which territory instance a question belongs to.
    # We use the first ID's welcome text as the representative value.
    for name, ids in name_id_map.items():
        if name not in welcome_by_name:
            welcome_by_name[name] = welcome_by_id[ids[0]]
        if name not in survey_dev_lookup:
            survey_dev_lookup[name] = survey_dev_by_id[ids[0]]

    # ── Step 3: map SURVEY_VOD__C name → display name and developer name ──
    df2["_survey_name"] = df2["SURVEY_VOD__C"]   # already a display name
    df2["_survey_dev"]  = df2["SURVEY_VOD__C"].map(survey_dev_lookup).fillna(
        df2["SURVEY_VOD__C"].apply(lambda n: slugify(n) or f"survey_{hash(n) & 0xFFFFFF:06x}")
    )

    # ── Step 3: drop deleted rows ──
    df2 = df2[df2["ISDELETED"] != "1"].copy()

    # ── Step 4: sort by survey, then question order ──
    df2["_order_int"] = pd.to_numeric(df2["ORDER_VOD__C"], errors="coerce").fillna(0).astype(int)
    df2 = df2.sort_values(["_survey_name", "_order_int"]).reset_index(drop=True)

    import json as _json

    # ── Step 5a: build per-survey SOURCE_ID_VOD__C label → NAME map ──
    # SOURCE_ID_VOD__C on each question holds the exact Q-label (e.g. "Q01") that
    # CONDITION_VOD__C references.  This is the authoritative lookup.
    source_id_map = {}  # survey_dev → {q_label: question_NAME}
    for survey_dev, grp in df2.groupby("_survey_dev"):
        source_id_map[survey_dev] = {}
        for _, r in grp.iterrows():
            src = str(r.get("SOURCE_ID_VOD__C", "")).strip()
            if src:
                source_id_map[survey_dev][src] = r["NAME"]

    # ── Step 5b: build per-router answer → page mapping ──
    # A survey may have multiple independent routing questions (e.g. Q00 and Q01).
    # Group CONDITION_VOD__C values by their Q-label → one decisions element per router.
    #
    # answer_page_map[survey_dev] = {answer_val: page_dev_name}  (all routers combined)
    # router_rules_per_survey[survey_dev] = {router_NAME: [{answer, page}, ...]}
    answer_page_map = {}
    router_rules_per_survey = {}

    for survey_dev, grp in df2.groupby("_survey_dev"):
        grp_sorted = grp.sort_values("_order_int")

        # Collect conditions grouped by Q-label, preserving answer order
        conditions_by_label = {}   # q_label → [answer_val, ...]
        for _, r in grp_sorted.iterrows():
            cond_raw = r.get("CONDITION_VOD__C", "")
            q_label, answer_val = parse_condition(cond_raw)
            if q_label and answer_val:
                if q_label not in conditions_by_label:
                    conditions_by_label[q_label] = []
                if answer_val not in conditions_by_label[q_label]:
                    conditions_by_label[q_label].append(answer_val)

        if not conditions_by_label:
            continue

        # Assign a page to each (router, answer) pair in label-sorted, answer-order
        page_idx = 0
        ans_page_local = {}        # answer_val → page_dev_name
        router_rules_local = {}    # router_NAME → [{answer, page}, ...]

        for q_label in sorted(conditions_by_label.keys()):
            router_name = source_id_map.get(survey_dev, {}).get(q_label)
            if not router_name:
                print(f"  [WARN] {survey_dev}: no SOURCE_ID_VOD__C={q_label} found, skipping branch group",
                      file=sys.stderr)
                continue
            rules = []
            for ans in conditions_by_label[q_label]:
                if ans not in ans_page_local:
                    ans_page_local[ans] = f"p_ans_{page_idx}"
                    page_idx += 1
                rules.append({"answer": ans, "page": ans_page_local[ans]})
            router_rules_local[router_name] = rules

        if ans_page_local:
            answer_page_map[survey_dev] = ans_page_local
            router_rules_per_survey[survey_dev] = router_rules_local

    # ── Step 5: build output rows ──
    rows = []
    split_notices = []
    truncation_warnings = []
    survey_q_num = {}   # running question counter per survey (handles splits)

    # Pre-build (survey_dev, router_NAME) → branch_rules JSON
    router_branch_rules = {}
    for survey_dev, rules_by_router in router_rules_per_survey.items():
        for router_name, rules in rules_by_router.items():
            router_branch_rules[(survey_dev, router_name)] = _json.dumps(rules)

    for _, row in df2.iterrows():
        survey_name = row["_survey_name"]
        survey_dev  = row["_survey_dev"]
        survey_q_num.setdefault(survey_dev, 0)

        # Use TEXT_VOD__C verbatim — no prefix stripping
        question_text = row["TEXT_VOD__C"].strip()

        q_type    = infer_question_type(row)
        required  = "true" if str(row.get("REQUIRED_VOD__C", "0")) == "1" else "false"
        welcome   = welcome_by_name.get(survey_name, f"Welcome to the {survey_name} survey.")

        # Determine page assignment from CONDITION_VOD__C
        cond_raw = row.get("CONDITION_VOD__C", "")
        q_label, answer_val = parse_condition(cond_raw)
        ans_map = answer_page_map.get(survey_dev, {})

        if answer_val and ans_map and answer_val in ans_map:
            page_dev = ans_map[answer_val]
            # page_ord: p_ans pages start at 2; get position from sorted unique pages
            sorted_ans_pages = sorted(set(ans_map.values()),
                                      key=lambda p: int(p.split("_")[-1]))
            page_ord = sorted_ans_pages.index(page_dev) + 2
            page_lbl = f"Page {page_ord}"
        else:
            page_dev = "p_1"
            page_ord = 1
            page_lbl = "Page 1"

        # branch_rules: set only on the router question for this survey
        br_key = (survey_dev, row["NAME"])
        branch_rules_json = router_branch_rules.get(br_key, "")

        # emissions: normally 1; 2 when a Picklist is split due to >20 choices
        if q_type in ("RadioButton", "Picklist", "MultiselectPicklist"):
            choice_list, _ = parse_choices(row["ANSWER_CHOICE_VOD__C"])
            max_c = 10 if q_type == "MultiselectPicklist" else 20

            if q_type == "Picklist" and len(choice_list) > max_c:
                split_notices.append(
                    f"  ✂️  {row['NAME']} ({survey_name}): "
                    f"{len(choice_list)} choices → split into 2 questions"
                )
                emissions = [
                    (" (Part 1 of 2)", "",   "|".join(choice_list[:max_c])),
                    (" (Part 2 of 2)", "_b", "|".join(choice_list[max_c:])),
                ]
            elif len(choice_list) > max_c:
                truncation_warnings.append(
                    f"  ⚠️  {row['NAME']} ({q_type}, {survey_name}): "
                    f"{len(choice_list)} choices → truncated to {max_c}"
                )
                emissions = [("", "", "|".join(choice_list[:max_c]))]
            else:
                emissions = [("", "", "|".join(choice_list))]
        else:
            emissions = [("", "", "")]

        for text_sfx, dev_sfx, choices_str in emissions:
            survey_q_num[survey_dev] += 1
            rows.append({
                "survey_name":              survey_name,
                "survey_developer_name":    survey_dev,
                "welcome_text":             welcome,
                "thankyou_label":           "Survey Complete",
                "thankyou_text":            "Thank you for completing this survey.",
                "page_label":               page_lbl,
                "page_developer_name":      page_dev,
                "page_order":               page_ord,
                "question_text":            question_text + text_sfx,
                "question_developer_name":  row["NAME"] + dev_sfx,
                "question_type":            q_type,
                "question_order":           survey_q_num[survey_dev],
                "required":                 required,
                "choices":                  choices_str,
                "slider_min":               "",
                "slider_max":               "",
                "branch_on_answer":         "",
                "branch_to_page":           "",
                "branch_rules":             branch_rules_json,
                "visibility_rule":          "",
            })

    out = pd.DataFrame(rows)

    # ── Step 6: report ──
    if split_notices:
        print(f"Split questions ({len(split_notices)}):")
        for n in split_notices:
            print(n)
        print()
    if truncation_warnings:
        print(f"Truncation warnings ({len(truncation_warnings)}):")
        for w in truncation_warnings:
            print(w)
        print()
    print(f"Total questions transformed : {len(out)}")
    print(f"Unique surveys              : {out['survey_name'].nunique()}")
    print()
    print("Question type breakdown:")
    print(out["question_type"].value_counts().to_string())
    print()
    print("Surveys included:")
    for s in sorted(out["survey_name"].unique()):
        n = len(out[out["survey_name"] == s])
        print(f"  [{n:3d}q]  {s}")
    print()

    # ── Step 7: save (optional) ──
    if output_path:
        out.to_csv(output_path, index=False)
        print(f"Saved: {output_path}")

    return out


if __name__ == "__main__":
    base = Path(__file__).parent
    xlsx = base / "sample_data" / "SURVEY_DATA.xlsx"
    csv_out = base / "sample_data" / "veeva_surveys_lsc.csv"

    if not xlsx.exists():
        print(f"ERROR: {xlsx} not found")
        sys.exit(1)

    transform(str(xlsx), str(csv_out))
