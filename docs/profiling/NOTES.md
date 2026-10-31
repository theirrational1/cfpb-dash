# Profile notes (CLEANER Audit)

Hand-written observations from the generated reports in this folder. Snapshot: bulk `complaints_2026-10-31.csv.zip` plus the 21 narrative archive files.

## M0-08 Bulk overview ([01_overview.md](01_overview.md))

- **18,823,456 complaints**, `Complaint ID` unique, integer and never null. Every date parses; received dates run from 2011-12-01 to 2026-10-30.
- **Volume is recent-heavy:** 2024–2026 hold 76% of all rows (2025: 5.4M, 2026 YTD: 6.1M).
- **The three credit bureaus are 78.8% of complaints** (TransUnion 27.7%, Equifax 26.6%, Experian 24.6%). The two credit-reporting product labels together are 81.5%. Every company-level comparison is dwarfed by them, so peer groups must be per product.
- **7,050 complaints were "sent to company" one day before they were received**, always exactly −1 day (probably a timezone artifact). `forwarding_lag_days` must decide how to treat −1 (→ nulls.md / M2-08).
- **`Sub-product` nulls are structural:** they're 100% null in the old `Credit reporting` and `Payday loan` products, and 89K of 357K in the old `Credit card` product, none of which had sub-products at the time.
- **`Company public response` is 44.8% null.** It's probably a meaningful blank (the company chose no public response), but this needs a decision in M0-14.
- **`Tags` has three values, one of them combined:** `Older American, Servicemember` (60K). The field is multi-valued and needs splitting in staging; 95.6% of rows are null.
- **ZIP codes:** 93.2% are 5 digits, 6.0% are masked to 3 digits + `XX`, 139K are fully masked as `XXXXX`, and about 100 are malformed (`3008-`, `89!01`).
- **`State`** has 63 values, including `UNITED STATES MINOR OUTLYING ISLANDS` (1,584) and military codes (`AA`); 0.34% are null.
- **`Company`** has 8,198 distinct names, or 8,191 after upper-casing and trimming. 24 rows have leading or trailing whitespace. Real name resolution is M2-07.
- Rare nulls: `Issue` (6) and `Company response to consumer` (21).

## M0-09 Company response ([02_company_response.md](02_company_response.md))

- **There are three value regimes:**
  - 2011–2012: `Closed with relief` / `Closed without relief`.
  - 2011–2017: bare `Closed` (17.6K).
  - From 2012: `Closed with explanation` / `with non-monetary relief` / `with monetary relief`.

  `relief_rate` needs an explicit mapping for the old values (`Closed with relief` → relief; `Closed without relief` and `Closed` → no relief, or excluded). That's a metric decision, so I'll ask in M3-01.
- **`In progress` is 623K rows, almost all from 2026 (622,907).** Those complaints are open, so they must be excluded from the closed-complaint denominator. `Untimely response` (35.7K) is also not closed.
- **Non-monetary relief jumps** from about 44K a year (2021) to 261K (2022) and then 2.2M (2025), driven by the credit bureaus. Peer comparisons must be within product.
- **`Company public response` nulls are partly structural.** The field effectively starts in 2015, so 2011–2014 is 100% null. `Company chooses not to provide a public response` (2014–2016) was replaced by `Company has responded to the consumer and the CFPB and chooses not to provide a public response` (2016 onward), and the two should be mapped together.

## M0-10 Labels over time ([03_labels.md](03_labels.md))

- **Two product taxonomy revisions:** **April 2017** (e.g. `Credit card` → `Credit card or prepaid card`, `Bank account or service` → `Checking or savings account`) and **August 2023** (`Credit card or prepaid card` → `Credit card` again, `Credit reporting, credit repair services, …` → `Credit reporting or other personal consumer reports`, the payday-loan label renamed again). The credit card switch-back happened between 2023-08-17 and 2023-08-25.
- 21 product labels map to roughly 11 current products. Sub-products and issues churn even more: 296 product×sub-product/issue rows are retired and 196 introduced. The M2-06 mapping seed must cover both 2017 and 2023.
- `Virtual currency` (18 rows) and `Other financial service` (1,056) are tiny retired products.

## M0-11 Narratives ([04_narratives.md](04_narratives.md))

- **3,851,415 complaints have a narrative**, out of 17.5M archive rows (no complaint ID repeats across archive files). 33 narrative IDs no longer exist in the bulk file.
- Credit reporting dominates here too: the two credit-reporting labels hold 2.48M narratives (64%).
- **The exact-duplicate rate after normalisation is 47.5% overall**, a lower bound against the published 57.6% (near-duplicates are M6-01). It's concentrated in credit reporting (74.7% for the current label) and debt collection (20.5%).
- **Credit card narratives are mostly original:** 9.3% duplicates under `Credit card` and 5.9% under `Credit card or prepaid card`. Mortgage is 0.4%, checking/savings 2.9%.
- Credit card narratives by label: `Credit card` 129,144 plus `Credit card or prepaid card` 108,683, so about **238K** across both labels before the cutoff and mapping.

## M0-15 Narrative coverage ([05_coverage.md](05_coverage.md))

- Narratives start in **2015** (the consent-to-publish rollout); 2011–2014 have 0% coverage, which is structural.
- **The overall decline in 2024–2026 is mostly credit reporting.** Its coverage falls from about 34% (2023) to 11% (2025-Q4) and 0.1% (2026). Other products hold about 40–60% through 2026-Q2.
- **For credit cards (current label), monthly coverage is 38–53% from 2025-09 to 2026-06**, with one dip (2026-02: 26.8%), then 22.4% in 2026-07 and **0% from 2026-08**. That's a hard publication cut, not a gradual lag.
- The PRD's "Mar 2026: 3.5%" is the all-products figure. Per product, the cutoff differs a lot.
