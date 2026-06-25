# Survey Generator — Special Logic Reference

All non-obvious decisions made during Veeva → LSC survey transformation and flow generation.

---

## 1. Picklist Split (>20 choices)

**Where:** `veeva_to_lsc.py` → Step 5  
**Trigger:** A `Picklist` question has more than 20 answer choices  
**Behaviour:** Split into two consecutive questions:
- Question text gets ` (Part 1 of 2)` / ` (Part 2 of 2)` appended
- Developer name of Part 2 gets `_b` suffix (e.g. `SQ00007511_b`)
- First 20 choices → Part 1; remaining choices → Part 2

**Why:** Salesforce Survey Flow caps Picklist at 20 choices per question.

---

## 2. MultiselectPicklist Cap (>10 choices)

**Where:** `veeva_to_lsc.py` → Step 5  
**Trigger:** A `MultiselectPicklist` question has more than 10 choices  
**Behaviour:** Truncated to first 10 choices. No split (multi-select split would be confusing to respondents).  
**Warning printed:** `⚠️  {question} ({type}): N choices → truncated to 10`

**Why:** Salesforce Survey Flow caps MultiselectPicklist at 10 choices.

---

## 3. Question Type Inference from Veeva

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

## 4. Bitmask / Choice Weight Handling

**Where:** `veeva_to_lsc.py` → `parse_choices()` / `generate_surveys.py` → `_build_surveys()`  
**Veeva format:** `ChoiceA;1;ChoiceB;0;ChoiceC;4` (label;weight pairs)  
**Logic:**
- If any weight ≠ 0 → question becomes `MultiselectPicklist`, weights become `<score>` elements in XML
- If all weights are equal → weights dropped entirely (no `<score>` element)

---

## 5. Question Text Prefix Stripping

**Where:** `veeva_to_lsc.py` → `strip_question_prefix()`  
**Strips these Veeva authoring artifacts from question text:**
- `QTN:`, `QTB:`, `QTP:`, `QTB-1)`, `QTP-2.` and similar prefixes
- `(For the representative to answer)` preambles
- Trailing/leading whitespace and newlines (normalised to single space)

---

## 6. Duplicate Survey Names (Territory Variants)

**Where:** `veeva_to_lsc.py` → Step 1  
**Trigger:** Two or more surveys in `SURVEY_VOD` share the same `NAME` (same survey deployed to different territories)  
**Behaviour:** Each variant gets the last 6 characters of its Salesforce record ID appended to the developer name  
Example: `adoption_ladder` → `adoption_ladder_4traay` and `adoption_ladder_ybeaao`

**Why:** Veeva's `SURVEY_QUESTION_VOD` tab references surveys by display name, not ID. Without this, territory variants share one developer name and their questions merge.

---

## 7. Non-ASCII Survey Names

**Where:** `veeva_to_lsc.py` → Step 1  
**Trigger:** Survey name contains only non-ASCII characters (e.g. Cyrillic) — `slugify()` returns an empty string  
**Behaviour:** Developer name falls back to `survey_{last8ofID}` (e.g. `survey_ab30022f`)

---

## 8. Choice Name Uniqueness (MD5 Hash Prefix)

**Where:** `generate_surveys.py` → `_build_surveys()`  
**Format:** `c_{s_dev}_{q_slug}_{t_slug}_{index}`  
Where `s_dev` = `{10-char slug of survey dev name}_{6-char MD5 of full dev name}`

**Why:** Salesforce requires all `<choices>` names to be globally unique across the org. Simple slug truncation caused collisions between territory variants (e.g. `adoption_ladder_d_onchaem1` and `adoption_ladder_f_onchaem1` both truncate to `adoption_ladde`). The MD5 hash of the full developer name guarantees uniqueness even when names share a truncated prefix.

---

## 9. Non-ASCII Choice Text (Empty Slug Fallback)

**Where:** `generate_surveys.py` → `_build_surveys()`  
**Trigger:** Choice text contains only non-ASCII characters → `slugify()` returns empty string  
**Behaviour:** Slug falls back to `opt{index}` (e.g. `opt0`, `opt1`)  
**Also applied to:** Survey slug prefix — falls back to `q{index}` if question dev name slugifies to empty

**Why:** Salesforce API names must be alphanumeric + underscore. Empty slugs produce double-underscore names (`c_survey__0`) which are invalid.

---

## 10. Trailing Underscore Prevention

**Where:** `generate_surveys.py` → everywhere slugs are constructed  
**Behaviour:** `.strip("_")` applied after every slug truncation  
**Why:** Salesforce API names cannot end with an underscore. Truncating mid-word (e.g. `gp_survey_` → last char is `_`) would produce invalid names.

---

## 11. Survey Developer Name Starts with Digit

**Where:** `veeva_to_lsc.py` → `slugify()` / `generate_surveys.py` → `slugify()`  
**Trigger:** Name begins with a number after non-ASCII stripping (e.g. `2026 COVID Survey` → `2026_covid_survey`)  
**Behaviour:** Prepend `s_` → `s_2026_covid_survey`

**Why:** Salesforce API names must start with a letter.

---

## 12. fieldText XML-Encoding-Aware Truncation

**Where:** `generate_surveys.py` → `_build_surveys()`  
**Trigger:** Question text, after XML-encoding, exceeds 960 characters  
**Behaviour:** Iteratively shrink to 90% of current length until encoded length ≤ 960  
**Warning printed:** `[TRUNCATE] '{q_dev}' → {N} raw chars`

**Why:** Salesforce caps the `fieldText` "User Input Prompt" at ~1000 XML-encoded characters. The `<p><strong>…</strong></p>` wrapper adds ~40 encoded chars, leaving ~960 for the text. The limit is on the *encoded* value, not raw characters — a single `&` counts as 5 (`&amp;`).

---

## 13. Multi-Page Branching from CONDITION_VOD__C

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

## 14. Router Question Detection — SOURCE_ID_VOD__C Authoritative Lookup

**Where:** `veeva_to_lsc.py` → Step 5a / 5b  
**Problem:** Veeva's `CONDITION_VOD__C` uses `Q01="answer"` where `Q01` is the label stored in `SOURCE_ID_VOD__C` on the router question — not a 0-based count of choice-bearing questions.  
**Strategy:** Build a per-survey `source_id_map`: `{q_label → question_NAME}` directly from `SOURCE_ID_VOD__C`. Conditions are then resolved by exact label match (e.g. `Q01` → `SQ00034519`). A warning is printed if no `SOURCE_ID_VOD__C` value matches the label in a condition.

**Multiple routers:** A survey may have more than one independent routing question (e.g. Q00 and Q01 each branching to different page sets). Each router gets its own `<decisions>` element. `router_rules_per_survey[survey_dev]` is keyed by `router_NAME` to support this.

---

## 15. Type Fallbacks (Unsupported LSC Types)

**Where:** `generate_surveys.py` → `TYPE_MAP`

| Veeva / input type | Falls back to | Reason |
|---|---|---|
| `DateTime` | `Date` field type | LSC Mobile does not support DateTime input |
| `CSAT` | `survey:runtimeRating` extension | Same platform component as Rating |
| `StackRank` | `survey:runtimePicklist` extension | No native StackRank in OfflineMobile |
| `Description` | `InputField` (no extension) | `DisplayText` unsupported in OfflineMobile; rendered as a read-only FreeText field |

---

## 16. Veeva Format Auto-Detection (Format A vs B)

**Where:** `generate_surveys.py` → `_detect_veeva_format()`  
**Format B** (response records export) detected when headers contain `SURVEY_TARGET_VOD__C` or `QUESTION_TEXT_VOD__C`  
**Format A** (question definitions export) assumed otherwise  

**Delimiter** also auto-detected: tab-separated if the first line contains a tab, otherwise comma.

---

## 17. Format B Deduplication

**Where:** `generate_surveys.py` → `parse_source()`  
**Trigger:** Using Veeva Format B (response records) — the same question appears once per account response  
**Behaviour:** `SURVEY_QUESTION_VOD__C` used as dedup key; first occurrence kept, subsequent rows for the same question skipped

---

## 18. Welcome Text Source

**Where:** `veeva_to_lsc.py` → Step 1  
**Primary source:** `DC1__C` field on the `SURVEY_VOD` tab  
**Fallback:** `"Welcome to the {survey_name} survey. Please answer all questions."`

---

## 19. Single-Rule Branching (CSV-authored surveys)

**Where:** `generate_surveys.py` → `_build_surveys()`  
**Trigger:** A question in a CSV-authored survey has `branch_on_answer` and `branch_to_page` columns set  
**Behaviour:** One `<decisions>` element with a single `<rules>` entry. The `defaultConnector` skips to the page *after* the branch target (so the branched page is not double-visited).

This is distinct from multi-rule branching used in the Veeva path.

---

## 20. Rating / CSAT Choice Auto-Generation

**Where:** `generate_surveys.py` → `_build_surveys()`  
**Trigger:** Question type is `Rating` or `CSAT`  
**Behaviour:** Numeric choices are generated automatically from `slider_min` to `slider_max` (inclusive). No choices need to be supplied in the CSV.  
Default range: 1–5 for Rating, 1–10 for CSAT (if not overridden).

---

## 21. Page Ordering and Distribution

### 21a. Veeva path — no-branching surveys
All questions land on a single page `p_1` with `page_order = 1`.  
The Veeva export has no page concept; pages are only introduced by branching logic.

### 21b. Veeva path — branching surveys
Pages are assigned during Step 5b of `veeva_to_lsc.py`:

| Page | `page_developer_name` | `page_order` | Contains |
|---|---|---|---|
| Always-shown | `p_1` | 1 | All unconditional questions + the router question |
| Answer group 0 | `p_ans_0` | 2 | Questions conditioned on 1st unique answer |
| Answer group 1 | `p_ans_1` | 3 | Questions conditioned on 2nd unique answer |
| … | … | … | … |
| Answer group N | `p_ans_N` | N+2 | Questions conditioned on (N+1)th unique answer |

Answer groups are ordered by **first appearance** of their answer value in the sorted question list (sorted by `ORDER_VOD__C`).

### 21c. CSV path — multi-page surveys
`page_developer_name` and `page_order` are set directly in the CSV by the survey author.  
`_build_surveys()` sorts pages by `page_order` ascending before generating the flow.

### 21d. Flow page sequence in the XML
The Salesforce runtime determines page order from the `pageNamesInOrder` list variable (populated by the `pageNamesInOrder_Assignment` element). The sequence is always:

```
welcome_page → p_1 → [p_ans_0 … p_ans_N] → thank_you_page
```

`welcome_page` and `thank_you_page` are implicit — they are not authored pages and are always prepended / appended. Content pages appear in `page_order` sequence between them.

### 21e. Page connector chain
Each content page has a `<connector>` pointing to the next element:

| Page type | Connector target |
|---|---|
| Normal page (no branching) | Next page by order, or `None` (falls through to thank_you) |
| Router page (has `branch_rules`) | The decision element `d_{page_dev}_branch` |
| Terminal answer page (`p_ans_N`) | `None` — no connector; survey ends after this page |

The connector for the **last** normal page is `None` (omitted from XML), which causes the flow to end at thank_you.

---

## 22. API Name Rules and Enforcement

Salesforce API names must satisfy: start with a letter, contain only `[A-Za-z0-9_]`, no consecutive underscores (`__`), no trailing underscore, max 80 characters.

### 22a. Survey developer name
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

### 22b. Question developer name
**Veeva path:** Kept as-is from Veeva `NAME` field (e.g. `SQ00034519`). These are already valid Salesforce API names.  
**CSV path / Format A:** `slugify(question_text, max_len=40)` — same rules as 22a but capped at 40 chars.  
**Dedup within page (CSV/Format A):** If two questions produce the same slug, the second and subsequent ones get `_2`, `_3`, … appended.

### 22c. Page developer name
**No-branch surveys:** Always `p_1`  
**Branching surveys:** `p_1` (unconditional page) and `p_ans_0`, `p_ans_1`, … (answer pages)  
**CSV path:** Set directly by author in the `page_developer_name` column  
**Validation:** The `validate()` function in `survey_pipeline.py` checks that any `branch_to_page` value references an existing page developer name.

### 22d. Choice API names
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

### 22e. Decision element names
**Format:** `d_{page_developer_name}_branch`  
**Rule name:** `d_{page_developer_name}_branch_rule` (single-rule) or `d_{page_developer_name}_branch_rule_{index}` (multi-rule)

### 22f. Reserved / fixed element names
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

## 23. LSC Flow XML Structure — Platform-Specific Rules

These are constraints and behaviours enforced by the Salesforce Survey Flow platform for `OfflineMobile` surveys. Violating any of these causes a deploy error.

### 23a. processType and surveyType
```xml
<processType>Survey</processType>
<processMetadataValues>
    <name>surveyType</name>
    <value><stringValue>OfflineMobile</stringValue></value>
</processMetadataValues>
```
Both must be present. `OfflineMobile` is the only type used for LSC mobile surveys. Using `Online` or omitting `surveyType` produces a different (incompatible) survey experience.

### 23b. isSimpleSurvey must be false
```xml
<processMetadataValues>
    <name>isSimpleSurvey</name>
    <value><booleanValue>false</booleanValue></value>
</processMetadataValues>
```
`isSimpleSurvey=true` restricts the survey to a subset of question types and disables branching. All multi-question, multi-type, or branching surveys must use `false`.

### 23c. XML element ordering in the flow
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

### 23d. Welcome page position in XML
The `welcome_page` screen is written **last** among all `<screens>` elements, even though it is the first page the user sees. This matches the pattern observed in working org surveys and is required — placing `welcome_page` first in the XML causes the platform to behave incorrectly.

The welcome page connector points to `pages[0].developer_name` (the first content page, `p_1`).

### 23e. startElementReference points to the assignment, not the welcome page
```xml
<startElementReference>pageNamesInOrder_Assignment</startElementReference>
```
The flow starts by running the assignment (which populates `pageNamesInOrder`), which then connects to `welcome_page`. Setting `startElementReference` directly to `welcome_page` would bypass page-order population and break the survey's progress indicator.

### 23f. pageNamesInOrder — required for progress bar
The `pageNamesInOrder` string collection variable must be populated with page developer names in order: `welcome_page`, then all content pages in sequence, then `thank_you_page`. This drives the progress bar displayed to the user during the survey. It is an output variable so the runtime can read it.

### 23g. fieldText must be HTML-encoded rich text
```xml
<fieldText>&lt;p&gt;&lt;strong&gt;Question text here&lt;/strong&gt;&lt;/p&gt;</fieldText>
```
The question text is wrapped in `<p><strong>…</strong></p>` tags. The entire `fieldText` value is itself XML-encoded (angle brackets become `&lt;`/`&gt;`). This is how LSC renders question text in bold on the mobile survey screen.

### 23h. No visibilityRule on OfflineMobile surveys
The `<visibilityRule>` element (question-level display logic) is **not supported** for `OfflineMobile` + `isSimpleSurvey=false` surveys. Deploying any such survey with a `visibilityRule` on a question produces:

> *"You can't add display logic to the questions in a life sciences commercial survey. Remove the display logic."*

This is why branching is implemented via page-level `<decisions>` instead. The template still has a `visibilityRule` block (used only for `Online` or `isSimpleSurvey=true` surveys via the CSV path).

### 23i. Scale element for numeric question types
```xml
<scale>0</scale>
```
Required on `Slider`, `Number`, `Rating`, and `CSAT` question fields. Omitting it causes a deploy validation error for those types.

### 23j. Decision conditions require processMetadataValues and elementReference

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

### 23k. Decision elements must always have a defaultConnector

Every `<decisions>` element **must** have a `<defaultConnector>` with a valid `<targetReference>`. If no rule matches (e.g. during initial page load or an unexpected value), the runtime uses `defaultConnector`. Without it, the flow terminates immediately — the user sees welcome → p_1 → thank you with no branch pages.

```xml
<defaultConnector>
    <targetReference>p_ans_0</targetReference>
</defaultConnector>
<defaultConnectorLabel>Other</defaultConnectorLabel>
```

**Generator behaviour:** When all branch pages are terminal (no further pages after them — i.e. `last_idx + 1` overflows), `default_next` falls back to `all_branch_pages[0]` (the first branch page). This ensures the element is always emitted.

### 23m. Choice dataType differs by question type
- **Rating / CSAT questions:** choice `<dataType>Number</dataType>` and `<value><numberValue>…</numberValue></value>`
- **All other choice types:** choice `<dataType>String</dataType>` and `<value><stringValue>…</stringValue></value>`

Using the wrong dataType for Rating choices causes incorrect scoring.

### 23n. Description type has no dataType element
For `Description` questions (rendered as read-only text), the `<dataType>` element is **omitted** entirely from the `<fields>` block. All other question types include it.

### 23o. Slider requires min/max processMetadataValues
For `Slider` type questions, three extra `<processMetadataValues>` must appear inside the `<fields>` block:
```xml
<processMetadataValues><name>max</name><value><stringValue>10</stringValue></value></processMetadataValues>
<processMetadataValues><name>min</name><value><stringValue>1</stringValue></value></processMetadataValues>
<processMetadataValues><name>scale</name><value><stringValue>1</stringValue></value></processMetadataValues>
```
These are in addition to the `<scale>0</scale>` element on the field itself.

### 23p. allowPause differs between welcome page and content pages
- **Content pages:** `<allowPause>true</allowPause>`
- **Welcome page:** `<allowPause>false</allowPause>`

Pausing is not meaningful before the survey has started.

### 23q. styleProperties on every question field
Every `<fields>` element must include:
```xml
<styleProperties>
    <verticalAlignment><stringValue>top</stringValue></verticalAlignment>
    <width><stringValue>12</stringValue></width>
</styleProperties>
```
`width=12` means full-width (out of a 12-column grid). Omitting this block causes rendering issues on the mobile tablet.

### 23r. pageOptionsMap — required survey metadata
```xml
<processMetadataValues>
    <name>pageOptionsMap</name>
    <value><stringValue>{"p_1":{"isMovable":true,"isDeletable":true},...}</stringValue></value>
</processMetadataValues>
```
A JSON object mapping every content page developer name to `{"isMovable": true, "isDeletable": true}`. Must include all content pages. The welcome and thank-you pages are not included. Omitting any page from this map causes a deploy error.

### 23s. Survey record auto-creation
A `Survey` sObject record is automatically created by the platform when a Survey Flow deploys successfully with `status=Active`. No manual DML or Bulk API insert is needed or possible (`Survey` is not directly insertable via API).

### 23t. Deploy is transactional
If any one flow in a batch deploy fails, the entire deploy rolls back. All 66+ flows are deployed together, so a single broken flow blocks all others. Keep problem flows in a separate excluded folder (e.g. `flows_excluded/`) and deploy them separately once fixed.

### 23u. Terminal branch pages must be chained via connectors for Survey Builder visibility

**Problem:** The Survey Builder "Select page" dropdown (branch logic UI) only shows pages reachable via `<connector>` / `<defaultConnector>` elements. Pages reachable only through decision rule connectors are invisible — the dropdown shows blank for those rules even though the XML routing is correct.

**Symptom:** In a 3-way branch, the "Select page" dropdown shows "Page 2" populated once (via defaultConnector) but blank entries for the other two rules, even though the flow XML has correct `<connector><targetReference>p_ans_N</targetReference></connector>` on each rule.

**Fix:** Chain terminal branch pages sequentially so every page is reachable via the connector-only graph walk:
- `p_ans_0` → connector → `p_ans_1`
- `p_ans_1` → connector → `p_ans_2`
- `p_ans_2` → no connector (terminal, advances to Thank You)

The decision routing still works correctly — users are sent to the right branch page by the decision rules, and from any branch page they use the Finish button to end the survey.

**Generator behaviour:** In `_build_surveys()`, when a terminal branch page is being processed, it is connected to the next sibling branch page in page-list order. The last branch page gets `connector = None`.

**Note on `thank_you_page`:** This is a virtual Salesforce construct — it cannot be used as a `<targetReference>` in a connector. Attempting to do so produces a deploy error: `Invalid element reference thank_you_page not found for target`.

---

## 24. Branching Surveys — Test Matrix

All 14 surveys below have multi-page branching. Open each from a Call record in the LSC iPad app (after device sync), select a choice on Page 1, and verify the correct branch page appears.

| Survey display name | Pages | Questions | Router question (Veeva NAME) | Branching complexity |
|---|---|---|---|---|
| ITA_Vaccine_Segmentation_HSP_24 | 5 | 6 | SQ00033840 | 4 answer branches, all terminal — hardest to test; good smoke test for defaultConnector fix |
| ITA_Vaccine_Segmentation_NAM_24 | 5 | 6 | SQ00033838 | 4 answer branches, all terminal |
| Survey HCP ATTR-CM/Vyndaqel | 4 | 14 | SQ00034519 | 3 answer branches, most questions per branch |
| Profilazione HCP Lorviqua | 4 | 5 | SQ00034350 | 3 answer branches |
| Elrexfio dicembre 2025 | 3 | 6 | SQ00038821 | 2 answer branches |
| Gastro Attitudinal Segmentation 2025 | 3 | 4 | SQ00035748 | 2 answer branches |
| IBRANCE Survey | 2 | 55 | SQ00036536, SQ00036539, SQ00036542 | 3 independent routers; highest question count |
| ISF Ginecologo - Abrysvo | 2 | 6 | SQ00040468 | 1 branch |
| Cibinqo Attitudinal Segmentation 2025 | 2 | 4 | SQ00035744 | 1 branch |
| ISF GP - Paxlovid | 2 | 4 | SQ00040474 | 1 branch |
| IT_Survey_Eliquis | 2 | 4 | SQ00034026 | 1 branch |
| Vyndaqel Attitudinal | 2 | 4 | SQ00038301 | 1 branch |
| GP_Survey_Paxlovid | 2 | 3 | SQ00035272 | 1 branch |
| GPs_Survey_No_Promo_ATTR-CM | 2 | 3 | SQ00035279 | 1 branch |

**Priority test order:** Start with ITA_Vaccine_Segmentation_HSP_24 (most complex, most likely to surface runtime issues). Then Survey HCP ATTR-CM/Vyndaqel (most questions per branch, good regression coverage). If those pass, remaining surveys are lower-risk.

**Note:** The survey display name (searchable in Salesforce) differs from the Flow API/developer name. Use the display name column above when looking up surveys in the LSC app or Survey Builder.
