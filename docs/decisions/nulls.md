# Null decisions (draft v0, M0-14)

> **Status: decisions reviewed by Saksham 2026-10-31; not yet enforced.** Each entry becomes a dbt test in M2-05 before the staging model ships. Entries marked **✔ decided** were open questions resolved in review.
>
> Evidence: `docs/profiling/01_overview.md`, `02_company_response.md`, `NOTES.md`. Snapshot `complaints_2026-10-31.csv.zip` (18,823,456 rows).

CLEANER null categories: **meaningful blank** (encode explicitly), **unknown** (keep null; metrics state how they treat it), **structural** (the field didn't exist or apply; keep null, flag the period), **error** (fix in the mapping, or exclude with a counted reason).

## Bulk file: columns that contain nulls

### `sub_product` — 235,275 nulls (1.25%) — **structural**
- **Evidence:** 100% null in products that had no sub-products when filed: `Credit card` before the April 2017 relabel (every credit card complaint 2011–2016), `Credit reporting` (2012–2017), `Payday loan` (2013–2017). From 2018, credit card sub-product is never null.
- **Decision:** keep null. The M2-06 mapping seed lists the (product label, era) pairs that have no sub-product.
- **Test:** `sub_product IS NULL` only for product labels in the seed's "no sub-product" list.

### `issue` — 6 nulls (0.00003%) — **error**
- **Evidence:** six 2024 complaints (five checking/savings, one credit reporting), all closed. Every other complaint has an issue.
- **Decision:** keep the rows for counts. Exclude them from issue-based metrics and report them as a counted "issue missing" exclusion.
- **Test:** null count ≤ 10 (error above, so growth gets noticed).
- **✔ decided:** `issue_share` **excludes** null-issue rows from numerator and denominator, so shares sum to 100%. The 6 rows stay in `complaint_count` and are reported as a counted exclusion.

### `sub_issue` — 946,495 nulls (5.03%) — **structural**
- **Evidence:** whole product/issue combinations have no sub-issues. For example, `Money transfer…` is 100% null and `Credit reporting… / Problem with fraud alerts or security freezes` is 100% null. Mortgage is 81% null.
- **Decision:** keep null. It isn't used by any planned metric, so per CLEANER Limit it may be dropped from the marts.
- **Test:** no not-null test. M2-06 checks the mapping seed's coverage of (product, issue, sub-issue) combinations.

### `company_public_response` — 8,435,956 nulls (44.8%) — **structural before 2015; then meaningful blank or not-yet-available**
- **Evidence:** 100% null 2011–2014 (the option effectively starts in 2015). From 2016, about 41–47% null among closed complaints and 100% null for `In progress` and `Untimely response`. Separately, the explicit value "Company … chooses not to provide a public response" exists, so a null is *not* the same as an explicit opt-out.
- **Decision:**
  - received before 2015-01-01 → structural (null, period flagged);
  - `In progress` → unknown (not yet available; null);
  - closed **or `Untimely response`** from 2015 → meaningful blank, encoded as `'none_given'`. An untimely response is still the company's response and says something about it.
- **Test:** accepted values (the 11 current values plus `'none_given'`); null only when received before 2015 or `In progress`.
- **✔ decided:** a blank on a closed or untimely complaint means "company gave no public response" (`'none_given'`) for `public_response_rate`.

### `state` — 63,583 nulls (0.34%) — **unknown**
- **Evidence:** consumer didn't provide it. It peaks at 2.85% in 2018 and is about 0.1–0.3% from 2022. There are also non-state values: `UNITED STATES MINOR OUTLYING ISLANDS` and military codes (`AA`, `AE`, `AP`).
- **Decision:** keep null. State breakdowns show an "unknown" row with its count, never silently dropped.
- **Test:** accepted values (US states, DC, territories, military codes); null allowed.

### `zip_code` — 3,426 nulls (0.02%), plus 139,165 `XXXXX` and ~100 malformed — **unknown / error**
- **Evidence:** 93.2% are 5 digits, 6.0% are masked to 3 digits + `XX`, 139K are fully masked as `XXXXX`, and about 100 are malformed (`3008-`, `89!01`).
- **✔ decided: dropped at staging (CLEANER Limit).** No planned metric, dimension or filter uses ZIP. It stays in the raw file, so it can be brought back with a revised decision if a consumer appears.
- **Test:** staging column list excludes `zip_code` (schema test on the staging model).

### `tags` — 17,993,831 nulls (95.6%) — **meaningful blank**
- **Evidence:** null means no tag applies. There are three values: `Older American`, `Servicemember`, and the combined `Older American, Servicemember`.
- **Decision:** split into booleans `is_older_american` and `is_servicemember`, where null → `false` (an explicit encoding, not missing).
- **Test:** raw accepted values (the three values, or null); the booleans are not null.

### `company_response` — 21 nulls (0.0001%) — **error**
- **Evidence:** scattered 2018–2024 complaints (credit reporting, debt collection, mortgage); every other complaint has a status.
- **Decision:** exclude from response-based metrics (`relief_rate`, `timely_response_rate` denominators) with a counted "status missing" exclusion; keep them in `complaint_count`.
- **Test:** null count ≤ 25 (error above).

## Bulk file: columns with no nulls (enforce `not_null`)

`complaint_id` (also `unique`, integer), `date_received`, `date_sent_to_company` (both parse as dates), `product`, `company`, `submitted_via`, `timely`. These have zero nulls today, so a null is a source change and fails the build.

- **Related, not a null:** 7,050 complaints have `date_sent_to_company` exactly one day **before** `date_received`. **✔ decided:** `forwarding_lag_days` **keeps −1** as-is. We'll check its effect on the metrics (M3) before deciding anything further; a test pins the count of negative lags so a change is noticed.

## Narrative archive

### `narrative` — empty for 13.7M of 17.5M archive rows — **meaningful blank; structural outside the coverage window**
- **Evidence:** narratives exist only when the consumer consented and CFPB published them. They're 0% before 2015 (structural), and none are used after the cutoff (received on or before 2026-06-30, decided in M0-15).
- **Decision:** `has_narrative` boolean (empty → `false`); the text is never imputed. Narrative metrics and the issue deep-dive are restricted to received ≤ 2026-06-30, and the product shows that boundary.
- **Test:** `has_narrative = (trim(narrative) <> '')`; no narrative-derived row has received > 2026-06-30.
