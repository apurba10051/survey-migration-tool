"""
Survey Generator v2 — Streamlit UI (Salesforce Lightning Design)
Upload CSV or Excel → Preview surveys → Generate LSC OfflineMobile Flow XML
"""

import streamlit as st
import pandas as pd
import io
from pathlib import Path

from survey_pipeline import parse_uploaded, validate, build, render_to_zip, render_to_folder, TYPE_MAP

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Survey Flow Generator",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── Salesforce Lightning CSS ─────────────────────────────────────────────────
st.markdown("""
<style>
  /* ── Fonts & base ── */
  @import url('https://fonts.googleapis.com/css2?family=Salesforce+Sans:wght@400;600;700&family=Inter:wght@400;500;600;700&display=swap');

  html, body, [class*="css"] {
    font-family: 'Inter', 'Salesforce Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    color: #181818;
  }

  /* ── App background & kill all Streamlit spacing ── */
  .stApp { background-color: #f3f3f3; }

  /* Remove ALL default Streamlit container padding/margin */
  .block-container,
  .stAppViewBlockContainer,
  [data-testid="stAppViewContainer"] > section > .block-container {
    padding: 0 !important;
    margin: 0 !important;
    max-width: 100% !important;
  }

  /* Tighten Streamlit default spacing — but NOT element-container (breaks widget spacing) */
  .stMarkdown { margin-top: 0 !important; }

  /* Kill row-gap only at top level page blocks, not inside columns */
  [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] {
    padding-top: 0 !important;
    padding-bottom: 0 !important;
  }

  /* Streamlit toolbar (deploy/menu bar at top) — collapse it */
  [data-testid="stToolbar"]     { display: none !important; }
  [data-testid="stDecoration"]  { display: none !important; }
  .stMainBlockContainer         { padding-top: 0 !important; }

  /* ── Global header bar (Salesforce nav) ── */
  .slds-global-header {
    background: #0176d3;
    padding: 0 1.5rem;
    height: 52px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    box-shadow: 0 2px 4px rgba(0,0,0,.2);
    position: sticky;
    top: 0;
    z-index: 999;
  }
  .slds-global-header .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    color: #fff;
    font-size: 1rem;
    font-weight: 700;
    letter-spacing: .3px;
  }
  .slds-global-header .brand svg { opacity: .95; }
  .slds-global-header .tagline {
    color: rgba(255,255,255,.75);
    font-size: 0.78rem;
    font-weight: 400;
  }

  /* ── Page wrapper ── */
  .page-body { padding: 0.75rem 1.5rem 2rem; }

  /* ── Card ── */
  .slds-card {
    background: #fff;
    border-radius: 0.25rem;
    border: 1px solid #dddbda;
    box-shadow: 0 2px 2px rgba(0,0,0,.05);
    margin-bottom: 0.75rem;
    overflow: hidden;
  }
  .slds-card__header {
    background: #fafaf9;
    border-bottom: 1px solid #dddbda;
    padding: 0.65rem 1rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .slds-card__header-title {
    font-size: 0.875rem;
    font-weight: 700;
    color: #181818;
    text-transform: uppercase;
    letter-spacing: .5px;
  }
  .slds-card__header-badge {
    background: #0176d3;
    color: #fff;
    border-radius: 999px;
    font-size: 0.7rem;
    font-weight: 700;
    padding: 1px 8px;
    margin-left: 6px;
  }
  .slds-card__body { padding: 0.6rem 0.75rem 0.75rem; }

  /* ── Section step indicator ── */
  .step-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #0176d3;
    color: #fff;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 700;
    padding: 3px 12px 3px 4px;
    margin: 0.6rem 0 0.3rem;
    letter-spacing: .3px;
  }
  .step-pill .num {
    background: #fff;
    color: #0176d3;
    border-radius: 50%;
    width: 20px;
    height: 20px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.75rem;
    font-weight: 800;
  }

  /* ── Metric tiles ── */
  .slds-metric-row { display: flex; gap: 1rem; margin-bottom: 1rem; }
  .slds-metric {
    flex: 1;
    background: #fff;
    border: 1px solid #dddbda;
    border-radius: 0.25rem;
    padding: 0.85rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .slds-metric__label { font-size: 0.72rem; font-weight: 600; color: #706e6b; text-transform: uppercase; letter-spacing: .5px; }
  .slds-metric__value { font-size: 1.75rem; font-weight: 700; color: #181818; line-height: 1; }
  .slds-metric--blue  .slds-metric__value { color: #0176d3; }
  .slds-metric--red   .slds-metric__value { color: #ba0517; }
  .slds-metric--orange .slds-metric__value { color: #fe9339; }

  /* ── Badge ── */
  .slds-badge {
    display: inline-block;
    border-radius: 999px;
    font-size: 0.7rem;
    font-weight: 700;
    padding: 2px 10px;
    letter-spacing: .3px;
  }
  .slds-badge--success { background: #2e844a1a; color: #2e844a; border: 1px solid #2e844a40; }
  .slds-badge--error   { background: #ba05171a; color: #ba0517; border: 1px solid #ba051740; }
  .slds-badge--warning { background: #fe93391a; color: #a85500; border: 1px solid #fe933940; }
  .slds-badge--neutral { background: #f3f3f3;   color: #706e6b; border: 1px solid #dddbda; }

  /* ── Alert boxes ── */
  .slds-notify--error {
    background: #fef1ee; border-left: 4px solid #ba0517;
    border-radius: 0.25rem; padding: 0.65rem 1rem;
    margin-bottom: 0.5rem; color: #181818; font-size: 0.85rem;
  }
  .slds-notify--warning {
    background: #fffaef; border-left: 4px solid #fe9339;
    border-radius: 0.25rem; padding: 0.65rem 1rem;
    margin-bottom: 0.5rem; color: #181818; font-size: 0.85rem;
  }
  .slds-notify--success {
    background: #eef6ec; border-left: 4px solid #2e844a;
    border-radius: 0.25rem; padding: 0.65rem 1rem;
    margin-bottom: 0.5rem; color: #181818; font-size: 0.85rem;
  }
  .slds-notify--info {
    background: #eaf4ff; border-left: 4px solid #0176d3;
    border-radius: 0.25rem; padding: 0.65rem 1rem;
    margin-bottom: 0.5rem; color: #181818; font-size: 0.85rem;
  }

  /* ── Survey accordion row ── */
  .survey-row {
    border: 1px solid #dddbda;
    border-radius: 0.25rem;
    background: #fff;
    margin-bottom: 0.5rem;
  }
  .survey-row__header {
    padding: 0.6rem 1rem;
    font-size: 0.85rem;
    font-weight: 600;
    color: #0176d3;
    background: #fafaf9;
    border-bottom: 1px solid #dddbda;
    border-radius: 0.25rem 0.25rem 0 0;
  }
  .survey-row__body { padding: 0.75rem 1rem; }

  /* ── Page label chip ── */
  .page-chip {
    display: inline-block;
    background: #e8f4ff;
    color: #0176d3;
    border: 1px solid #a8d4f5;
    border-radius: 0.2rem;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 2px 8px;
    margin: 0.5rem 0 0.4rem;
    letter-spacing: .2px;
  }

  /* ── File result row ── */
  .file-result {
    font-size: 0.8rem;
    padding: 4px 0;
    color: #181818;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .file-result .dot { color: #2e844a; font-size: 1rem; }

  /* ── Override Streamlit default button ── */
  .stButton > button {
    background: #0176d3 !important;
    color: #fff !important;
    border: none !important;
    border-radius: 0.25rem !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    padding: 0.45rem 1.2rem !important;
    transition: background .15s;
  }
  .stButton > button:hover { background: #014486 !important; }
  .stButton > button:disabled { background: #dddbda !important; color: #706e6b !important; }

  /* ── Override Streamlit download button ── */
  .stDownloadButton > button {
    background: #fff !important;
    color: #0176d3 !important;
    border: 1px solid #0176d3 !important;
    border-radius: 0.25rem !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
  }
  .stDownloadButton > button:hover { background: #eaf4ff !important; }

  /* ── File uploader — compact, flush inside card ── */
  [data-testid="stFileUploader"] {
    margin: 0 !important;
    padding: 0 !important;
    border: none !important;
    background: transparent !important;
  }
  [data-testid="stFileUploaderDropzone"],
  [data-testid="stFileUploader"] > section {
    border: 2px dashed #a8d4f5 !important;
    border-radius: 0.2rem !important;
    background: #f4f9ff !important;
    padding: 0.5rem 0.75rem !important;
    min-height: unset !important;
    margin: 0 !important;
  }
  [data-testid="stFileUploaderDropzoneInput"] { display: none; }
  /* Shrink the upload button row */
  [data-testid="stFileUploader"] button {
    padding: 0.25rem 0.75rem !important;
    font-size: 0.8rem !important;
  }

  /* ── Override Streamlit expander ── */
  details { border: 1px solid #dddbda !important; border-radius: 0.25rem !important; margin-bottom: 0.4rem !important; }
  details summary { font-weight: 600 !important; font-size: 0.85rem !important; color: #0176d3 !important; padding: 0.5rem 0.75rem !important; background: #fafaf9 !important; }

  /* ── Override Streamlit dataframe ── */
  [data-testid="stDataFrame"] { border: 1px solid #dddbda !important; border-radius: 0.25rem !important; }

  /* ── Override metric ── */
  [data-testid="stMetric"] { background: #fff; border: 1px solid #dddbda; border-radius: 0.25rem; padding: 0.75rem 1rem; }

  /* ── Hide Streamlit default chrome ── */
  #MainMenu, footer, header { visibility: hidden; }
  .stDeployButton { display: none; }
</style>
""", unsafe_allow_html=True)

# ─── Global header ────────────────────────────────────────────────────────────
st.markdown("""
<div class="slds-global-header">
  <div class="brand">
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
      <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z" fill="rgba(255,255,255,0.25)"/>
      <path d="M13 7h-2v5H7v2h6V7z" fill="white"/>
    </svg>
    Survey Flow Generator
    <span class="tagline">· LSC OfflineMobile · Salesforce</span>
  </div>
  <span style="color:rgba(255,255,255,.6);font-size:.75rem;">v2.0</span>
</div>
<div class="page-body">
""", unsafe_allow_html=True)

# ─── Session state ────────────────────────────────────────────────────────────
for key in ("raw_surveys", "built_surveys", "issues", "df", "columns"):
    if key not in st.session_state:
        st.session_state[key] = None


# ─── Section 1: Upload ────────────────────────────────────────────────────────
st.markdown("""
<div class="step-pill"><span class="num">1</span>UPLOAD SOURCE FILE</div>
<div class="slds-card">
  <div class="slds-card__header">
    <span class="slds-card__header-title">📂 Survey Source File</span>
  </div>
  <div class="slds-card__body">
""", unsafe_allow_html=True)

uploaded = st.file_uploader(
    "Upload CSV or Excel file",
    type=["csv", "xlsx", "xls"],
    help="CSV: one row per question using generate_surveys.py column format. Excel with same columns is also supported.",
    label_visibility="collapsed",
)

if uploaded:
    # Only re-parse when a NEW file is uploaded — not on every rerun
    file_id = f"{uploaded.name}_{uploaded.size}"
    if st.session_state.get("uploaded_file_id") != file_id:
        content = uploaded.read()
        try:
            from survey_pipeline import _is_veeva_xlsx, _veeva_transform, _HAS_VEEVA_XLSX
            is_veeva = (uploaded.name.lower().endswith((".xlsx", ".xls"))
                        and _is_veeva_xlsx(content))

            if is_veeva and _HAS_VEEVA_XLSX:
                df = _veeva_transform(io.BytesIO(content), output_path=None)
            elif uploaded.name.lower().endswith((".xlsx", ".xls")):
                df = pd.read_excel(io.BytesIO(content), dtype=str).fillna("")
            else:
                df = pd.read_csv(io.StringIO(content.decode("utf-8-sig")), dtype=str).fillna("")

            st.session_state.df                = df
            st.session_state.columns           = list(df.columns)
            raw                                = parse_uploaded(content, uploaded.name)
            st.session_state.raw_surveys       = raw
            st.session_state.issues            = validate(raw, list(df.columns))
            st.session_state.built_surveys     = None
            st.session_state.save_result       = None
            st.session_state.folder_path_input = ""
            st.session_state.uploaded_file_id  = file_id

        except Exception as e:
            st.markdown(f'<div class="slds-notify--error">❌ Failed to parse file: {e}</div>',
                        unsafe_allow_html=True)
            st.stop()

    # Always show loaded message from session state (survives reruns)
    if st.session_state.get("df") is not None and st.session_state.get("raw_surveys") is not None:
        st.markdown(f"""
        <div class="slds-notify--success">
          ✅ &nbsp;<strong>{uploaded.name}</strong> loaded —
          <strong>{len(st.session_state.df)}</strong> rows ·
          <strong>{len(st.session_state.raw_surveys)}</strong> survey(s) detected
        </div>
        """, unsafe_allow_html=True)
else:
    st.markdown('<div class="slds-notify--info">ℹ️ &nbsp;Upload a CSV or Excel file to get started.</div>',
                unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)
    st.stop()

st.markdown("</div></div>", unsafe_allow_html=True)


# ─── Section 2: Raw Data Preview ──────────────────────────────────────────────
st.markdown("""
<div class="step-pill"><span class="num">2</span>RAW DATA PREVIEW</div>
<div class="slds-card">
  <div class="slds-card__header">
    <span class="slds-card__header-title">📄 Uploaded Records</span>
  </div>
  <div class="slds-card__body">
""", unsafe_allow_html=True)

df = st.session_state.df
with st.expander(f"Show raw data — {len(df)} rows", expanded=False):
    if len(df) > 200:
        show_all = st.checkbox("Show all rows (may be slow for large files)", value=False)
        st.dataframe(df if show_all else df.head(200), use_container_width=True)
        if not show_all:
            st.caption(f"Showing first 200 of {len(df)} rows.")
    else:
        st.dataframe(df, use_container_width=True)

st.markdown("</div></div>", unsafe_allow_html=True)


# ─── Section 3: Survey Preview ────────────────────────────────────────────────
st.markdown("""
<div class="step-pill"><span class="num">3</span>SURVEY PREVIEW</div>
<div class="slds-card">
  <div class="slds-card__header">
    <span class="slds-card__header-title">🔍 Parsed Surveys</span>
  </div>
  <div class="slds-card__body">
""", unsafe_allow_html=True)

raw    = st.session_state.raw_surveys
issues = st.session_state.issues
errors   = [i for i in issues if i["level"] == "error"]
warnings = [i for i in issues if i["level"] == "warning"]

# ── Helpers ───────────────────────────────────────────────────────────────────
def pages_list(s):
    p = s["pages"]
    return list(p.values()) if isinstance(p, dict) else p

def pages_items(s):
    p = s["pages"]
    if isinstance(p, dict):
        return sorted(p.items(), key=lambda x: x[1]["order"])
    return [(pg["developer_name"], pg) for pg in p]

def surveys_iter(raw):
    if isinstance(raw, dict):
        return raw.items()
    return [(s["survey_developer_name"], s) for s in raw]

def q_order(q):
    return q.get("question_order", q.get("order", 0))

def q_choices(q):
    if "choices_pipe" in q:
        raw_c = q["choices_pipe"]
        return raw_c.replace("|", " | ") if raw_c else "—"
    choices = q.get("choices", [])
    return " | ".join(c["text"] for c in choices) if choices else "—"

def type_counts(pl):
    from collections import Counter
    c = Counter()
    for p in pl:
        for q in p["questions"]:
            c[q["type"]] += 1
    return c

def format_types_short(counter):
    TYPE_SHORT = {
        "Picklist": "Picklist", "RadioButton": "RadioBtn",
        "FreeText": "FreeText", "Disclaimer": "Disclaimer",
        "ShortText": "ShortText", "MultiSelect": "MultiSel",
        "Rating": "Rating", "CSAT": "CSAT",
        "Slider": "Slider", "Date": "Date", "Number": "Number",
    }
    parts = []
    for t, n in sorted(counter.items(), key=lambda x: -x[1]):
        label = TYPE_SHORT.get(t, t)
        parts.append(f"{label}×{n}" if n > 1 else label)
    return ", ".join(parts) if parts else "—"

def has_branching(pl):
    return any(
        q.get("branch_on_answer") or q.get("branch_to_page")
        for p in pl for q in p["questions"]
    )

def get_branch_rules(pl):
    seen, rules = set(), []
    for p in pl:
        for q in p["questions"]:
            ans = q.get("branch_on_answer", "")
            tgt = q.get("branch_to_page", "")
            if ans or tgt:
                key = (q["text"][:60], ans, tgt)
                if key not in seen:
                    seen.add(key)
                    q_label = q["text"]
                    rules.append({
                        "Router Question": (q_label[:70] + "…") if len(q_label) > 70 else q_label,
                        "If Answer":       ans or "—",
                        "→ Go To Page":    tgt or "—",
                    })
    return rules

# ── Metric tiles ──────────────────────────────────────────────────────────────
total_questions  = sum(sum(len(p["questions"]) for p in pages_list(s)) for _, s in surveys_iter(raw))
branching_count  = sum(1 for _, s in surveys_iter(raw) if has_branching(pages_list(s)))
err_cls  = "slds-metric--red"    if errors   else "slds-metric--blue"
warn_cls = "slds-metric--orange" if warnings else "slds-metric--blue"

st.markdown(f"""
<div class="slds-metric-row">
  <div class="slds-metric slds-metric--blue">
    <div class="slds-metric__label">Surveys</div>
    <div class="slds-metric__value">{sum(1 for _ in surveys_iter(raw))}</div>
  </div>
  <div class="slds-metric slds-metric--blue">
    <div class="slds-metric__label">Total Questions</div>
    <div class="slds-metric__value">{total_questions}</div>
  </div>
  <div class="slds-metric slds-metric--blue">
    <div class="slds-metric__label">With Branching</div>
    <div class="slds-metric__value">{branching_count}</div>
  </div>
  <div class="slds-metric {err_cls}">
    <div class="slds-metric__label">Errors</div>
    <div class="slds-metric__value">{len(errors)}</div>
  </div>
  <div class="slds-metric {warn_cls}">
    <div class="slds-metric__label">Warnings</div>
    <div class="slds-metric__value">{len(warnings)}</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Errors / Warnings ─────────────────────────────────────────────────────────
if errors:
    for e in errors:
        prefix = f"[{e['survey']}] " if e["survey"] != "ALL" else ""
        st.markdown(f'<div class="slds-notify--error">❌ &nbsp;{prefix}{e["message"]}</div>',
                    unsafe_allow_html=True)
if warnings:
    with st.expander(f"⚠️ {len(warnings)} warning(s) — generation still allowed"):
        for w in warnings:
            st.markdown(f'<div class="slds-notify--warning">⚠️ &nbsp;[{w["survey"]}] {w["message"]}</div>',
                        unsafe_allow_html=True)

# ── Summary table ─────────────────────────────────────────────────────────────
summary_rows = []
for s_dev, s in surveys_iter(raw):
    pl      = pages_list(s)
    q_count = sum(len(p["questions"]) for p in pl)
    tc      = type_counts(pl)
    br      = has_branching(pl)
    s_err   = any(i["survey"] == s_dev for i in errors)
    s_warn  = any(i["survey"] == s_dev for i in warnings)
    summary_rows.append({
        "Survey Name":   s["survey_name"],
        "Pages":         len(pl),
        "Questions":     q_count,
        "Branching":     "Yes" if br else "No",
        "Branch Rules":  len(get_branch_rules(pl)) if br else 0,
        "Picklist":      tc.get("Picklist", 0),
        "RadioButton":   tc.get("RadioButton", 0),
        "FreeText":      tc.get("FreeText", 0),
        "Disclaimer":    tc.get("Disclaimer", 0),
        "Other Types":   format_types_short(
                             {k: v for k, v in tc.items()
                              if k not in ("Picklist", "RadioButton", "FreeText", "Disclaimer")}),
        "Status":        "❌ Error" if s_err else ("⚠️ Warning" if s_warn else "✅ Ready"),
    })

st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True,
             column_config={
                 "Survey Name":  st.column_config.TextColumn(width="large"),
                 "Pages":        st.column_config.NumberColumn(width="small"),
                 "Questions":    st.column_config.NumberColumn(width="small"),
                 "Branching":    st.column_config.TextColumn(width="small"),
                 "Branch Rules": st.column_config.NumberColumn(width="small"),
                 "Picklist":     st.column_config.NumberColumn(width="small"),
                 "RadioButton":  st.column_config.NumberColumn(width="small"),
                 "FreeText":     st.column_config.NumberColumn(width="small"),
                 "Disclaimer":   st.column_config.NumberColumn(width="small"),
                 "Other Types":  st.column_config.TextColumn(width="medium"),
                 "Status":       st.column_config.TextColumn(width="small"),
             })

# ── Per-survey expanders ───────────────────────────────────────────────────────
st.markdown("<hr style='border:none;border-top:1px solid #dddbda;margin:1rem 0 0.5rem'>",
            unsafe_allow_html=True)

search_q = st.text_input("🔍 Filter surveys", placeholder="Type survey name to filter…",
                         label_visibility="visible", key="survey_search")

survey_list = list(surveys_iter(raw))
if search_q:
    survey_list = [(dev, s) for dev, s in survey_list
                   if search_q.lower() in s["survey_name"].lower()]
    if not survey_list:
        st.caption("No surveys match the filter.")

for s_dev, s in survey_list:
    s_errors   = [i for i in errors   if i["survey"] == s_dev]
    s_warnings = [i for i in warnings if i["survey"] == s_dev]
    icon       = "❌" if s_errors else ("⚠️" if s_warnings else "✅")
    pl         = pages_list(s)
    q_count    = sum(len(p["questions"]) for p in pl)
    branching  = has_branching(pl)
    tc         = type_counts(pl)
    branch_rules  = get_branch_rules(pl)
    branch_targets = {r["→ Go To Page"] for r in branch_rules}

    expander_label = (
        f"{icon}  {s['survey_name']}"
        f"  —  {len(pl)} page(s)  ·  {q_count} Q"
        + ("  · 🔀 Branching" if branching else "")
    )

    with st.expander(expander_label):

        # ── Stats badges strip ───────────────────────────────────────────
        branch_badge = (
            f'<span class="slds-badge slds-badge--success">🔀 Branching · {len(branch_rules)} rule(s)</span>'
            if branching else
            '<span class="slds-badge slds-badge--neutral">➡ Linear</span>'
        )
        type_badges = " ".join(
            f'<span class="slds-badge slds-badge--neutral">{t}×{n}</span>'
            for t, n in sorted(tc.items(), key=lambda x: -x[1])
        )
        st.markdown(f"""
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:0.75rem;align-items:center">
          <span class="slds-badge slds-badge--neutral">📄 {len(pl)} pages</span>
          <span class="slds-badge slds-badge--neutral">❓ {q_count} questions</span>
          {branch_badge}
          {type_badges}
        </div>
        """, unsafe_allow_html=True)

        # ── Survey metadata row ──────────────────────────────────────────
        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            st.markdown(f"**API Name**  \n`{s_dev}`")
        with mc2:
            wt = s.get("welcome_text") or "—"
            st.markdown(f"**Welcome Text**  \n{(wt[:80] + '…') if len(wt) > 80 else wt}")
        with mc3:
            ty = s.get("thankyou_text") or "—"
            tl = s.get("thankyou_label") or "Thank You"
            st.markdown(f"**Thank-You** _{tl}_  \n{(ty[:80] + '…') if len(ty) > 80 else ty}")

        for issue in s_errors:
            st.markdown(f'<div class="slds-notify--error">❌ &nbsp;{issue["message"]}</div>',
                        unsafe_allow_html=True)
        for issue in s_warnings:
            st.markdown(f'<div class="slds-notify--warning">⚠️ &nbsp;{issue["message"]}</div>',
                        unsafe_allow_html=True)

        # ── Branch logic table ───────────────────────────────────────────
        if branching and branch_rules:
            st.markdown("""
            <div style="font-size:.75rem;font-weight:700;color:#706e6b;text-transform:uppercase;
                        letter-spacing:.5px;margin:0.75rem 0 0.3rem;border-top:1px solid #dddbda;
                        padding-top:0.6rem">🔀 Branch Logic</div>
            """, unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(branch_rules), use_container_width=True, hide_index=True,
                         column_config={
                             "Router Question": st.column_config.TextColumn(width="large"),
                             "If Answer":       st.column_config.TextColumn(width="medium"),
                             "→ Go To Page":    st.column_config.TextColumn(width="medium"),
                         })

        # ── Page-by-page structure ───────────────────────────────────────
        st.markdown("""
        <div style="font-size:.75rem;font-weight:700;color:#706e6b;text-transform:uppercase;
                    letter-spacing:.5px;margin:0.75rem 0 0.3rem;border-top:1px solid #dddbda;
                    padding-top:0.6rem">📋 Page Structure</div>
        """, unsafe_allow_html=True)

        for p_dev, page in pages_items(s):
            page_q_count  = len(page["questions"])
            page_tc       = type_counts([page])
            is_target     = p_dev in branch_targets
            left_color    = "#2e844a" if is_target else "#0176d3"
            target_tag    = (' <span style="background:#2e844a;color:#fff;font-size:.65rem;'
                             'font-weight:700;border-radius:999px;padding:1px 7px;margin-left:6px">'
                             'BRANCH TARGET</span>') if is_target else ""
            type_str      = format_types_short(page_tc)

            st.markdown(f"""
            <div style="background:#f8f8f8;border:1px solid #e0e0e0;
                        border-left:3px solid {left_color};
                        border-radius:0 0.2rem 0.2rem 0;
                        padding:0.45rem 0.75rem;margin:0.35rem 0 0.15rem;
                        display:flex;align-items:center;justify-content:space-between;
                        flex-wrap:wrap;gap:4px">
              <div>
                <span style="font-size:.82rem;font-weight:700;color:#181818">
                  Page {page['order']}: {page['label']}
                </span>{target_tag}
                <span style="color:#706e6b;font-size:.7rem;margin-left:8px">
                  <code>{p_dev}</code>
                </span>
              </div>
              <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
                <span class="slds-badge slds-badge--neutral">{page_q_count} Q</span>
                <span style="font-size:.72rem;color:#706e6b">{type_str}</span>
              </div>
            </div>
            """, unsafe_allow_html=True)

            if page["questions"]:
                q_rows = []
                for q in sorted(page["questions"], key=q_order):
                    q_type = q["type"] if q["type"] in TYPE_MAP else f"❌ {q['type']}"
                    q_req  = "Yes" if str(q.get("required", "false")).lower() == "true" else "No"
                    row = {
                        "#":        q_order(q),
                        "Question": q["text"],
                        "Type":     q_type,
                        "Required": q_req,
                        "Choices":  q_choices(q),
                    }
                    if branching:
                        row["Branch If Answer"] = q.get("branch_on_answer") or "—"
                        row["Branch To Page"]   = q.get("branch_to_page")   or "—"
                    q_rows.append(row)

                col_cfg = {
                    "#":        st.column_config.NumberColumn(width="small"),
                    "Question": st.column_config.TextColumn(width="large"),
                    "Type":     st.column_config.TextColumn(width="medium"),
                    "Required": st.column_config.TextColumn(width="small"),
                    "Choices":  st.column_config.TextColumn(width="large"),
                }
                if branching:
                    col_cfg["Branch If Answer"] = st.column_config.TextColumn(width="medium")
                    col_cfg["Branch To Page"]   = st.column_config.TextColumn(width="medium")

                st.dataframe(pd.DataFrame(q_rows), use_container_width=True,
                             hide_index=True, column_config=col_cfg)
            else:
                st.caption("No questions on this page.")

st.markdown("</div></div>", unsafe_allow_html=True)


# ─── Section 4: Generate & Download ──────────────────────────────────────────
st.markdown("""
<div class="step-pill"><span class="num">4</span>GENERATE XML</div>
<div class="slds-card">
  <div class="slds-card__header">
    <span class="slds-card__header-title">⚙️ Generate Flow XML</span>
  </div>
  <div class="slds-card__body">
""", unsafe_allow_html=True)

if errors:
    st.markdown('<div class="slds-notify--error">❌ &nbsp;Fix the errors above before generating.</div>',
                unsafe_allow_html=True)
else:
    if st.button("⚙️  Generate XML Files"):
        with st.spinner("Building survey flows..."):
            try:
                built = build(raw)
                st.session_state.built_surveys = built
            except Exception as e:
                st.markdown(f'<div class="slds-notify--error">❌ &nbsp;Generation failed: {e}</div>',
                            unsafe_allow_html=True)

if st.session_state.built_surveys:
    built = st.session_state.built_surveys

    result_html = "".join(
        f'<div class="file-result"><span class="dot">✓</span>'
        f'<code>{s["survey_developer_name"]}.flow-meta.xml</code>'
        f'&nbsp;—&nbsp;{len(s["all_questions"])} question(s), {len(s["pages"])} page(s)</div>'
        for s in built
    )
    st.markdown(f"""
    <div class="slds-notify--success">
      ✅ &nbsp;<strong>{len(built)} survey(s) generated successfully</strong>
      <div style="margin-top:0.5rem">{result_html}</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<hr style='border:none;border-top:1px solid #dddbda;margin:1rem 0'>",
                unsafe_allow_html=True)

    dl_col, save_col = st.columns(2)

    # ── Download as ZIP ───────────────────────────────────────────────
    with dl_col:
        st.markdown("""
        <div style="background:#fff;border:1px solid #dddbda;border-radius:0.25rem;
                    padding:0.75rem 1rem 0.75rem;">
          <div style="font-size:.75rem;font-weight:700;color:#706e6b;text-transform:uppercase;
                      letter-spacing:.5px;margin-bottom:0.6rem;">⬇️ Download as ZIP</div>
        """, unsafe_allow_html=True)
        try:
            zip_bytes = render_to_zip(built)
            st.download_button(
                label="⬇️  Download flows.zip",
                data=zip_bytes,
                file_name="flows.zip",
                mime="application/zip",
                key="dl_zip_btn",
                type="primary",
            )
        except Exception as e:
            st.markdown(f'<div class="slds-notify--error">❌ &nbsp;ZIP failed: {e}</div>',
                        unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # ── Save to Local Folder ──────────────────────────────────────────
    with save_col:
        st.markdown("""
        <div style="background:#fff;border:1px solid #dddbda;border-radius:0.25rem;
                    padding:0.75rem 1rem 0.75rem;">
          <div style="font-size:.75rem;font-weight:700;color:#706e6b;text-transform:uppercase;
                      letter-spacing:.5px;margin-bottom:0.6rem;">💾 Save to Local Folder</div>
        """, unsafe_allow_html=True)

        # Single source of truth — widget key manages the value
        st.text_input(
            "Output folder path",
            placeholder="/Users/you/project/force-app/main/default/flows",
            label_visibility="collapsed",
            key="folder_path_input",
        )

        if st.button("💾  Save to Folder", key="save_folder_btn"):
            folder_path = st.session_state.get("folder_path_input", "").strip()
            if not folder_path:
                st.session_state.save_result = ("error", "Please enter a folder path.")
            else:
                try:
                    written = render_to_folder(built, folder_path)
                    files = "  ·  ".join(written)
                    st.session_state.save_result = ("success", f"Saved {len(written)} file(s) to {folder_path}  —  {files}")
                except PermissionError:
                    st.session_state.save_result = ("error", f"Permission denied: cannot write to {folder_path}")
                except Exception as e:
                    st.session_state.save_result = ("error", str(e))

        # Show persistent result message
        if "save_result" in st.session_state and st.session_state.save_result:
            level, msg = st.session_state.save_result
            css = "slds-notify--success" if level == "success" else "slds-notify--error"
            icon = "✅" if level == "success" else "❌"
            st.markdown(f'<div class="{css}">{icon} &nbsp;{msg}</div>',
                        unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

st.markdown("</div></div>", unsafe_allow_html=True)

# close page-body div
st.markdown("</div>", unsafe_allow_html=True)
