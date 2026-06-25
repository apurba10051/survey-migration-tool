# Survey Generator — End-to-End Technical Documentation

**Version:** 2.0  
**Covers:** `veeva_to_lsc.py`, `generate_surveys.py`, `survey_pipeline.py`, `survey_app.py`, `templates/survey_flow.xml.j2`

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Repository Structure](#2-repository-structure)
3. [End-to-End Pipeline](#3-end-to-end-pipeline)
4. [Input Formats](#4-input-formats)
5. [Veeva XLSX Transformation Pipeline](#5-veeva-xlsx-transformation-pipeline)
6. [Field Mapping: Veeva → LSC CSV](#6-field-mapping-veeva--lsc-csv)
7. [LSC CSV Column Reference](#7-lsc-csv-column-reference)
8. [Build Pipeline — `_build_surveys()`](#8-build-pipeline--_build_surveys)
9. [Flow XML Template](#9-flow-xml-template)
10. [Streamlit UI — `survey_app.py`](#10-streamlit-ui--survey_apppy)
11. [Deployment to Salesforce](#11-deployment-to-salesforce)
12. [Special Logic Reference](#12-special-logic-reference)
13. [Quick Start: Direct CSV Input](#13-quick-start-direct-csv-input)

---

## 1. System Overview

The Survey Generator converts survey definitions from Veeva CRM exports into Salesforce **LSC OfflineMobile Survey Flow** metadata XML files (`.flow-meta.xml`), which are deployed to a Salesforce org via the SFDX CLI.

### What it produces

Each survey becomes one `{developer_name}.flow-meta.xml` file. On successful deployment with `status=Active`, Salesforce automatically creates a `Survey` sObject record — no DML is needed.

### Components

| File | Role |
|---|---|
| `veeva_to_lsc.py` | Transforms Veeva `SURVEY_DATA.xlsx` → intermediate LSC CSV |
| `generate_surveys.py` | Core engine: parses CSV/Veeva exports, builds survey data model, renders XML via CLI |
| `survey_pipeline.py` | Adapter layer for the Streamlit UI — wraps the core engine |
| `survey_app.py` | Streamlit web UI (upload → preview → generate → download/save) |
| `templates/survey_flow.xml.j2` | Jinja2 template for the Flow XML structure |

### Supported survey types on OfflineMobile

`ShortText`, `FreeText`, `Date`, `Number`, `Slider`, `RadioButton`, `Picklist`, `MultiselectPicklist`, `Rating`, `CSAT`, `StackRank` (falls back to Picklist), `Description` (falls back to read-only FreeText).

---

## 2. Repository Structure

```
survey_generator/
├── veeva_to_lsc.py          # Veeva XLSX → LSC CSV transformer
├── generate_surveys.py      # Core engine + CLI entry point
├── survey_pipeline.py       # UI adapter (parse / validate / build / render)
├── survey_app.py            # Streamlit web UI
├── launcher.py              # PyInstaller entry point
├── requirements.txt         # Python dependencies
├── survey_generator.spec    # PyInstaller build config
├── Dockerfile / .dockerignore
├── .gitignore
├── templates/
│   └── survey_flow.xml.j2   # Jinja2 Flow XML template
├── sample_data/
│   └── SURVEY_DATA.xlsx     # Veeva source export (not committed)
└── TECHNICAL_DOC.md         # This document
```

---

## 3. End-to-End Pipeline

### Path A — Veeva XLSX (primary production path)

```
SURVEY_DATA.xlsx
      │
      ▼
[veeva_to_lsc.py — transform()]
  Step 1: Build survey name → developer_name map (handle territory duplicates)
  Step 2: Build welcome text lookup from DC1__C
  Step 3: Map SURVEY_VOD__C name → developer_name on question rows
  Step 4: Sort questions by ORDER_VOD__C
  Step 5a: Build Q-index map (for CONDITION_VOD__C fallback resolution)
  Step 5b: Detect branching surveys; assign p_1 / p_ans_N pages; find router question
  Step 5: Emit one CSV row per question (split Picklists > 20 choices into two rows)
  Step 6: Print summary report
  Step 7: Write veeva_surveys_lsc.csv (optional)
      │
      ▼  (returns DataFrame)
[survey_pipeline.py — parse_uploaded()]
  Reads CSV rows → builds raw_surveys OrderedDict
      │
      ▼
[generate_surveys.py — _build_surveys()]
  - Resolve TYPE_MAP attributes per question type
  - Generate choice API names (MD5-prefixed)
  - Truncate fieldText if XML-encoded length > 960
  - Parse branch_rules JSON → multi-rule decision elements
  - Build page connector chain
  - Emit decisions elements
      │
      ▼
[Jinja2 template render]
  → {survey_developer_name}.flow-meta.xml per survey
      │
      ▼
[sf project deploy start]
  → Survey Flow activated in Salesforce org
  → Survey sObject record auto-created
```

### Path B — LSC Structured CSV (manual authoring)

```
surveys.csv  (one row per question, columns per §7)
      │
      ▼
[generate_surveys.py — parse_csv()]  OR  [survey_pipeline.py — parse_uploaded()]
      │
      ▼
[_build_surveys()] → [template render] → [deploy]
```

### Path C — Veeva CSV Format A/B (legacy path, via CLI only)

```
veeva_export.csv  (tab or comma, auto-detected)
      │
      ▼
[generate_surveys.py — parse_source()]
  - Auto-detect Format A (question definitions) or B (response records)
  - Format B: deduplicate by SURVEY_QUESTION_VOD__C
  - Infer question types from choice counts and weights
  - Resolve CONDITION_VOD__C into visibility_rule (Format A) or value-lookup (Format B)
      │
      ▼
[_build_surveys()] → [template render] → [deploy]
```

---

## 4. Input Formats

### 4a. Veeva SURVEY_DATA.xlsx (primary)

Two-tab Excel export from Veeva CRM. Detected by checking for both sheet names.

**Tab 1: SURVEY_VOD**

| Column | Used for |
|---|---|
| `ID` | Territory dedup suffix; non-ASCII name fallback |
| `NAME` | Survey display name (grouping key) |
| `DC1__C` | Welcome text (falls back to auto-generated string) |

**Tab 2: SURVEY_QUESTION_VOD**

| Column | Used for |
|---|---|
| `SURVEY_VOD__C` | Links question to survey (display name) |
| `NAME` | Question developer name (kept as-is, e.g. `SQ00034519`) |
| `TEXT_VOD__C` | Question text (prefix-stripped) |
| `ANSWER_CHOICE_VOD__C` | Choice list in `Label;weight;Label;weight` format |
| `ORDER_VOD__C` | Question order within survey |
| `REQUIRED_VOD__C` | `1` = required, `0` = optional |
| `SURVEY_DISCLAIMER__C` | `1` = render as Description (read-only) |
| `CONDITION_VOD__C` | Branching condition: `Q01="answer text"` |
| `ISDELETED` | `1` = skip this row entirely |

### 4b. Veeva CSV Format A (question definitions)

Single-file CSV export of `Survey_Question_vod__c` records. Auto-detected when headers do NOT include `SURVEY_TARGET_VOD__C` or `QUESTION_TEXT_VOD__C`.

Key columns: `SURVEY_VOD__C`, `TEXT_VOD__C`, `ANSWER_CHOICE_VOD__C`, `ORDER_VOD__C`, `REQUIRED_VOD__C`, `MIN_SCORE_VOD__C`, `MAX_SCORE_VOD__C`, `CONDITION_VOD__C`, `INACTIVE_CONDITION_VOD__C`, `SURVEY_NAME_VOD__C`, `SURVEY_DEVELOPER_NAME_VOD__C`.

### 4c. Veeva CSV Format B (response records)

Export of `Survey_Question_Response_vod__c`. Auto-detected when headers include `SURVEY_TARGET_VOD__C` or `QUESTION_TEXT_VOD__C`. Same question appears once per account response — deduplicated by `SURVEY_QUESTION_VOD__C`.

### 4d. LSC Structured CSV

One row per question. See §7 for full column reference. Supports multi-page surveys with manual `page_developer_name` / `page_order` and single-rule branching via `branch_on_answer` / `branch_to_page`.

---

## 5. Veeva XLSX Transformation Pipeline

`veeva_to_lsc.py → transform(xlsx_path, output_path)`

### Step 1 — Build survey name → developer name map

Reads the `SURVEY_VOD` tab. For each survey record:

1. `slugify(NAME)` → snake_case developer name (max 80 chars)
2. If slugify returns empty (all non-ASCII) → `survey_{last8_of_ID}`
3. If the name appears more than once (territory variants) → append `_{last6_of_ID}` to each variant's dev name

This produces two lookup dicts:
- `survey_dev_lookup[name]` → used for unique-name surveys
- `survey_dev_by_id[id]` → used for territory variants

**Why:** The `SURVEY_QUESTION_VOD` tab references surveys by display `NAME`, not `ID`. Territory variants (same name, different IDs) must get distinct developer names so their questions don't merge.

### Step 2 — Build welcome text lookup

For each survey, welcome text = `DC1__C` if non-empty, else `"Welcome to the {name} survey. Please answer all questions."`. Stored in `welcome_by_name` and `welcome_by_id`.

### Step 3 — Map question rows to survey developer names

Reads `SURVEY_QUESTION_VOD`. Maps `SURVEY_VOD__C` (display name) → developer name using the Step 1 lookup. Rows with `ISDELETED = "1"` are dropped.

### Step 4 — Sort questions

Within each survey, rows are sorted by `ORDER_VOD__C` (cast to int, nulls → 0).

### Step 5a — Build Q-index map

Veeva's `CONDITION_VOD__C` uses `Q00`, `Q01`, … where the index counts only choice-bearing questions (`RadioButton`, `Picklist`, `MultiselectPicklist`) in display order. `Description` and `FreeText` are NOT counted.

Builds `q_index_map[survey_dev][q_index] = question_NAME` as a fallback for condition resolution.

### Step 5b — Detect branching and assign pages

For each survey:

1. Collect all unique condition answer values from `CONDITION_VOD__C` in first-appearance order
2. If any conditions exist → find the **router question** using answer-matching strategy (see §12 item 14)
3. Build `answer_page_map[survey_dev] = {answer: "p_ans_N"}` (N = 0, 1, 2, …)
4. Build `router_branch_rules[(survey_dev, router_NAME)] = JSON([{answer, page}, …])`

### Step 5 — Emit output rows

For each question row:

1. Strip question text prefix (`QTN:`, `QTB:`, etc.)
2. Infer question type (see §12 item 3)
3. Parse `REQUIRED_VOD__C` → `"true"` / `"false"`
4. Determine page:
   - Has a condition + survey has branching → `p_ans_N`, `page_order = N+2`
   - Otherwise → `p_1`, `page_order = 1`
5. Set `branch_rules` JSON on the router question; empty on all others
6. If Picklist and choices > 20 → emit 2 rows (Part 1 / Part 2); MultiselectPicklist > 10 → truncate

### Step 6 — Summary report

Prints split notices, truncation warnings, question count, survey count, type breakdown, and survey list to stdout.

### Step 7 — Save CSV (optional)

If `output_path` is provided, writes the DataFrame to CSV. If called from `survey_pipeline.py` (UI path), `output_path=None` and the DataFrame is returned directly.

---

## 6. Field Mapping: Veeva → LSC CSV

### SURVEY_VOD tab → survey-level CSV columns

| Veeva field | LSC CSV column | Transformation |
|---|---|---|
| `NAME` | `survey_name` | Direct (display name kept as-is) |
| `NAME` (slugified) | `survey_developer_name` | `slugify()` → snake_case, max 80 chars; territory variants get `_{last6_ID}` suffix |
| `DC1__C` | `welcome_text` | Direct if non-empty; else `"Welcome to the {name} survey…"` |
| _(hardcoded)_ | `thankyou_label` | `"Survey Complete"` |
| _(hardcoded)_ | `thankyou_text` | `"Thank you for completing this survey."` |

### SURVEY_QUESTION_VOD tab → question-level CSV columns

| Veeva field | LSC CSV column | Transformation |
|---|---|---|
| `SURVEY_VOD__C` | _(grouping key)_ | Maps to `survey_developer_name` via Step 1 lookup |
| `NAME` | `question_developer_name` | Kept as-is (e.g. `SQ00034519`) |
| `TEXT_VOD__C` | `question_text` | `strip_question_prefix()` removes `QTN:` / `QTB:` / `QTP:` markers |
| `ORDER_VOD__C` | `question_order` | Cast to int; nulls → 0 |
| `REQUIRED_VOD__C` | `required` | `"1"` → `"true"`, else `"false"` |
| `ANSWER_CHOICE_VOD__C` | `choices` | `Label;weight;Label;weight` → pipe-separated labels. Weights → `branch_rules` scoring if any ≠ 0 |
| `SURVEY_DISCLAIMER__C` | `question_type` | `"1"` → `Description`; otherwise type inferred (see §12 item 3) |
| `CONDITION_VOD__C` | `branch_rules` (router) or page assignment | Router question gets `branch_rules` JSON; conditional questions get placed on `p_ans_N` |
| `ISDELETED` | _(filter)_ | Rows with `"1"` excluded entirely |
| _(derived)_ | `page_developer_name` | `"p_1"` (unconditional) or `"p_ans_N"` (conditional) |
| _(derived)_ | `page_order` | `1` (p_1) or `N+2` (p_ans_N) |
| _(derived)_ | `page_label` | `"Page 1"`, `"Page 2"`, etc. |
| _(hardcoded)_ | `slider_min` / `slider_max` | `""` (not used in XLSX path; Rating/CSAT use auto-generated choices) |
| _(hardcoded)_ | `branch_on_answer` / `branch_to_page` | Always `""` in XLSX path (branching via `branch_rules` instead) |
| _(hardcoded)_ | `visibility_rule` | Always `""` in XLSX path (OfflineMobile doesn't support visibilityRule) |

### Veeva choice format → LSC choices

```
Veeva:  "Internista/Geriatra;0;Cardiologo Tier 2;0;Centro di Riferimento;0"
                │
                ▼  parse_choices()
Labels:  ["Internista/Geriatra", "Cardiologo Tier 2", "Centro di Riferimento"]
Weights: ["0", "0", "0"]  → all equal → no scoring
                │
                ▼
LSC:  "Internista/Geriatra|Cardiologo Tier 2|Centro di Riferimento"
```

If any weight ≠ 0 (bitmask scoring):
```
Veeva:  "Choice A;1;Choice B;2;Choice C;4"
LSC choices: "Choice A|Choice B|Choice C"
LSC weights: "1|2|4"   ← stored in choices_weights, rendered as <score> in XML
Question type: MultiselectPicklist
```

---

## 7. LSC CSV Column Reference

One row per question. Multiple rows sharing the same `survey_developer_name` + `page_developer_name` belong to the same page.

| Column | Required | Description |
|---|---|---|
| `survey_name` | Yes | Display name of the survey |
| `survey_developer_name` | Yes | Salesforce API name for the Flow (snake_case, max 80 chars) |
| `welcome_text` | No | Text shown on the welcome screen |
| `thankyou_label` | No | Bold heading on thank-you page (default: `"Thank You"`) |
| `thankyou_text` | No | Body text on thank-you page |
| `page_label` | Yes | Display label of the page (e.g. `"Page 1"`) |
| `page_developer_name` | Yes | API name of the page (e.g. `"p_1"`, `"p_ans_0"`) |
| `page_order` | Yes | Integer; pages sorted ascending. `1` = first content page |
| `question_text` | Yes | Question text shown to the respondent |
| `question_developer_name` | Yes | API name of the question field (unique within survey) |
| `question_type` | Yes | One of: `ShortText`, `FreeText`, `Date`, `DateTime`, `Number`, `Slider`, `RadioButton`, `Picklist`, `MultiselectPicklist`, `Rating`, `CSAT`, `StackRank`, `Description` |
| `question_order` | Yes | Integer; questions on a page sorted ascending |
| `required` | No | `"true"` or `"false"` (default: `"false"`) |
| `choices` | Conditional | Pipe-separated choice labels. Required for `RadioButton`, `Picklist`, `MultiselectPicklist`, `StackRank`. Auto-generated for `Rating`/`CSAT` |
| `slider_min` | No | Minimum value for `Slider` / range start for `Rating`/`CSAT` (default: `"1"`) |
| `slider_max` | No | Maximum value for `Slider` / range end for `Rating`/`CSAT` (default: `"10"`) |
| `branch_on_answer` | No | Answer value that triggers a page skip (single-rule branching) |
| `branch_to_page` | No | `page_developer_name` to jump to when `branch_on_answer` matches |
| `branch_rules` | No | JSON array of `[{"answer": "…", "page": "…"}, …]` for multi-answer routing (Veeva path only; auto-generated) |
| `visibility_rule` | No | `"question_dev==answer_value"` for question-level display logic (CSV path, Online surveys only; not used for OfflineMobile) |

---

## 8. Build Pipeline — `_build_surveys()`

`generate_surveys.py → _build_surveys(surveys: OrderedDict) → list`

Takes the raw surveys dict (output of any parser) and produces a list of fully-resolved survey dicts ready for template rendering.

### 8a. Choice name prefix computation

```python
import hashlib
_full = s["survey_developer_name"]          # e.g. "adoption_ladder_d_onchaem1"
_h6   = hashlib.md5(_full.encode()).hexdigest()[:6]  # e.g. "f51876"
s_dev = slugify(_full, 10).strip("_") + "_" + _h6   # e.g. "adoption_l_f51876"
```

Used as the survey portion of every choice API name.

### 8b. Page sorting

Pages sorted by `page["order"]` ascending. Questions within each page sorted by `question_order` ascending.

### 8c. Question type resolution

Each `question_type` string looked up in `TYPE_MAP`:

| `question_type` | `data_type` | `field_type` | `extension_name` |
|---|---|---|---|
| `ShortText` | `String` | `ComponentInput` | `survey:runtimeShortText` |
| `FreeText` | `String` | `InputField` | _(none)_ |
| `Date` | `Date` | `InputField` | _(none)_ |
| `DateTime` | `Date` | `InputField` | _(none — falls back to Date)_ |
| `Number` | `Number` | `InputField` | _(none)_ |
| `Slider` | `Number` | `ComponentInput` | `survey:cmpInputRuntimeSlider` |
| `RadioButton` | `String` | `ComponentChoice` | `survey:runtimeRadioButton` |
| `Picklist` | `String` | `ComponentChoice` | `survey:runtimePicklist` |
| `MultiselectPicklist` | `String` | `MultiSelectCheckboxes` | _(none)_ |
| `Rating` | `Number` | `ComponentChoice` | `survey:runtimeRating` |
| `CSAT` | `Number` | `ComponentChoice` | `survey:runtimeRating` _(same as Rating)_ |
| `StackRank` | `String` | `ComponentChoice` | `survey:runtimePicklist` _(same as Picklist)_ |
| `Description` | `String` | `InputField` | _(none)_ |

`data_type = None` → `<dataType>` element omitted from XML (applies to `Description`).

### 8d. Choice generation

**Rating / CSAT:** Auto-generate numeric choices from `slider_min` to `slider_max`:
```
name:  c_{s_dev}_{q_slug}_{value}_{index}
text:  "1", "2", … "10"
dataType: Number
```

**All other choice types:** Parse `choices_pipe` (pipe-separated):
```
name:  c_{s_dev}_{q_slug}_{t_slug}_{index}
text:  choice label
score: weight if has_scores else None
```
`t_slug = slugify(choice_text, 14).strip("_") or f"opt{index}"`

### 8e. fieldText truncation

```python
_MAX_ENCODED = 960
while len(html.escape(q_text, quote=False)) > _MAX_ENCODED:
    q_text = q_text[:int(len(q_text) * 0.9)]
```

Iteratively shrinks by 10% until the XML-encoded text fits. A warning is printed to stderr for each truncation.

### 8f. branch_rules parsing and choice_api_name enrichment

If `q["branch_rules"]` is a non-empty JSON string, it is parsed into a list of `{answer, page}` dicts. This marks the question as a multi-rule router.

After parsing, each rule is enriched with `choice_api_name` — the API name of the choice element whose label text matches `answer`. This is resolved from the question's `choices` list built in the same loop. The template then emits `<elementReference>` (not `<stringValue>`) in the decision condition's `<rightValue>`, which is required for OfflineMobile runtime comparison to work.

### 8g. Terminal branch page collection

Before processing page connectors, all `p_ans_N` destinations are collected into `terminal_branch_pages`. These pages are chained sequentially so every branch page is reachable via a `<connector>` graph walk — see §8h §3 and §12.23u for why this is required.

### 8h. Page connector and decision building

For each page, in `page_order` sequence:

1. **Multi-rule branching** (question has `branch_rules` list):
   - Create `decisions` element with one `<rules>` per answer
   - `defaultConnector` = page after the last `p_ans_N`; if all branch pages are terminal (no page follows), falls back to `all_branch_pages[0]`. A `defaultConnector` is **always** emitted — omitting it causes the runtime to end the flow immediately when no rule matches.
   - Page connector → decision element name `d_{page_dev}_branch`

2. **Single-rule branching** (question has `branch_on_answer` + `branch_to_page`):
   - Create `decisions` element with one `<rules>`
   - `defaultConnector` = next page, skipping the branch target if it would double-connect
   - Page connector → decision element name

3. **Terminal answer page** (in `terminal_branch_pages`):
   - Chained to the next sibling branch page in page-list order (e.g. `p_ans_0 → p_ans_1 → p_ans_2`)
   - The **last** branch page gets `connector = None` (terminal, advances to Thank You on Finish)
   - **Why:** The Survey Builder "Select page" dropdown only resolves pages reachable via `<connector>` / `<defaultConnector>` links. Pages reachable only through decision rule connectors appear blank in the builder UI even if the XML routing is correct. See §12.23u.

4. **Normal page** (no branching):
   - `connector = next page` in order, or `None` for the last page

### 8i. Outputs added to each survey dict

| Key | Value |
|---|---|
| `pages` | List of page dicts, sorted by order, questions resolved |
| `decisions` | List of decision element dicts |
| `all_questions` | Flat list of all questions across all pages (used for `<choices>` rendering) |
| `page_options_map` | JSON string: `{"p_1": {"isMovable": true, "isDeletable": true}, …}` |

---

## 9. Flow XML Template

`templates/survey_flow.xml.j2` — Jinja2 template rendered once per survey.

### Template variables

| Variable | Type | Source |
|---|---|---|
| `survey_name` | str | Survey display name |
| `survey_developer_name` | str | Flow API name |
| `welcome_text` | str | Welcome screen body |
| `thankyou_label` | str | Thank-you heading |
| `thankyou_text` | str | Thank-you body |
| `pages` | list | Resolved page dicts (sorted by order) |
| `decisions` | list | Decision element dicts |
| `all_questions` | list | All questions across all pages |
| `page_options_map` | str | JSON for `pageOptionsMap` metadata |

### XML element order (required by Salesforce metadata API)

```
<Flow>
  <assignments>             ← pageNamesInOrder_Assignment
  <choices>                 ← ALL choice elements (must precede all <screens>)
  <decisions>               ← branching decisions (must precede all <screens>)
  <interviewLabel>
  <label>
  <processMetadataValues>   ← survey settings (advanceThankYouPageEnabled, surveyType, etc.)
  <processType>Survey</processType>
  <screens>                 ← content pages (p_1, p_ans_0…) in order
  <screens>                 ← welcome_page LAST among all screens
  <startElementReference>pageNamesInOrder_Assignment</startElementReference>
  <status>Active</status>
  <textTemplates>           ← thankYouLabel, thankYouDescription, welcome_question_lref_tt
  <variables>               ← guestUserLang, invitationId, pageNamesInOrder, previewMode, etc.
</Flow>
```

### Key rendering notes

- `fieldText` is double-encoded: question text XML-escaped, then wrapped in `&lt;p&gt;&lt;strong&gt;…&lt;/strong&gt;&lt;/p&gt;`
- `<choices>` use `<dataType>Number</dataType>` for Rating/CSAT, `<dataType>String</dataType>` for all others
- `<scale>0</scale>` emitted on `Slider`, `Number`, `Rating`, `CSAT` fields
- `Description` type: `<dataType>` element omitted entirely
- `Slider` type: three extra `<processMetadataValues>` (max, min, scale=1) inside `<fields>`
- Pages with `connector=None` have no `<connector>` element → flow falls through to thank-you
- Multi-rule decisions render N `<rules>` blocks; single-rule renders 1 `<rules>` block
- Decision `<conditions>` must include 4 `<processMetadataValues>` (`inputDataType`, `leftHandSideType`, `operatorDataType`, `rightHandSideType`) and use `<elementReference>` (choice API name) in `<rightValue>` — not `<stringValue>`. Using `<stringValue>` causes rules to silently never match on OfflineMobile.
- Every `<decisions>` element must have a `<defaultConnector>` — see §12.23k-new

---

## 10. Streamlit UI — `survey_app.py`

Four-step UI running on `streamlit run survey_app.py` (default: `http://localhost:8501`).

### Step 1 — Upload

Accepts `.csv`, `.xlsx`, `.xls`. On upload:
- If XLSX with `SURVEY_VOD` + `SURVEY_QUESTION_VOD` tabs → detected as Veeva export → auto-transforms via `veeva_to_lsc.transform()`
- If plain XLSX → read directly with `pd.read_excel()`
- If CSV → decoded as UTF-8-BOM

File identity tracked by `(name, size)` to avoid re-parsing on every Streamlit rerun.

### Step 2 — Raw Data Preview

Shows the uploaded DataFrame in an expander. For large files (>200 rows), limits display to 200 unless a "show all" checkbox is enabled.

### Step 3 — Survey Preview

- **Metric tiles:** survey count, total questions, error count, warning count
- **Error/warning alerts:** from `validate()` in `survey_pipeline.py`
- **Summary table:** one row per survey — name, API name, page count, question count, status
- **Per-survey expanders:** welcome/thankyou text, page-by-page question tables including type, required flag, choices, branch settings

Validation checks:
- Missing required CSV columns
- Unknown `question_type` values
- Duplicate `question_developer_name` within a page
- `branch_to_page` references a non-existent page
- Missing choices on choice-type questions (warning)
- Choices exceeding per-type caps (error)
- Choice text > 200 chars or containing `;` (error)
- Missing `welcome_text` (warning)

### Step 4 — Generate & Download

**Generate button** → calls `build(raw)` → stores result in `st.session_state.built_surveys`

**Download as ZIP** → `render_to_zip(built)` → in-memory ZIP of all `.flow-meta.xml` files → `st.download_button`

**Save to Local Folder** → `render_to_folder(built, path)` → writes files directly to the specified filesystem path (useful when the app runs locally and the target is a Salesforce project directory)

---

## 11. Deployment to Salesforce

### Prerequisites

- Salesforce CLI (`sf`) installed and authenticated to the target org
- Project structure with `force-app/main/default/flows/` directory
- User has `Deploy Metadata` permission (System Administrator or equivalent)

### Typical deploy command

```bash
cd ~/projects/lsdev1
sf project deploy start --source-dir force-app/main/default/flows
```

### Deploy behaviour

- **Transactional:** if any single flow in the batch fails validation, the entire deploy rolls back. No partial success.
- **Status must be Active:** flows with `<status>Draft</status>` deploy but do not create Survey records.
- **Survey record auto-creation:** `Survey` sObject records are created automatically by the platform on successful deploy. No manual insert is needed or possible (`Survey` is not directly insertable via API).
- **Survey not visible immediately:** the Survey App in Salesforce may take a moment to index newly created Survey records.

### Problem flows

Keep flows that persistently fail in `flows_excluded/` and deploy them separately:
```bash
cp force-app/main/default/flows/problem_survey.flow-meta.xml flows_excluded/
```

### Version behaviour

Re-deploying an existing flow creates a new version and activates it. Previous versions are deactivated.


## 12. Special Logic Reference

All non-obvious decisions made during Veeva → LSC survey transformation and flow generation.

---

### 12.1. Picklist Split (>20 choices)

**Where:** `veeva_to_lsc.py` → Step 5  
**Trigger:** A `Picklist` question has more than 20 answer choices  
**Behaviour:** Split into two consecutive questions:
- Question text gets ` (Part 1 of 2)` / ` (Part 2 of 2)` appended
- Developer name of Part 2 gets `_b` suffix (e.g. `SQ00007511_b`)
- First 20 choices → Part 1; remaining choices → Part 2

**Why:** Salesforce Survey Flow caps Picklist at 20 choices per question.

---

### 12.2. MultiselectPicklist Cap (>10 choices)

**Where:** `veeva_to_lsc.py` → Step 5  
**Trigger:** A `MultiselectPicklist` question has more than 10 choices  
**Behaviour:** Truncated to first 10 choices. No split (multi-select split would be confusing to respondents).  
**Warning printed:** `⚠️  {question} ({type}): N choices → truncated to 10`

**Why:** Salesforce Survey Flow caps MultiselectPicklist at 10 choices.

---

### 12.3. Question Type Inference from Veeva

**Where:** `veeva_to_lsc.py` → `infer_question_type()`  
**Priority order (first match wins):**

| Condition | Mapped type |
|---|---|
| `SURVEY_DISCLAIMER__C = 1` OR text starts with "disclaimer" | `Description` |
| No choices (`ANSWER_CHOICE_VOD__C` empty) | `FreeText` |
| Any choice weight ≠ 0 (bitmask scoring) | `MultiselectPicklist` |
| Exactly 2 choices, all weights = 0 | `RadioButton` |
| 3+ choices, all weights = 0 | `Picklist` |

---

### 12.4. Bitmask / Choice Weight Handling

**Where:** `veeva_to_lsc.py` → `parse_choices()` / `generate_surveys.py` → `_build_surveys()`  
**Veeva format:** `ChoiceA;1;ChoiceB;0;ChoiceC;4` (label;weight pairs)  
**Logic:**
- If any weight ≠ 0 → question becomes `MultiselectPicklist`, weights become `<score>` elements in XML
- If all weights are equal → weights dropped entirely (no `<score>` element)

---

### 12.5. Question Text Prefix Stripping

**Where:** `veeva_to_lsc.py` → `strip_question_prefix()`  
**Strips these Veeva authoring artifacts from question text:**
- `QTN:`, `QTB:`, `QTP:`, `QTB-1)`, `QTP-2.` and similar prefixes
- `(For the representative to answer)` preambles
- Trailing/leading whitespace and newlines (normalised to single space)

---

### 12.6. Duplicate Survey Names (Territory Variants)

**Where:** `veeva_to_lsc.py` → Step 1  
**Trigger:** Two or more surveys in `SURVEY_VOD` share the same `NAME` (same survey deployed to different territories)  
**Behaviour:** Each variant gets the last 6 characters of its Salesforce record ID appended to the developer name  
Example: `adoption_ladder` → `adoption_ladder_4traay` and `adoption_ladder_ybeaao`

**Why:** Veeva's `SURVEY_QUESTION_VOD` tab references surveys by display name, not ID. Without this, territory variants share one developer name and their questions merge.

---

### 12.7. Non-ASCII Survey Names

**Where:** `veeva_to_lsc.py` → Step 1  
**Trigger:** Survey name contains only non-ASCII characters (e.g. Cyrillic) — `slugify()` returns an empty string  
**Behaviour:** Developer name falls back to `survey_{last8ofID}` (e.g. `survey_ab30022f`)

---

### 12.8. Choice Name Uniqueness (MD5 Hash Prefix)

**Where:** `generate_surveys.py` → `_build_surveys()`  
**Format:** `c_{s_dev}_{q_slug}_{t_slug}_{index}`  
Where `s_dev` = `{10-char slug of survey dev name}_{6-char MD5 of full dev name}`

**Why:** Salesforce requires all `<choices>` names to be globally unique across the org. Simple slug truncation caused collisions between territory variants (e.g. `adoption_ladder_d_onchaem1` and `adoption_ladder_f_onchaem1` both truncate to `adoption_ladde`). The MD5 hash of the full developer name guarantees uniqueness even when names share a truncated prefix.

---

### 12.9. Non-ASCII Choice Text (Empty Slug Fallback)

**Where:** `generate_surveys.py` → `_build_surveys()`  
**Trigger:** Choice text contains only non-ASCII characters → `slugify()` returns empty string  
**Behaviour:** Slug falls back to `opt{index}` (e.g. `opt0`, `opt1`)  
**Also applied to:** Survey slug prefix — falls back to `q{index}` if question dev name slugifies to empty

**Why:** Salesforce API names must be alphanumeric + underscore. Empty slugs produce double-underscore names (`c_survey__0`) which are invalid.

---

### 12.10. Trailing Underscore Prevention

**Where:** `generate_surveys.py` → everywhere slugs are constructed  
**Behaviour:** `.strip("_")` applied after every slug truncation  
**Why:** Salesforce API names cannot end with an underscore. Truncating mid-word (e.g. `gp_survey_` → last char is `_`) would produce invalid names.

---

### 12.11. Survey Developer Name Starts with Digit

**Where:** `veeva_to_lsc.py` → `slugify()` / `generate_surveys.py` → `slugify()`  
**Trigger:** Name begins with a number after non-ASCII stripping (e.g. `2026 COVID Survey` → `2026_covid_survey`)  
**Behaviour:** Prepend `s_` → `s_2026_covid_survey`

**Why:** Salesforce API names must start with a letter.

---

### 12.12. fieldText XML-Encoding-Aware Truncation

**Where:** `generate_surveys.py` → `_build_surveys()`  
**Trigger:** Question text, after XML-encoding, exceeds 960 characters  
**Behaviour:** Iteratively shrink to 90% of current length until encoded length ≤ 960  
**Warning printed:** `[TRUNCATE] '{q_dev}' → {N} raw chars`

**Why:** Salesforce caps the `fieldText` "User Input Prompt" at ~1000 XML-encoded characters. The `<p><strong>…</strong></p>` wrapper adds ~40 encoded chars, leaving ~960 for the text. The limit is on the *encoded* value, not raw characters — a single `&` counts as 5 (`&amp;`).

---

### 12.13. Multi-Page Branching from CONDITION_VOD__C

**Where:** `veeva_to_lsc.py` → Step 5b, Step 5 / `generate_surveys.py` → `_build_surveys()`  
**Trigger:** Any question in a survey has a non-empty `CONDITION_VOD__C` value  
**Behaviour:**
1. Collect all unique condition answer values across the survey (in first-appearance order)
2. Assign each unique answer its own page: `p_ans_0`, `p_ans_1`, …
3. Questions **without** a condition stay on `p_1` (always shown)
4. Questions **with** a condition go to the page for their answer (`p_ans_N`)
5. The router question (the one whose choices are the condition answers) stays on `p_1` and gets a `branch_rules` JSON list: `[{answer, page}, ...]`
6. `_build_surveys()` turns `branch_rules` into one `<decisions>` element with one `<rules>` entry per answer, routing to the correct page
7. Each `p_ans_N` page has **no connector** — it terminates the survey (respondents only see their segment's questions)

**Why:** Salesforce `OfflineMobile` surveys do not support question-level `visibilityRule` display logic. Only page-level `<decisions>` branching is allowed.

---

### 12.14. Router Question Detection — SOURCE_ID_VOD__C Authoritative Lookup

**Where:** `veeva_to_lsc.py` → Step 5a / 5b  
**Problem:** Veeva's `CONDITION_VOD__C` uses `Q01="answer"` where `Q01` is the label stored in `SOURCE_ID_VOD__C` on the router question — not a 0-based count of choice-bearing questions.  
**Strategy:** Build a per-survey `source_id_map`: `{q_label → question_NAME}` directly from `SOURCE_ID_VOD__C`. Conditions are then resolved by exact label match (e.g. `Q01` → `SQ00034519`). A warning is printed if no `SOURCE_ID_VOD__C` value matches the label in a condition.

**Multiple routers:** A survey may have more than one independent routing question (e.g. Q00 and Q01 each branching to different page sets). Each router gets its own `<decisions>` element. `router_rules_per_survey[survey_dev]` is keyed by `router_NAME` to support this.

---

### 12.15. Type Fallbacks (Unsupported LSC Types)

**Where:** `generate_surveys.py` → `TYPE_MAP`

| Veeva / input type | Falls back to | Reason |
|---|---|---|
| `DateTime` | `Date` field type | LSC Mobile does not support DateTime input |
| `CSAT` | `survey:runtimeRating` extension | Same platform component as Rating |
| `StackRank` | `survey:runtimePicklist` extension | No native StackRank in OfflineMobile |
| `Description` | `InputField` (no extension) | `DisplayText` unsupported in OfflineMobile; rendered as a read-only FreeText field |

---

### 12.16. Veeva Format Auto-Detection (Format A vs B)

**Where:** `generate_surveys.py` → `_detect_veeva_format()`  
**Format B** (response records export) detected when headers contain `SURVEY_TARGET_VOD__C` or `QUESTION_TEXT_VOD__C`  
**Format A** (question definitions export) assumed otherwise  

**Delimiter** also auto-detected: tab-separated if the first line contains a tab, otherwise comma.

---

### 12.17. Format B Deduplication

**Where:** `generate_surveys.py` → `parse_source()`  
**Trigger:** Using Veeva Format B (response records) — the same question appears once per account response  
**Behaviour:** `SURVEY_QUESTION_VOD__C` used as dedup key; first occurrence kept, subsequent rows for the same question skipped

---

### 12.18. Welcome Text Source

**Where:** `veeva_to_lsc.py` → Step 1  
**Primary source:** `DC1__C` field on the `SURVEY_VOD` tab  
**Fallback:** `"Welcome to the {survey_name} survey. Please answer all questions."`

---

### 12.19. Single-Rule Branching (CSV-authored surveys)

**Where:** `generate_surveys.py` → `_build_surveys()`  
**Trigger:** A question in a CSV-authored survey has `branch_on_answer` and `branch_to_page` columns set  
**Behaviour:** One `<decisions>` element with a single `<rules>` entry. The `defaultConnector` skips to the page *after* the branch target (so the branched page is not double-visited).

This is distinct from multi-rule branching used in the Veeva path.

---

### 12.20. Rating / CSAT Choice Auto-Generation

**Where:** `generate_surveys.py` → `_build_surveys()`  
**Trigger:** Question type is `Rating` or `CSAT`  
**Behaviour:** Numeric choices are generated automatically from `slider_min` to `slider_max` (inclusive). No choices need to be supplied in the CSV.  
Default range: 1–5 for Rating, 1–10 for CSAT (if not overridden).

---

### 12.21. Page Ordering and Distribution

#### 12.21a. Veeva path — no-branching surveys
All questions land on a single page `p_1` with `page_order = 1`.  
The Veeva export has no page concept; pages are only introduced by branching logic.

#### 12.21b. Veeva path — branching surveys
Pages are assigned during Step 5b of `veeva_to_lsc.py`:

| Page | `page_developer_name` | `page_order` | Contains |
|---|---|---|---|
| Always-shown | `p_1` | 1 | All unconditional questions + the router question |
| Answer group 0 | `p_ans_0` | 2 | Questions conditioned on 1st unique answer |
| Answer group 1 | `p_ans_1` | 3 | Questions conditioned on 2nd unique answer |
| … | … | … | … |
| Answer group N | `p_ans_N` | N+2 | Questions conditioned on (N+1)th unique answer |

Answer groups are ordered by **first appearance** of their answer value in the sorted question list (sorted by `ORDER_VOD__C`).

#### 12.21c. CSV path — multi-page surveys
`page_developer_name` and `page_order` are set directly in the CSV by the survey author.  
`_build_surveys()` sorts pages by `page_order` ascending before generating the flow.

#### 12.21d. Flow page sequence in the XML
The Salesforce runtime determines page order from the `pageNamesInOrder` list variable (populated by the `pageNamesInOrder_Assignment` element). The sequence is always:

```
welcome_page → p_1 → [p_ans_0 … p_ans_N] → thank_you_page
```

`welcome_page` and `thank_you_page` are implicit — they are not authored pages and are always prepended / appended. Content pages appear in `page_order` sequence between them.

#### 12.21e. Page connector chain
Each content page has a `<connector>` pointing to the next element:

| Page type | Connector target |
|---|---|
| Normal page (no branching) | Next page by order, or `None` (falls through to thank_you) |
| Router page (has `branch_rules`) | The decision element `d_{page_dev}_branch` |
| Terminal answer page (`p_ans_N`) | `None` — no connector; survey ends after this page |

The connector for the **last** normal page is `None` (omitted from XML), which causes the flow to end at thank_you.

---

### 12.22. API Name Rules and Enforcement

Salesforce API names must satisfy: start with a letter, contain only `[A-Za-z0-9_]`, no consecutive underscores (`__`), no trailing underscore, max 80 characters.

#### 12.22a. Survey developer name
**Source:** `SURVEY_VOD.NAME` → `slugify()` in `veeva_to_lsc.py`  
**`slugify()` steps:**
1. Lowercase and strip whitespace
2. Remove all characters except `[a-z0-9\s_]`
3. Collapse runs of whitespace to `_`
4. Collapse consecutive `_` to single `_`
5. Strip leading/trailing `_`
6. Truncate to 80 characters
7. If result starts with a digit → prepend `s_`
8. If result is empty (all non-ASCII) → `survey_{last8ofRecordID}`

**Territory duplicate suffix:** Last 6 chars of Salesforce record ID appended with `_` (e.g. `adoption_ladder_4traay`). The suffix comes from the record ID so it is alphanumeric-safe.

#### 12.22b. Question developer name
**Veeva path:** Kept as-is from Veeva `NAME` field (e.g. `SQ00034519`). These are already valid Salesforce API names.  
**CSV path / Format A:** `slugify(question_text, max_len=40)` — same rules as 12.22a but capped at 40 chars.  
**Dedup within page (CSV/Format A):** If two questions produce the same slug, the second and subsequent ones get `_2`, `_3`, … appended.

#### 12.22c. Page developer name
**No-branch surveys:** Always `p_1`  
**Branching surveys:** `p_1` (unconditional page) and `p_ans_0`, `p_ans_1`, … (answer pages)  
**CSV path:** Set directly by author in the `page_developer_name` column  
**Validation:** The `validate()` function in `survey_pipeline.py` checks that any `branch_to_page` value references an existing page developer name.

#### 12.22d. Choice API names
**Format:** `c_{s_dev}_{q_slug}_{t_slug}_{index}`

| Part | Source | Max length | Rule |
|---|---|---|---|
| `c_` | Fixed prefix | — | Ensures name starts with a letter |
| `s_dev` | `slugify(survey_dev, 10)` + `_` + MD5[:6] | 17 chars | 10-char slug + `_` + 6-char hex hash |
| `q_slug` | `slugify(question_dev, 14)` | 14 chars | Trailing `_` stripped; empty → `q` or `q{index}` |
| `t_slug` | `slugify(choice_text, 14)` | 14 chars | Trailing `_` stripped; empty (non-ASCII text) → `opt{index}` |
| `{index}` | 0-based position in choice list | — | Guarantees uniqueness within question |

**Total max length:** `2 + 17 + 1 + 14 + 1 + 14 + 1 + N_digits` ≈ 53 chars (well under the 80-char limit).

**Why MD5 in `s_dev`:** Truncating to 10 chars loses information — territory variants like `adoption_ladder_d_onchaem1` and `adoption_ladder_f_onchaem1` both truncate to `adoption_la`. The MD5 hash of the **full** developer name produces `f51876` vs `f1aa1a`, making them distinct.

#### 12.22e. Decision element names
**Format:** `d_{page_developer_name}_branch`  
**Rule name:** `d_{page_developer_name}_branch_rule` (single-rule) or `d_{page_developer_name}_branch_rule_{index}` (multi-rule)

#### 12.22f. Reserved / fixed element names
These names are hardcoded and must not be reused as page or question developer names:

| Name | Element |
|---|---|
| `welcome_page` | Welcome screen |
| `thank_you_page` | Thank-you screen |
| `welcome_question` | Welcome screen field |
| `pageNamesInOrder_Assignment` | Page order assignment element |
| `pageNamesInOrder` | String collection variable |
| `invitationId` | Input variable |
| `guestUserLang` | Input variable |
| `previewMode` | Boolean variable |
| `thankYouLabel` / `thankYouDescription` | Output variables |
| `thankYouLabelTextTemplate` / `thankYouDescriptionTextTemplate` / `welcome_question_lref_tt` | Text template elements |

---

### 12.23. LSC Flow XML Structure — Platform-Specific Rules

These are constraints and behaviours enforced by the Salesforce Survey Flow platform for `OfflineMobile` surveys. Violating any of these causes a deploy error.

#### 12.23a. processType and surveyType
```xml
<processType>Survey</processType>
<processMetadataValues>
    <name>surveyType</name>
    <value><stringValue>OfflineMobile</stringValue></value>
</processMetadataValues>
```
Both must be present. `OfflineMobile` is the only type used for LSC mobile surveys. Using `Online` or omitting `surveyType` produces a different (incompatible) survey experience.

#### 12.23b. isSimpleSurvey must be false
```xml
<processMetadataValues>
    <name>isSimpleSurvey</name>
    <value><booleanValue>false</booleanValue></value>
</processMetadataValues>
```
`isSimpleSurvey=true` restricts the survey to a subset of question types and disables branching. All multi-question, multi-type, or branching surveys must use `false`.

#### 12.23c. XML element ordering in the flow
Salesforce's metadata API requires a strict element ordering within `<Flow>`. The generator follows this order:
1. `<assignments>` — the `pageNamesInOrder_Assignment` element
2. `<choices>` — **all** choice elements from all questions, before any `<screens>`
3. `<decisions>` — branching decisions, before any `<screens>`
4. `<interviewLabel>` and `<label>`
5. `<processMetadataValues>` — all survey settings
6. `<processType>`
7. `<screens>` — content pages (p_1, p_ans_0 …), then welcome_page last
8. `<startElementReference>`
9. `<status>`
10. `<textTemplates>`
11. `<variables>`

**Critical:** `<choices>` must precede all `<screens>`. If any choice element appears after a screen, the deploy fails with a schema validation error.

#### 12.23d. Welcome page position in XML
The `welcome_page` screen is written **last** among all `<screens>` elements, even though it is the first page the user sees. This matches the pattern observed in working org surveys and is required — placing `welcome_page` first in the XML causes the platform to behave incorrectly.

The welcome page connector points to `pages[0].developer_name` (the first content page, `p_1`).

#### 12.23e. startElementReference points to the assignment, not the welcome page
```xml
<startElementReference>pageNamesInOrder_Assignment</startElementReference>
```
The flow starts by running the assignment (which populates `pageNamesInOrder`), which then connects to `welcome_page`. Setting `startElementReference` directly to `welcome_page` would bypass page-order population and break the survey's progress indicator.

#### 12.23f. pageNamesInOrder — required for progress bar
The `pageNamesInOrder` string collection variable must be populated with page developer names in order: `welcome_page`, then all content pages in sequence, then `thank_you_page`. This drives the progress bar displayed to the user during the survey. It is an output variable so the runtime can read it.

#### 12.23g. fieldText must be HTML-encoded rich text
```xml
<fieldText>&lt;p&gt;&lt;strong&gt;Question text here&lt;/strong&gt;&lt;/p&gt;</fieldText>
```
The question text is wrapped in `<p><strong>…</strong></p>` tags. The entire `fieldText` value is itself XML-encoded (angle brackets become `&lt;`/`&gt;`). This is how LSC renders question text in bold on the mobile survey screen.

#### 12.23h. No visibilityRule on OfflineMobile surveys
The `<visibilityRule>` element (question-level display logic) is **not supported** for `OfflineMobile` + `isSimpleSurvey=false` surveys. Deploying any such survey with a `visibilityRule` on a question produces:

> *"You can't add display logic to the questions in a life sciences commercial survey. Remove the display logic."*

This is why branching is implemented via page-level `<decisions>` instead. The template still has a `visibilityRule` block (used only for `Online` or `isSimpleSurvey=true` surveys via the CSV path).

#### 12.23i. Scale element for numeric question types
```xml
<scale>0</scale>
```
Required on `Slider`, `Number`, `Rating`, and `CSAT` question fields. Omitting it causes a deploy validation error for those types.

#### 12.23j. Decision conditions require processMetadataValues and elementReference

Each `<conditions>` block inside a `<decisions>` element **must** include four `<processMetadataValues>` entries describing the data type context, and the `<rightValue>` must use `<elementReference>` (pointing to the choice element's API name) — **not** `<stringValue>` with the label text.

```xml
<conditions>
    <processMetadataValues>
        <name>inputDataType</name>
        <value><stringValue>String</stringValue></value>
    </processMetadataValues>
    <processMetadataValues>
        <name>leftHandSideType</name>
        <value><stringValue>Picklist</stringValue></value>
    </processMetadataValues>
    <processMetadataValues>
        <name>operatorDataType</name>
        <value><stringValue>String</stringValue></value>
    </processMetadataValues>
    <processMetadataValues>
        <name>rightHandSideType</name>
        <value><stringValue>String</stringValue></value>
    </processMetadataValues>
    <leftValueReference>SQ00033840</leftValueReference>
    <operator>EqualTo</operator>
    <rightValue>
        <elementReference>c_ita_vaccin_8a1e61_sq00033840_l_interlocutor_0</elementReference>
    </rightValue>
</conditions>
```

**Why `elementReference` not `stringValue`:** The OfflineMobile runtime resolves picklist comparisons through the choice element. A raw `<stringValue>` containing the label text never matches at runtime — the decision rule is silently skipped and the flow falls through to `defaultConnector`.

**Impact:** Missing these entries causes every branching rule to fail silently. The generator enriches each `branch_rules` entry with `choice_api_name` in `_build_surveys()`, and the template emits `<elementReference>` when that field is present.

#### 12.23k. Decision elements must always have a defaultConnector

Every `<decisions>` element **must** have a `<defaultConnector>` with a valid `<targetReference>`. If no rule matches (e.g. during initial page load or an unexpected value), the runtime uses `defaultConnector`. Without it, the flow terminates immediately — the user sees welcome → p_1 → thank you with no branch pages.

```xml
<defaultConnector>
    <targetReference>p_ans_0</targetReference>
</defaultConnector>
<defaultConnectorLabel>Other</defaultConnectorLabel>
```

**Generator behaviour:** When all branch pages are terminal (no further pages after them — i.e. `last_idx + 1` overflows), `default_next` falls back to `all_branch_pages[0]` (the first branch page). This ensures the element is always emitted.

#### 12.23l. Choice dataType differs by question type
- **Rating / CSAT questions:** choice `<dataType>Number</dataType>` and `<value><numberValue>…</numberValue></value>`
- **All other choice types:** choice `<dataType>String</dataType>` and `<value><stringValue>…</stringValue></value>`

Using the wrong dataType for Rating choices causes incorrect scoring.

#### 12.23m. Description type has no dataType element
For `Description` questions (rendered as read-only text), the `<dataType>` element is **omitted** entirely from the `<fields>` block. All other question types include it.

#### 12.23n. Slider requires min/max processMetadataValues
For `Slider` type questions, three extra `<processMetadataValues>` must appear inside the `<fields>` block:
```xml
<processMetadataValues><name>max</name><value><stringValue>10</stringValue></value></processMetadataValues>
<processMetadataValues><name>min</name><value><stringValue>1</stringValue></value></processMetadataValues>
<processMetadataValues><name>scale</name><value><stringValue>1</stringValue></value></processMetadataValues>
```
These are in addition to the `<scale>0</scale>` element on the field itself.

#### 12.23o. allowPause differs between welcome page and content pages
- **Content pages:** `<allowPause>true</allowPause>`
- **Welcome page:** `<allowPause>false</allowPause>`

Pausing is not meaningful before the survey has started.

#### 12.23p. styleProperties on every question field
Every `<fields>` element must include:
```xml
<styleProperties>
    <verticalAlignment><stringValue>top</stringValue></verticalAlignment>
    <width><stringValue>12</stringValue></width>
</styleProperties>
```
`width=12` means full-width (out of a 12-column grid). Omitting this block causes rendering issues on the mobile tablet.

#### 12.23q. pageOptionsMap — required survey metadata
```xml
<processMetadataValues>
    <name>pageOptionsMap</name>
    <value><stringValue>{"p_1":{"isMovable":true,"isDeletable":true},...}</stringValue></value>
</processMetadataValues>
```
A JSON object mapping every content page developer name to `{"isMovable": true, "isDeletable": true}`. Must include all content pages. The welcome and thank-you pages are not included. Omitting any page from this map causes a deploy error.

#### 12.23r. Survey record auto-creation
A `Survey` sObject record is automatically created by the platform when a Survey Flow deploys successfully with `status=Active`. No manual DML or Bulk API insert is needed or possible (`Survey` is not directly insertable via API).

#### 12.23s. Deploy is transactional
If any one flow in a batch deploy fails, the entire deploy rolls back. All 66+ flows are deployed together, so a single broken flow blocks all others. Keep problem flows in a separate excluded folder (e.g. `flows_excluded/`) and deploy them separately once fixed.

#### 12.23u. Terminal branch pages must be chained via connectors for Survey Builder visibility

**Problem:** The Survey Builder "Select page" dropdown only shows pages reachable via `<connector>` / `<defaultConnector>` elements. Pages reachable only through decision rule connectors are invisible — the dropdown shows blank for those rules even though the XML routing is correct.

**Symptom:** In a 3-way branch, the "Select page" dropdown shows the first branch destination (e.g. "Page 2") populated (via `defaultConnector`) but blank entries for the other two rules.

**Fix:** Chain terminal branch pages sequentially in page-list order so every page is in the connector graph:
```
p_ans_0 → connector → p_ans_1 → connector → p_ans_2 (no connector, terminal)
```

The decision routing is unaffected — users land on the correct branch page via the decision rule, then use Finish to end the survey.

**Note:** `thank_you_page` is a virtual construct — it cannot be used as a `<targetReference>`. Attempting this causes `Invalid element reference thank_you_page not found for target` at deploy time.

---

## 13. Quick Start: Direct CSV Input

You do **not** need a Veeva export to use this tool. You can author surveys directly as a plain single-tab CSV file and upload it into the Streamlit UI (or pass it via CLI) — no Veeva dependency at all.

### 13a. When to use direct CSV

- Creating new surveys from scratch (not migrating from Veeva)
- Editing or adding questions to an existing Salesforce survey
- Building a quick one-off survey without going through Veeva CRM

### 13b. File format

- **File type:** `.csv` (UTF-8 or UTF-8-BOM), **single tab/sheet**
- **Row model:** one row per question. All questions from all surveys can be in the same file.
- **Header row required** (exact column names as shown below)

A sample file with all column headers and example rows is provided at:
```
sample_data/lsc_survey_template.csv
```

### 13c. Required columns and values

| Column | Required? | Allowed values / format |
|---|---|---|
| `survey_name` | Yes | Free text display name. Surveys grouped by this value. |
| `survey_developer_name` | Yes | Salesforce API name: `[a-z][a-z0-9_]{0,79}`, no double-underscore, no trailing `_`. Use snake_case. |
| `welcome_text` | No | Text shown on the welcome screen. If blank, defaults to `"Welcome to the {survey_name} survey."` |
| `thankyou_label` | No | Bold heading on the thank-you page. Default: `"Thank You"` |
| `thankyou_text` | No | Body text on the thank-you page. Default: `"Thank you for completing this survey."` |
| `page_label` | Yes | Display label for the page (e.g. `"Page 1"`). Used for readability only. |
| `page_developer_name` | Yes | API name of the page (e.g. `"p_1"`, `"p_segment_a"`). All questions on the same logical page share the same value. |
| `page_order` | Yes | Integer. Pages rendered in ascending order. First content page = `1`. |
| `question_text` | Yes | The question displayed to the respondent. |
| `question_developer_name` | Yes | Salesforce API name for the field. Must be unique within the survey. |
| `question_type` | Yes | See §13d below. |
| `question_order` | Yes | Integer. Questions on a page displayed in ascending order. |
| `required` | No | `"true"` or `"false"`. Default: `"false"`. |
| `choices` | Conditional | Pipe-separated choice labels: `"Option A\|Option B\|Option C"`. Required for: `RadioButton`, `Picklist`, `MultiselectPicklist`, `StackRank`. Leave blank for all other types. |
| `slider_min` | No | Minimum value for `Slider`. Start value for `Rating`/`CSAT`. Default: `1`. |
| `slider_max` | No | Maximum value for `Slider`. End value for `Rating`/`CSAT`. Default: `10`. |
| `branch_on_answer` | No | Answer label that triggers a page skip (single-rule branching). Leave blank if not branching. |
| `branch_to_page` | No | `page_developer_name` to jump to when `branch_on_answer` matches. Required if `branch_on_answer` is set. |
| `branch_rules` | No | JSON multi-rule branching (auto-generated by Veeva path). Leave blank when authoring directly. |
| `visibility_rule` | No | Question-level display logic: `"q_dev_name==answer_value"`. **Not supported on OfflineMobile** — leave blank for LSC surveys. |

### 13d. Supported question types

| `question_type` | Description | Choices needed? |
|---|---|---|
| `ShortText` | Single-line text input | No |
| `FreeText` | Multi-line text input | No |
| `Date` | Date picker | No |
| `Number` | Numeric input field | No |
| `Slider` | Horizontal slider (set min/max) | No |
| `RadioButton` | Single-select, radio button style | Yes (2+ choices) |
| `Picklist` | Single-select dropdown (max 20 choices) | Yes (2–20 choices) |
| `MultiselectPicklist` | Multi-select checkboxes (max 10 choices) | Yes (2–10 choices) |
| `Rating` | 1–N star/number rating (set min/max) | No (auto-generated) |
| `CSAT` | Customer satisfaction rating (same as Rating) | No (auto-generated) |
| `StackRank` | Ranked ordering (rendered as Picklist) | Yes (2+ choices) |
| `Description` | Read-only explanatory text (no input) | No |

### 13e. Minimal working example

A single-survey, two-question CSV:

```
survey_name,survey_developer_name,welcome_text,thankyou_label,thankyou_text,page_label,page_developer_name,page_order,question_text,question_developer_name,question_type,question_order,required,choices,slider_min,slider_max,branch_on_answer,branch_to_page,branch_rules,visibility_rule
My Survey,my_survey,Welcome!,Thank You,Thanks.,Page 1,p_1,1,How satisfied are you?,q_sat,RadioButton,1,true,Very Satisfied|Satisfied|Neutral|Dissatisfied|Very Dissatisfied,,,,,
My Survey,my_survey,Welcome!,Thank You,Thanks.,Page 1,p_1,1,Any comments?,q_comments,FreeText,2,false,,,,,,,
```

**Rules for repeating survey-level fields:**  
`survey_name`, `survey_developer_name`, `welcome_text`, `thankyou_label`, `thankyou_text` are **read from the first row of each survey**. Repeat the values on every row for consistency, but only the first occurrence is used to set survey-level metadata.

### 13f. Multi-page surveys (manual CSV)

To create multiple pages, use different `page_developer_name` and `page_order` values:

```
survey_name,...,page_label,page_developer_name,page_order,question_text,question_developer_name,...
My Survey,...,Page 1,p_1,1,Question on page 1,q1,...
My Survey,...,Page 2,p_2,2,Question on page 2,q2,...
```

### 13g. Single-rule branching (manual CSV)

Use `branch_on_answer` + `branch_to_page` on the question that drives branching.  
The respondent is sent to `branch_to_page` when they select `branch_on_answer`. All other answers continue to the next page in order.

```
survey_name,...,page_developer_name,page_order,question_text,question_developer_name,question_type,...,choices,branch_on_answer,branch_to_page
My Survey,...,p_1,1,Are you a specialist?,q_specialist_flag,RadioButton,...,Yes|No,Yes,p_specialist
My Survey,...,p_1,1,Your specialty?,q_specialty_name,ShortText,...,,,
My Survey,...,p_specialist,2,Which specialty?,q_specialty,Picklist,...,Cardiology|Oncology|Other,,
```

The question with `branch_on_answer` must be on the source page. `branch_to_page` must match a `page_developer_name` that exists in the same survey.

### 13h. How to upload / use

**Via Streamlit UI:**
1. Run: `streamlit run survey_app.py`
2. Open `http://localhost:8501` in a browser
3. Upload your `.csv` file in Step 1
4. Review the preview in Step 3 (check for validation errors)
5. Click Generate in Step 4, then Download ZIP

**Via CLI (generate only):**
```bash
python generate_surveys.py --csv path/to/your_surveys.csv --out path/to/output/flows/
```

**What gets created:**
One `.flow-meta.xml` file per `survey_developer_name` value in the CSV.

### 13i. Common mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| `survey_developer_name` starts with a digit | Validation error | Prefix with a letter, e.g. `s_2024_survey` |
| `survey_developer_name` has spaces or hyphens | Validation error | Use snake_case: `my_survey_name` |
| `choices` column missing for `RadioButton` / `Picklist` | Validation warning; empty question in flow | Add pipe-separated choices |
| `Picklist` with > 20 choices | Error | Split into two separate questions manually, or use `MultiselectPicklist` (max 10) |
| `branch_to_page` references a page not in CSV | Validation error | Ensure the target `page_developer_name` exists in the same survey |
| `visibility_rule` filled in | No error, but silently ignored on OfflineMobile | Leave blank; use `branch_on_answer` / `branch_to_page` instead |
| All questions on the same `page_order` value | All questions end up on one page | Assign distinct `page_order` integers for each logical page |
| Duplicate `question_developer_name` within a survey | Validation error | Each question must have a unique API name within a survey |
