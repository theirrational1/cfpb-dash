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
