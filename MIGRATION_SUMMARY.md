# Veeva CRM → Salesforce LSC OfflineMobile Survey Migration
## Migration Summary Document

**Target org:** lsdev1 (epic.abe30022fb6d@orgfarm.salesforce.com)  
**Target object:** Salesforce Flow — `processType=Survey`, `surveyType=OfflineMobile`  
**Migration tool:** `~/survey_generator/generate_surveys.py` + `veeva_to_lsc.py`  
**Document date:** 2026-06-24

---

## 1. Migration at a Glance

| Metric | Value |
|---|---|
| Total surveys deployed | **73** |
| Total questions migrated | **604** |
| Surveys with branching (multi-page) | **14** |
| Surveys single-page | **54** |
| Surveys multi-page (no branching) | **5** |
| Max questions in one survey | **66** (Survey questions on moderate-severe atopic dermatitis) |
| Max pages in one survey | **6** (All Star Survey Testing) |
| Surveys with Disclaimer text | **28** |
| Surveys requiring Picklist split | **1** (ROS-1 Testing Pathway) |
| Surveys with Rating/CSAT auto-choices | **3** |

---

## 2. Question Type Breakdown — All 604 Questions

| Question Type (SF LSC) | Count | % of total | Notes |
|---|---:|---:|---|
| Picklist | 353 | 58% | Veeva 3+ choices, all weights = 0 |
| RadioButton | 116 | 19% | Veeva ≤2 choices, or ≤3 choices, all weights = 0 |
| FreeText | 76 | 13% | Veeva: no choices (open text) |
| Disclaimer | 28 | 5% | Veeva: `SURVEY_DISCLAIMER__C=1` → rendered as read-only InputField |
| ShortText | 8 | 1% | Manually authored (CSV path only) |
| MultiSelect | 5 | <1% | Veeva: any choice weight ≠ 0 (bitmask) |
| Rating/CSAT | 5 | <1% | Numeric star rating — choices auto-generated from min/max |
| Slider | 5 | <1% | Numeric range slider |
| Date | 6 | <1% | Date input field |
| Number | 2 | <1% | Numeric input field |
| **Total** | **604** | | |

---

## 3. Special Transformations Applied (Veeva → SF LSC)

### 3a. Disclaimer → FreeText InputField
- **Trigger:** `SURVEY_DISCLAIMER__C = 1` in Veeva, or question text starts with "disclaimer"
- **Transform:** Mapped to `fieldType=InputField`, `dataType=String` with no choices. Rendered as read-only instructional text on the iPad.
- **Affected surveys:** 28 surveys (typically the first question on Page 1)

### 3b. Picklist Split (>20 choices → Part 1 / Part 2)
- **Trigger:** A Picklist question in Veeva has more than 20 answer choices (Salesforce hard cap)
- **Transform:** Split into two consecutive questions — Part 1 takes first 20 choices, Part 2 takes the remainder. Developer name of Part 2 gets `_b` suffix.
- **Affected surveys:** 1 survey — ROS-1 Testing Pathway (original question had >20 choices)

### 3c. Rating / CSAT Auto-Choice Generation
- **Trigger:** Question type resolved as Rating or CSAT
- **Transform:** Numeric choices auto-generated from `MIN_SCORE_VOD__C` to `MAX_SCORE_VOD__C` (e.g. 1–5 → 5 choices). Each choice has `dataType=Number` and `<numberValue>` instead of `<stringValue>`.
- **Affected surveys:** 3 surveys

### 3d. CONDITION_VOD__C → Multi-Page Branching
- **Trigger:** One or more questions in a Veeva survey have `CONDITION_VOD__C` populated (e.g. `Q01="Internista/Geriatra"`)
- **Transform (4 steps):**
  1. **SOURCE_ID_VOD__C lookup** — Q-label (e.g. `Q01`) matched to question NAME (e.g. `SQ00034519`) using `SOURCE_ID_VOD__C` as the authoritative index
  2. **Page assignment** — each distinct condition answer value assigned its own branch page (`p_ans_0`, `p_ans_1`, …). Questions sharing the same condition land on the same page.
  3. **Decision element** — one `<decisions>` element per router question, one `<rules>` per answer. Each rule uses `<elementReference>` pointing to the choice's API name (not raw `<stringValue>`) — required by the OfflineMobile runtime.
  4. **Branch page chaining** — terminal branch pages are connected sequentially (`p_ans_0 → p_ans_1 → p_ans_2`) so all pages appear in the Survey Builder "Select page" dropdown. The last branch page has no connector (flow ends, advances to Thank You).
- **Affected surveys:** 14 surveys

### 3e. Weighted Choices (Veeva bitmask → SF score)
- **Trigger:** Any choice weight ≠ 0 in `ANSWER_CHOICE_VOD__C` (e.g. `ChoiceA;1;ChoiceB;2`)
- **Transform:** Question type mapped to `MultiselectPicklist`. Each choice gets a `<score>` element with its weight value.
- **Affected surveys:** 0 in current batch (feature implemented, not triggered)

### 3f. Duplicate Survey Name Handling (Territory Splits)
- **Trigger:** Same survey display name appears with multiple IDs in the Veeva export (territory variants)
- **Transform:** Each territory instance gets a unique developer name: `{slugified_name}_{last_6_chars_of_ID}` (e.g. `adoption_ladder_d_onchaem1`, `adoption_ladder_d_onchaem2`)
- **Affected surveys:** Adoption Ladder (×4), Aussendienst Fragebogen (×2), Service externe questionnaire (×2), Questionnaire Litfulo 2025 (×5) — 13 territory-split instances

### 3g. Non-ASCII / Cyrillic Survey Names
- **Trigger:** Survey display names in non-Latin scripts (Russian, Ukrainian)
- **Transform:** Developer name generated from ID-based fallback when slugify produces empty string. Display name preserved exactly in `<label>` and `<interviewLabel>`.
- **Affected surveys:** Сегментация PERSONAS KZ, Канали комунікації

---

## 4. Branching Surveys — Detail

14 surveys use `CONDITION_VOD__C`-driven multi-page branching. All were fixed for three issues discovered during migration:

| Issue | Root Cause | Fix Applied |
|---|---|---|
| Branching not working at runtime | `<stringValue>` used instead of `<elementReference>` for picklist comparison | Template updated to emit `<elementReference>` with choice API name |
| Flow terminates immediately (no branch pages shown) | Missing `<defaultConnector>` on `<decisions>` element | Generator falls back to `all_branch_pages[0]` when no page follows last branch |
| Survey Builder "Select page" shows blank for branch pages beyond the first | Builder only traverses `<connector>`/`<defaultConnector>` links — pages reachable only via decision rule connectors are invisible | Terminal branch pages chained sequentially so all are in the connector graph |

| Survey | Total Pages | Branch Pages | Branch Depth | Router Question |
|---|---:|---:|---|---|
| ITA_Vaccine_Segmentation_HSP_24 | 5 | 4 | 4-deep chain | SQ00033840 |
| ITA_Vaccine_Segmentation_NAM_24 | 5 | 4 | 4-deep chain | SQ00033838 |
| Survey HCP ATTR-CM/Vyndaqel | 4 | 3 | 3-deep chain | SQ00034519 |
| Profilazione HCP Lorviqua | 4 | 3 | 3-deep chain | SQ00034350 |
| Elrexfio dicembre 2025 | 3 | 2 | 2-deep chain | SQ00038821 |
| Gastro Attitudinal Segmentation 2025 | 3 | 2 | 2-deep chain | SQ00035748 |
| IBRANCE Survey | 2 | 1 | 1 branch | SQ00036536/39/42 |
| ISF Ginecologo - Abrysvo | 2 | 1 | 1 branch | SQ00040468 |
| Cibinqo Attitudinal Segmentation 2025 | 2 | 1 | 1 branch | SQ00035744 |
| ISF GP - Paxlovid | 2 | 1 | 1 branch | SQ00040474 |
| IT_Survey_Eliquis | 2 | 1 | 1 branch | SQ00034026 |
| Vyndaqel Attitudinal | 2 | 1 | 1 branch | SQ00038301 |
| GP_Survey_Paxlovid | 2 | 1 | 1 branch | SQ00035272 |
| GPs_Survey_No_Promo_ATTR-CM | 2 | 1 | 1 branch | SQ00035279 |

---

## 5. All Deployed Surveys — Full Inventory

| # | Survey Name | Pages | Qs | Branching | Question Types | Special Transformations |
|---|---|---:|---:|---|---|---|
| 1 | Adoption Ladder_D_ONC-HAEM1 | 1 | 14 | No | FreeText×7, RadioButton, Picklist×6 | — |
| 2 | Adoption Ladder_D_ONC-HAEM2 | 1 | 14 | No | FreeText×7, RadioButton, Picklist×6 | — |
| 3 | Adoption Ladder_F_ONC-HAEM1 | 1 | 14 | No | FreeText×7, RadioButton, Picklist×6 | — |
| 4 | Adoption Ladder_F_ONC-HAEM2 | 1 | 14 | No | FreeText×7, RadioButton, Picklist×6 | — |
| 5 | All Star Survey Testing | 6 | 12 | Yes (single-page) | FreeText×2, ShortText, RadioButton, Picklist×3, Rating/CSAT×2, Slider, Date×2 | Rating auto-choices |
| 6 | All Question Types Survey | 6 | 15 | Yes (single-page) | FreeText×3, ShortText, RadioButton, Picklist×3, MultiSelect, Rating/CSAT×2, Slider, Date×2, Number | Rating auto-choices |
| 7 | Aussendienst Fragebogen Veeva– Hämophilie_D_ONC-HAEM1 | 1 | 15 | No | FreeText×6, RadioButton×3, Picklist×6 | Territory split |
| 8 | Aussendienst Fragebogen Veeva– Hämophilie_D_ONC-HAEM2 | 1 | 15 | No | FreeText×6, RadioButton×3, Picklist×6 | Territory split |
| 9 | Cibinqo Attitudinal Segmentation 2025 | 2 | 4 | Yes — 1 choice → 1 branch page | Disclaimer, RadioButton×3 | Disclaimer→FreeText; Branch page chained; CONDITION_VOD__C→elementReference |
| 10 | Covid Service Survey 2026 | 1 | 1 | No | Picklist | — |
| 11 | Disease Awareness Vyndaqel DE | 1 | 10 | No | Picklist×10 | — |
| 12 | Disease Awareness Vyndaqel FR | 1 | 5 | No | Picklist×5 | — |
| 13 | Eliquis Environment Insight Survey | 1 | 23 | No | FreeText, RadioButton×11, Picklist×11 | — |
| 14 | Elrexfio dicembre 2025 | 3 | 6 | Yes — 2 choices → 2 branch pages | Disclaimer, RadioButton×3, Picklist×2 | Disclaimer→FreeText; Branch pages chained 2-deep; CONDITION_VOD__C→elementReference |
| 15 | Elrexfio – Questionnaire qualifiant Segmentation INFIRMIERES | 1 | 8 | No | Disclaimer, Picklist×7 | Disclaimer→FreeText |
| 16 | Fragebogen Pneumoologen DE | 1 | 10 | No | Picklist×10 | — |
| 17 | Fragebogen Pneumoologen FR | 1 | 10 | No | Picklist×10 | — |
| 18 | Gastro Attitudinal Segmentation 2025 | 3 | 4 | Yes — 2 choices → 2 branch pages | Disclaimer, RadioButton×3 | Disclaimer→FreeText; Branch pages chained 2-deep; CONDITION_VOD__C→elementReference |
| 19 | Genotropin Detail Aid Survey | 1 | 5 | No | FreeText, RadioButton, Picklist×3 | — |
| 20 | GP_Survey_Accesso | 1 | 2 | No | Disclaimer, Picklist | Disclaimer→FreeText |
| 21 | GP_Survey_Paxlovid | 2 | 3 | Yes — 1 choice → 1 branch page | Disclaimer, RadioButton×2 | Disclaimer→FreeText; Branch page chained; CONDITION_VOD__C→elementReference |
| 22 | GPs_Survey_No_Promo_ATTR-CM | 2 | 3 | Yes — 1 choice → 1 branch page | Disclaimer, RadioButton×2 | Disclaimer→FreeText; Branch page chained; CONDITION_VOD__C→elementReference |
| 23 | HCP Profiling Questionnaire | 1 | 4 | No | RadioButton, Picklist×3 | — |
| 24 | Hympavzi attitudinal | 1 | 4 | No | Disclaimer, RadioButton, Picklist×2 | Disclaimer→FreeText |
| 25 | IBRANCE Survey | 2 | 55 | Yes — 1 choice → 1 branch page | RadioButton×15, Picklist×40 | Branch page chained; CONDITION_VOD__C→elementReference |
| 26 | I&I Adoption Survey 1 | 1 | 3 | No | FreeText, Picklist×2 | — |
| 27 | I&I Adoption Survey 2 | 1 | 3 | No | FreeText, Picklist×2 | — |
| 28 | ISF Ginecologo - Abrysvo | 2 | 6 | Yes — 1 choice → 1 branch page | Disclaimer, RadioButton×2, Picklist×3 | Disclaimer→FreeText; Branch page chained; CONDITION_VOD__C→elementReference |
| 29 | ISF GP - Paxlovid | 2 | 4 | Yes — 1 choice → 1 branch page | Disclaimer, FreeText, RadioButton×2 | Disclaimer→FreeText; Branch page chained; CONDITION_VOD__C→elementReference |
| 30 | ISF GP - Vax Portfolio | 1 | 5 | No | Disclaimer, RadioButton×4 | Disclaimer→FreeText |
| 31 | ISF Igienista - Vax Portfolio | 1 | 5 | No | Disclaimer, RadioButton×3, Picklist | Disclaimer→FreeText |
| 32 | IT_Survey_Eliquis | 2 | 4 | Yes — 1 choice → 1 branch page | Disclaimer, RadioButton×2, Picklist | Disclaimer→FreeText; Branch page chained; CONDITION_VOD__C→elementReference |
| 33 | ITA_Vaccine_Segmentation_HSP_24 | 5 | 6 | Yes — 4 choices → 4 branch pages | Disclaimer, RadioButton×4, Picklist | Disclaimer→FreeText; Branch pages chained 4-deep; CONDITION_VOD__C→elementReference |
| 34 | ITA_Vaccine_Segmentation_NAM_24 | 5 | 6 | Yes — 4 choices → 4 branch pages | Disclaimer, RadioButton×4, Picklist | Disclaimer→FreeText; Branch pages chained 4-deep; CONDITION_VOD__C→elementReference |
| 35 | NAM Igienista - Vax Portfolio | 1 | 5 | No | Disclaimer, RadioButton×4 | Disclaimer→FreeText |
| 36 | NAM - Vyndaqel Attitud Giu26 | 1 | 2 | No | Disclaimer, Picklist | Disclaimer→FreeText |
| 37 | Persönlicher Consent | 1 | 2 | No | FreeText, MultiSelect | — |
| 38 | Сегментация PERSONAS KZ | 1 | 1 | No | Picklist | Non-ASCII name (Cyrillic) |
| 39 | Profilazione HCP Lorviqua | 4 | 5 | Yes — 3 choices → 3 branch pages | Disclaimer, RadioButton×2, Picklist×2 | Disclaimer→FreeText; Branch pages chained 3-deep; CONDITION_VOD__C→elementReference |
| 40 | Progetto FarmaCUore - Numero coupon ECG consegnati | 1 | 1 | No | FreeText | — |
| 41 | Questionnaire Veeva - Cresemba 2025 | 1 | 7 | No | Disclaimer, Picklist×6 | Disclaimer→FreeText |
| 42 | Questionnaire Veeva - Litfulo 2025 CAH | 1 | 8 | No | Disclaimer, Picklist×7 | Disclaimer→FreeText; Territory split |
| 43 | Questionnaire Veeva - Litfulo 2025 DE0100 | 1 | 8 | No | Disclaimer, Picklist×7 | Disclaimer→FreeText; Territory split |
| 44 | Questionnaire Veeva - Litfulo 2025 DE0200 | 1 | 8 | No | Disclaimer, Picklist×7 | Disclaimer→FreeText; Territory split |
| 45 | Questionnaire Veeva - Litfulo 2025 III100 | 1 | 8 | No | Disclaimer, Picklist×7 | Disclaimer→FreeText; Territory split |
| 46 | Questionnaire Veeva - Litfulo 2025 III200 | 1 | 8 | No | Disclaimer, Picklist×7 | Disclaimer→FreeText; Territory split |
| 47 | RD Gene Therapy Partners - Non Promo ABN survey | 1 | 2 | No | RadioButton, Picklist | — |
| 48 | ROS-1 Testing Pathway | 1 | 21 | No | FreeText×4, RadioButton, Picklist×16 | Picklist split (>20 choices → Part 1 / Part 2) |
| 49 | 2026 COVID Hospital Role Survey | 1 | 1 | No | RadioButton | — |
| 50 | Segmentation Portfolio Brands Antinfectiva_Antithrombotics | 1 | 5 | No | Picklist×5 | — |
| 51 | Segmentation Portfolio Brands CH_HC | 1 | 7 | No | Picklist×7 | — |
| 52 | Segmentation Portfolio Brands CH_HC 2 | 1 | 7 | No | Picklist×7 | — |
| 53 | Segmentation Portfolio Brands HEMATOLOGY | 1 | 2 | No | Picklist×2 | — |
| 54 | Segmentation Portfolio Brands LUNG_GU_KIDNEY_2 | 1 | 2 | No | Picklist×2 | — |
| 55 | Segmentation Portfolio Brands LUNG_GU_KIDNEY_3 | 1 | 2 | No | Picklist×2 | — |
| 56 | Segmentation Portfolio Brands ONC Breast | 1 | 1 | No | Picklist | — |
| 57 | Segmentation Portfolio Brands RD_ATTR-CM | 1 | 2 | No | Picklist×2 | — |
| 58 | Segmentation Proposal Survey of CH I&I | 1 | 8 | No | Picklist×8 | — |
| 59 | Segmentation Questionnaire | 3 | 15 | No | FreeText, ShortText, RadioButton, Picklist×9, Slider, Date, Number | — |
| 60 | Service externe questionnaire Veeva – Hémophilie_F_ONC-HAEM1 | 1 | 11 | No | FreeText×5, Picklist×6 | Territory split |
| 61 | Service externe questionnaire Veeva – Hémophilie_F_ONC-HAEM2 | 1 | 11 | No | FreeText×4, RadioButton, Picklist×6 | Territory split |
| 62 | Канали комунікації | 1 | 7 | No | FreeText×7 | Non-ASCII name (Ukrainian) |
| 63 | Survey A – Clinico Centro Cefalee | 1 | 4 | No | Disclaimer, Picklist×3 | Disclaimer→FreeText |
| 64 | Survey B – Neurologo extra Centro Cefalee | 1 | 7 | No | Disclaimer, RadioButton×3, Picklist×3 | Disclaimer→FreeText |
| 65 | Survey HCP ATTR-CM/Vyndaqel | 4 | 14 | Yes — 3 choices → 3 branch pages | Disclaimer, RadioButton×9, Picklist×4 | Disclaimer→FreeText; Branch pages chained 3-deep; CONDITION_VOD__C→elementReference |
| 66 | Survey questions on moderate-severe atopic dermatitis | 1 | 66 | No | RadioButton×11, Picklist×55 | — |
| 67 | Survey Test SKM | 2 | 9 | No | FreeText, ShortText×2, RadioButton×2, MultiSelect, Rating/CSAT, Slider, Date | Rating auto-choices |
| 68 | Teilnahme am VCC Programm 2025 | 1 | 2 | No | MultiSelect×2 | — |
| 69 | Test Survey Paging | 3 | 3 | Yes (single-page) | ShortText×2, Picklist | Reference survey (manually created in org) |
| 70 | Visit Survey | 1 | 3 | No | ShortText, Picklist, Slider | — |
| 71 | VTE Hospital Protocol Survey | 1 | 7 | No | FreeText, RadioButton×2, Picklist×4 | — |
| 72 | Vyndaqel Attitudinal | 2 | 4 | Yes — 1 choice → 1 branch page | Disclaimer, RadioButton×3 | Disclaimer→FreeText; Branch page chained; CONDITION_VOD__C→elementReference |
| 73 | Zinforo (Ceftaroline Fosamil) Formulary Survey | 1 | 6 | No | FreeText, Picklist×5 | — |

---

## 6. Migration Tool Architecture

```
SURVEY_DATA.xlsx
       │
       ▼
veeva_to_lsc.py         — Tab 1 (SURVEY_VOD): survey metadata, welcome text, territory dedup
  transform()           — Tab 2 (SURVEY_QUESTION_VOD): questions, types, choices, conditions
       │                   ├─ SOURCE_ID_VOD__C lookup → Q-label → question NAME
       │                   ├─ CONDITION_VOD__C parsing → branch page assignment
       │                   ├─ SURVEY_DISCLAIMER__C → Description type
       │                   └─ ANSWER_CHOICE_VOD__C → labels + bitmask detection
       │ CSV (in-memory)
       ▼
generate_surveys.py
  parse_csv()           — Load structured CSV rows
  _build_surveys()      — Resolve types, build choices, decisions, page connectors
       │                   ├─ choice_api_name enrichment → elementReference in decisions
       │                   ├─ defaultConnector fallback → all_branch_pages[0]
       │                   └─ terminal branch page chaining → connector graph for Builder
       │ survey dicts
       ▼
survey_flow.xml.j2      — Jinja2 template → .flow-meta.xml
       │
       ▼
sf project deploy start → lsdev1
```

---

## 7. Known Limitations & Platform Constraints

| Constraint | Detail |
|---|---|
| Picklist max 20 choices | Hard Salesforce cap. Questions >20 choices split into Part 1 / Part 2. |
| MultiselectPicklist max 10 choices | Truncated to first 10 with warning printed. |
| OfflineMobile — no question-level visibility rules | `visibilityRule` inside `<fields>` is not processed by OfflineMobile runtime. Branching must be done at page level via `<decisions>`. |
| `thank_you_page` is not a real element | Cannot be used as a `<connector>` target — deploy error. It is only referenced as a string value in `pageNamesInOrder`. |
| DateTime → Date fallback | LSC OfflineMobile does not support DateTime. DateTime questions mapped to Date. |
| CSAT → Rating fallback | CSAT question type maps to `survey:runtimeRating` extension (same component). |
| StackRank → Picklist fallback | StackRank not supported on OfflineMobile. Mapped to Picklist. |
| Survey auto-creation | `Survey` sObject record created automatically by platform on successful active-flow deploy — no manual insert required or possible. |
| Deploy is transactional | A single broken flow in a batch deploy rolls back the entire batch. |

---

*Generated from live flow XML in `lsdev1/force-app/main/default/flows/`. Re-run `generate_surveys.py --xlsx SURVEY_DATA.xlsx` to regenerate all surveys from source.*
