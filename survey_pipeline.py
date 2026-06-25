"""
survey_pipeline.py — adapter layer for the Streamlit UI.

Imports from generate_surveys.py (same folder) and adds:
  - parse_uploaded()   handle CSV or Excel bytes in-memory
  - validate()         pre-flight checks before generating
  - render_to_zip()    render XML and return as in-memory ZIP bytes
  - render_to_folder() render XML and write to a local folder
"""

import csv, io, json, sys, zipfile
from collections import OrderedDict
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader

from generate_surveys import _build_surveys, parse_source, slugify, TYPE_MAP, CHOICE_TYPES

try:
    from veeva_to_lsc import transform as _veeva_transform
    _HAS_VEEVA_XLSX = True
except ImportError:
    _HAS_VEEVA_XLSX = False


def _is_veeva_xlsx(content: bytes) -> bool:
    """Return True if the Excel file has the two Veeva tabs (SURVEY_VOD + SURVEY_QUESTION_VOD)."""
    try:
        xl = pd.ExcelFile(io.BytesIO(content))
        return "SURVEY_VOD" in xl.sheet_names and "SURVEY_QUESTION_VOD" in xl.sheet_names
    except Exception:
        return False

_BASE_DIR    = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
TEMPLATE_DIR = _BASE_DIR / "templates"

REQUIRED_COLUMNS = {
    "survey_name", "survey_developer_name",
    "page_label", "page_developer_name", "page_order",
    "question_text", "question_developer_name", "question_type",
    "question_order",
}


def _load_template():
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template("survey_flow.xml.j2")


def parse_uploaded(content: bytes, filename: str) -> OrderedDict:
    """
    Parse CSV or Excel upload bytes into the raw surveys dict
    that _build_surveys() expects.

    If the file is a two-tab Veeva XLSX (SURVEY_VOD + SURVEY_QUESTION_VOD),
    it is automatically transformed via veeva_to_lsc before parsing.
    """
    if filename.lower().endswith((".xlsx", ".xls")) and _is_veeva_xlsx(content):
        if not _HAS_VEEVA_XLSX:
            raise ImportError("veeva_to_lsc.py not found — cannot transform Veeva XLSX")
        df = _veeva_transform(io.BytesIO(content), output_path=None)
        csv_str = df.to_csv(index=False)
        reader = csv.DictReader(io.StringIO(csv_str))
    elif filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(content), dtype=str)
        df = df.fillna("")
        csv_str = df.to_csv(index=False)
        reader = csv.DictReader(io.StringIO(csv_str))
    else:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))

    surveys = OrderedDict()
    for row in reader:
        row = {k: (v or "").strip() for k, v in row.items() if k}

        s_key = row.get("survey_developer_name", "").strip()
        if not s_key:
            continue

        if s_key not in surveys:
            surveys[s_key] = {
                "survey_name":           row.get("survey_name", s_key),
                "survey_developer_name": s_key,
                "welcome_text":          row.get("welcome_text", ""),
                "thankyou_label":        row.get("thankyou_label", "Thank You"),
                "thankyou_text":         row.get("thankyou_text", ""),
                "pages":                 OrderedDict(),
            }

        p_key = row.get("page_developer_name", "").strip()
        if not p_key:
            continue

        pages = surveys[s_key]["pages"]
        if p_key not in pages:
            pages[p_key] = {
                "label":          row.get("page_label", p_key),
                "developer_name": p_key,
                "order":          int(row.get("page_order", 1) or 1),
                "questions":      [],
            }

        q_type = row.get("question_type", "").strip()
        q_dev  = row.get("question_developer_name", "").strip()
        q_text = row.get("question_text", "").strip()

        if not q_dev or not q_text:
            continue

        # Parse visibility_rule from "dev_name==answer" format (produced by veeva_to_lsc)
        vis_raw = row.get("visibility_rule", "").strip()
        if "==" in vis_raw:
            vq_dev, vval = vis_raw.split("==", 1)
            visibility_rule = {"question_dev": vq_dev.strip(), "operator": "EqualTo", "value": vval.strip()}
        else:
            visibility_rule = None

        pages[p_key]["questions"].append({
            "text":             q_text,
            "developer_name":   q_dev,
            "type":             q_type,
            "question_order":   int(row.get("question_order", 1) or 1),
            "required":         row.get("required", "false").lower(),
            "choices_pipe":     row.get("choices", "").strip(),
            "slider_min":       row.get("slider_min", "1") or "1",
            "slider_max":       row.get("slider_max", "10") or "10",
            "branch_on_answer": row.get("branch_on_answer", "").strip(),
            "branch_to_page":   row.get("branch_to_page", "").strip(),
            "branch_rules":     row.get("branch_rules", "").strip(),
            "visibility_rule":  visibility_rule,
        })

    return surveys


def validate(raw_surveys: OrderedDict, columns: list) -> list:
    """
    Returns list of dicts: {survey, level ("error"|"warning"), message}
    Errors block generation; warnings are shown inline.
    """
    issues = []

    missing = REQUIRED_COLUMNS - set(c.strip() for c in columns)
    if missing:
        issues.append({
            "survey": "ALL",
            "level": "error",
            "message": f"Missing required columns: {', '.join(sorted(missing))}",
        })
        return issues  # Can't validate further without required columns

    for s_dev, s in raw_surveys.items():
        all_page_keys = set(s["pages"].keys())

        for p_dev, page in s["pages"].items():
            seen_q_devs = set()
            for q in page["questions"]:
                # Unknown type
                if q["type"] and q["type"] not in TYPE_MAP:
                    issues.append({
                        "survey": s_dev,
                        "level": "error",
                        "message": f"Unknown question_type '{q['type']}' on '{q['developer_name']}' (page: {p_dev})",
                    })

                # Duplicate developer_name within survey
                if q["developer_name"] in seen_q_devs:
                    issues.append({
                        "survey": s_dev,
                        "level": "error",
                        "message": f"Duplicate question_developer_name '{q['developer_name']}' on page '{p_dev}'",
                    })
                seen_q_devs.add(q["developer_name"])

                # branch_to_page references a missing page
                if q["branch_to_page"] and q["branch_to_page"] not in all_page_keys:
                    issues.append({
                        "survey": s_dev,
                        "level": "error",
                        "message": f"branch_to_page '{q['branch_to_page']}' not found in survey pages",
                    })

                # Choices expected but empty (Rating/CSAT auto-generate from slider_min/max)
                AUTO_CHOICE_TYPES = {"Rating", "CSAT"}
                if q["type"] in CHOICE_TYPES and q["type"] not in AUTO_CHOICE_TYPES and not q["choices_pipe"]:
                    issues.append({
                        "survey": s_dev,
                        "level": "warning",
                        "message": f"Question '{q['developer_name']}' is type '{q['type']}' but has no choices",
                    })

                # Choice constraint validations
                if q["type"] in CHOICE_TYPES and q["choices_pipe"]:
                    choices = [c.strip() for c in q["choices_pipe"].split("|") if c.strip()]
                    max_choices = 10 if q["type"] == "MultiselectPicklist" else 20
                    if len(choices) > max_choices:
                        issues.append({
                            "survey": s_dev,
                            "level": "error",
                            "message": f"Question '{q['developer_name']}' ({q['type']}) has {len(choices)} choices — max is {max_choices}",
                        })
                    for choice in choices:
                        if len(choice) > 200:
                            issues.append({
                                "survey": s_dev,
                                "level": "error",
                                "message": f"Question '{q['developer_name']}': choice '{choice[:40]}...' exceeds 200 characters",
                            })
                        if ";" in choice:
                            issues.append({
                                "survey": s_dev,
                                "level": "error",
                                "message": f"Question '{q['developer_name']}': choice '{choice}' contains a semicolon (not allowed)",
                            })

                # Welcome text missing
        if not s.get("welcome_text"):
            issues.append({
                "survey": s_dev,
                "level": "warning",
                "message": "No welcome_text — welcome page will be blank",
            })

    return issues


def build(raw_surveys) -> list:
    """Thin wrapper around _build_surveys() from generate_surveys.py."""
    import copy
    raw_surveys = copy.deepcopy(raw_surveys)
    if isinstance(raw_surveys, list):
        raw_surveys = OrderedDict((s["survey_developer_name"], s) for s in raw_surveys)
    return _build_surveys(raw_surveys)


def render_to_zip(surveys: list) -> bytes:
    """Render all surveys to XML and return as in-memory ZIP bytes."""
    tpl = _load_template()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for s in surveys:
            xml = tpl.render(**s)
            zf.writestr(f"{s['survey_developer_name']}.flow-meta.xml", xml)
    return buf.getvalue()


def render_to_folder(surveys: list, output_dir: str) -> list:
    """Write .flow-meta.xml files to a local folder. Returns filenames written."""
    tpl = _load_template()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for s in surveys:
        path = out / f"{s['survey_developer_name']}.flow-meta.xml"
        path.write_text(tpl.render(**s), encoding="utf-8")
        written.append(path.name)
    return written
