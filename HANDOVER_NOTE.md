# Survey Migration — Handover Note
## For: Receiving Team
## Org: lsdev1 (epic.abe30022fb6d@orgfarm.salesforce.com)

---

## What Has Been Delivered

73 Salesforce OfflineMobile surveys have been migrated from Veeva CRM and deployed to the lsdev1 org. They are live and ready for testing and use on LSC iPad devices.

| What | Detail |
|---|---|
| Surveys deployed | 73 |
| Total questions | 604 |
| Surveys with page branching | 14 |
| Source system | Veeva CRM (`SURVEY_DATA.xlsx`) |
| Target | Salesforce Flow — `processType=Survey`, `surveyType=OfflineMobile` |

---

## Where to Find the Surveys

- **Salesforce org:** lsdev1 — search for any survey name in **Survey Builder** (`/survey/builderApp.app`) or in the Surveys list view
- **Flow metadata files (XML):** `/Users/apurba.roy/projects/lsdev1/force-app/main/default/flows/`
- **Migration tool:** `/Users/apurba.roy/survey_generator/` — use this to regenerate or add surveys
- **Full inventory:** `MIGRATION_SUMMARY.md` in the same folder — has every survey, page count, question types, and transformations applied

---

## How Surveys Work on the iPad (LSC OfflineMobile)

1. The survey appears inside a **Call record** on the LSC iPad app
2. The rep opens the call, selects the survey, and taps through pages
3. **Welcome page → Page 1 → (branch pages if applicable) → Thank You page**
4. For branching surveys: the answer on Page 1 routes the rep to the correct set of follow-up questions automatically
5. Responses sync back to Salesforce when the device is online

---

## Branching Surveys — What to Know

14 surveys have multi-page branching driven by a routing question on Page 1. When the rep selects an answer, the flow jumps to the corresponding branch page.

**How to verify in Survey Builder:**
- Open the survey in Survey Builder
- Go to branch logic — each rule should show a populated "Select page" value (e.g. "Page 2", "Page 3")
- If any "Select page" is blank, the survey XML has been correctly deployed but a browser refresh usually resolves the display

**Branching surveys by complexity:**

| Survey | Choices on Page 1 | Branch pages |
|---|---|---|
| ITA_Vaccine_Segmentation_HSP_24 | 4 | 4 |
| ITA_Vaccine_Segmentation_NAM_24 | 4 | 4 |
| Survey HCP ATTR-CM/Vyndaqel | 3 | 3 |
| Profilazione HCP Lorviqua | 3 | 3 |
| Elrexfio dicembre 2025 | 2 | 2 |
| Gastro Attitudinal Segmentation 2025 | 2 | 2 |
| IBRANCE Survey | 1 | 1 |
| ISF Ginecologo - Abrysvo | 1 | 1 |
| Cibinqo Attitudinal Segmentation 2025 | 1 | 1 |
| ISF GP - Paxlovid | 1 | 1 |
| IT_Survey_Eliquis | 1 | 1 |
| Vyndaqel Attitudinal | 1 | 1 |
| GP_Survey_Paxlovid | 1 | 1 |
| GPs_Survey_No_Promo_ATTR-CM | 1 | 1 |

---

## Question Types Used

Veeva question types were mapped to Salesforce OfflineMobile-compatible types:

| Type | What the rep sees on iPad | Count |
|---|---|---|
| Picklist | Single-select dropdown | 353 |
| RadioButton | Single-select radio buttons | 116 |
| FreeText | Open text input | 76 |
| Disclaimer | Read-only instructional text block | 28 |
| ShortText | Short single-line text | 8 |
| Date | Date picker | 6 |
| Slider | Numeric range slider | 5 |
| Rating / CSAT | Star / numeric rating | 5 |
| MultiSelect | Multi-select checkboxes | 5 |
| Number | Numeric input | 2 |

> **Note on Disclaimer:** Veeva disclaimer questions (`SURVEY_DISCLAIMER__C=1`) appear as a read-only text block — typically legal/consent text at the top of Page 1. The rep does not need to answer these; they just scroll past.

---

## Things That Were Adjusted During Migration

| What | Why |
|---|---|
| Veeva Disclaimer → Salesforce FreeText (read-only) | OfflineMobile has no native DisplayText field type |
| ROS-1 Testing Pathway: one Picklist split into Part 1 / Part 2 | Salesforce caps Picklist at 20 choices |
| Territory-split surveys (e.g. Adoption Ladder ×4, Litfulo ×5) | Same Veeva survey name exists for multiple territories — each deployed as a separate flow with unique developer name |
| Branching: picklist comparison uses element reference, not text | OfflineMobile runtime requirement — raw text comparison silently fails |
| Branching: branch pages chained in sequence | Required for Survey Builder to show all pages in the "Select page" dropdown |

---

## Testing Recommendations

**Start with these surveys to confirm branching works end-to-end:**

1. **ITA_Vaccine_Segmentation_HSP_24** — most complex (4 branches). Test all 4 answer choices and verify each lands on the correct follow-up page.
2. **Survey HCP ATTR-CM/Vyndaqel** — 3 branches, 14 questions. Good regression test.
3. **GP_Survey_Paxlovid** — simplest branching (1 branch). Quick sanity check.

**For all surveys:** open on an iPad via a Call record (not the browser), complete all pages, and confirm responses appear in the Survey Response records in Salesforce after sync.

---

## Regenerating or Adding Surveys

If any survey needs to be updated or a new survey added:

1. Update `SURVEY_DATA.xlsx` in `/Users/apurba.roy/survey_generator/sample_data/`
2. Run: `python3 generate_surveys.py --xlsx sample_data/SURVEY_DATA.xlsx --deploy lsdev1`
3. This regenerates all surveys and deploys in one step

For a new survey from scratch (no Veeva source), use the CSV template at `sample_data/lsc_survey_template.csv`.

---

## Key Contacts / Reference Files

| Resource | Location |
|---|---|
| Migration tool | `~/survey_generator/generate_surveys.py` |
| Veeva→LSC transformer | `~/survey_generator/veeva_to_lsc.py` |
| Full survey inventory | `~/survey_generator/MIGRATION_SUMMARY.md` |
| Technical documentation | `~/survey_generator/TECHNICAL_DOC.md` |
| Special logic / edge cases | `~/survey_generator/SPECIAL_LOGIC.md` |
| Flow XML files | `~/projects/lsdev1/force-app/main/default/flows/` |
