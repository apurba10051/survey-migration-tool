# Survey Migration Tool

[![Build macOS App](https://github.com/apurba10051/survey-migration-tool/actions/workflows/build.yml/badge.svg)](https://github.com/apurba10051/survey-migration-tool/actions/workflows/build.yml)

Migrates Veeva CRM surveys to **LSC OfflineMobile** Flow XML, with a Streamlit UI for preview, validation, and download. Packaged as a double-click macOS `.app` (no Python required) and built for both Apple Silicon and Intel via GitHub Actions.

---

## Download

<p align="center">
<a href="https://github.com/apurba10051/survey-migration-tool/releases/latest/download/Survey-Generator-macOS-arm64.zip">
<img src="https://img.shields.io/badge/Download-Apple%20Silicon%20(M1%2FM2%2FM3%2FM4)-000000?style=for-the-badge&logo=apple&logoColor=white" alt="Download for Apple Silicon"/>
</a>
<br/><sub>macOS arm64 · M1 / M2 / M3 / M4</sub>
</p>

> **First launch:** macOS will block an unsigned app. Right-click → **Open** → **Open** to approve once.

All releases → [Releases page](https://github.com/apurba10051/survey-migration-tool/releases)

---

## What it does

1. Accepts a Veeva `SURVEY_DATA.xlsx` export (two tabs: `SURVEY_VOD` + `SURVEY_QUESTION_VOD`) or a plain CSV
2. Transforms Veeva question types, answer choices, and branch conditions into Flow XML
3. Produces `.flow-meta.xml` files ready to deploy

---

## Project structure

```
survey-migration-tool/
│
├── survey_app.py             # Streamlit UI — upload, preview, generate, download
├── survey_pipeline.py        # Orchestration: parse → validate → build → render
├── generate_surveys.py       # Core builder — constructs Flow XML data structures
├── veeva_to_lsc.py           # Veeva XLSX → intermediate CSV transformer
├── launcher.py               # PyInstaller entry point (opens Streamlit in browser)
│
├── templates/
│   └── survey_flow.xml.j2    # Jinja2 template that renders the Flow XML
│
├── sample_data/
│   └── lsc_survey_template.csv   # Blank CSV template for manually authored surveys
│
├── survey_generator.spec     # PyInstaller build spec (macOS arm64 / x86_64)
├── requirements.txt          # Python dependencies
├── Dockerfile                # Container build for server/CI use
│
├── .github/
│   └── workflows/
│       └── build.yml         # GitHub Actions — builds macOS arm64 + x86_64 on tag push
│
├── MIGRATION_SUMMARY.md      # Full inventory of all 73 migrated surveys
├── HANDOVER_NOTE.md          # Plain-language guide for the receiving team
├── TECHNICAL_DOC.md          # Deep-dive: flow structure, element types, known limits
└── SPECIAL_LOGIC.md          # Edge cases: branch chaining, disclaimers, Picklist cap, etc.
```

---

## Running locally (Python)

```bash
pip install -r requirements.txt
streamlit run survey_app.py
```

Opens at `http://localhost:8501`.

---

## Running via Docker

```bash
docker build -t survey-migration-tool .
docker run -p 8501:8501 survey-migration-tool
```

Opens at `http://localhost:8501`.

---

## macOS desktop app (no Python required)

Download the latest build from the [Download](#download) section above, unzip, and double-click `Survey Generator.app`.

The app starts a local Streamlit server and opens your browser automatically. No Python installation needed.

---

## Building the app yourself

Requires Python 3.11+ and PyInstaller:

```bash
pip install -r requirements.txt pyinstaller
pyinstaller survey_generator.spec --noconfirm
# Output: dist/Survey Generator.app
```

### GitHub Actions (CI builds)

Pushing a version tag triggers automatic builds for both architectures:

```bash
git tag v1.2.0
git push origin v1.2.0
```

The workflow (`.github/workflows/build.yml`) runs on:
- `macos-14` → arm64 (Apple Silicon)
- `macos-13` → x86_64 (Intel)

Both `.zip` files are published as a GitHub Release automatically.

---

## Usage — Veeva XLSX migration

1. Export `SURVEY_DATA.xlsx` from Veeva CRM (two tabs: `SURVEY_VOD`, `SURVEY_QUESTION_VOD`)
2. Upload it in the UI
3. Review the survey preview — pages, questions, branch logic, question types
4. Click **Generate XML Files**
5. Download `flows.zip` or save directly to your Salesforce project folder
6. Deploy: `sf project deploy start --source-dir force-app/main/default/flows`

## Usage — CSV (new surveys)

Use `sample_data/lsc_survey_template.csv` as a starting point. Fill in one row per question, upload the CSV in the UI.

---

## Key transformations (Veeva → Salesforce)

| Veeva | Salesforce LSC | Notes |
|---|---|---|
| `SURVEY_DISCLAIMER__C=1` | FreeText (read-only) | OfflineMobile has no DisplayText type |
| 3+ choices, no weights | Picklist | |
| ≤2 choices | RadioButton | |
| Any choice weight ≠ 0 | MultiselectPicklist | Bitmask weights become `<score>` |
| `CONDITION_VOD__C` | `<decisions>` + branch pages | Comparison uses `<elementReference>`, not raw string |
| >20 Picklist choices | Split into Part 1 / Part 2 | Salesforce hard cap |
| Duplicate survey names | One flow per unique name | Territory variants share questions in Tab 2 |
| Cyrillic / non-ASCII names | ID-based developer name | Display label preserved exactly |

---

## Question types supported

`Picklist` · `RadioButton` · `FreeText` · `ShortText` · `Disclaimer` · `MultiSelect` · `Rating` · `CSAT` · `Slider` · `Date` · `Number`

---

## Dependencies

| Package | Purpose |
|---|---|
| `streamlit` | Web UI |
| `jinja2` | Flow XML templating |
| `pandas` | XLSX / CSV parsing |
| `openpyxl` | Excel file reading |
