# ADR 0001: Issuer-specific sector exceptions

Status: Accepted, 2026-11-05. The project maintainer approved the four exceptions
below, their offline CSV update and scheme metadata, then publication after review
of the local changes. A live source refresh and further issuer assignments are
outside this change.

## Context

The 2026-11-05 published snapshot at commit
`271cb9033bb56a284c161da74047e4f6a56d1258` reports 11,930 active securities and
6,281 issuers, using `sic11-v1`. SIC 7389 contains payment businesses alongside
technology, commerce and transportation businesses. Changing its default sector
would move unrelated issuers and replace one known error with others.

These sectors are this project's own scheme: 11 sectors plus `Other`, not GICS or
another vendor's classification. Business evidence informs an original project
decision; it does not establish a universal sector assignment.

## Decision

Keep the existing SIC hierarchy and add `BY_CIK` in `src/sectors.py`, keyed by
10-digit CIK strings. Each value contains the expected SIC and approved sector.
Preserve `sic_to_sector()` for SIC-only callers. Issuer-aware classification uses
the matching CIK exception first, then the existing SIC fallback. An exception
applies only with its expected SIC; a change requires review, not silent reuse.

Funds (`ETP`, `Closed-End Fund`), missing issuers and missing SICs retain blank
sectors. The same eligible issuer receives the exception across its FIGIs,
including retained delisted securities. Neither tickers nor company-name matching
select an exception. Leading zeros remain part of the stored CIK.

The approved exceptions all have expected SIC 7389:

| Issuer | CIK | Before | Approved sector | Original rationale |
| --- | --- | --- | --- | --- |
| Accenture (ACN) | `0001467373` | Financials | Technology | Technology consulting, integration, managed services and platforms fit the project's technology-services policy. |
| Akamai (AKAM) | `0001086222` | Financials | Technology | Cybersecurity, cloud computing and delivery infrastructure fit Technology. |
| Uber (UBER) | `0001543151` | Financials | Industrials | Classify the underlying mobility, delivery and freight activity as transportation; software delivery alone does not determine the sector. |
| Alibaba (BABA) | `0001577552` | Financials | Consumer Discretionary | Commerce is the principal business; a substantial cloud business does not make this issuer a payment-services company. |

Uber's Industrials assignment is an approved project policy choice. It is not a
sector supplied by the SEC. Keep Visa (`0001403161`), Mastercard (`0001141391`)
and PayPal (`0001633917`) in Financials through the unchanged SIC default.

## Evidence and provenance

All four decisions were reviewed on 2026-11-05 against these specific filings:

| Issuer | Document / filing date | Primary evidence |
| --- | --- | --- |
| Accenture | FY2026 10-K, 2026-10-16 | [Item 1, Business](https://www.sec.gov/Archives/edgar/data/1467373/000146737326000049/acn-20260831.htm): technology, consulting, managed services, platforms and software. |
| Akamai | FY2025 10-K, 2026-02-20 | [Item 1, Business](https://www.sec.gov/Archives/edgar/data/1086222/000108622226000022/akam-20251231.htm): security, cloud computing and delivery offerings. |
| Uber | FY2025 10-K, 2026-02-13 | [Item 1, Business](https://www.sec.gov/Archives/edgar/data/1543151/000154315126000015/uber-20251231.htm): mobility, delivery and freight services. |
| Alibaba | FY2026 20-F, 2026-05-20 | [Business and segment reporting](https://www.sec.gov/Archives/edgar/data/1577552/000119312526231755/baba-20260331.htm): China and international commerce alongside cloud services. |

Source permissions and exclusions are recorded in [DATA_SOURCES.md](../DATA_SOURCES.md).
Publish original rationales and source citations, not copied vendor sector lists
or filing text. Do not assume every third-party document hosted by the SEC has
the same reuse permissions. New sources require their terms to be recorded there.
Keep CUSIPs and ISINs out of this repository; private holdings joins stay downstream.

The scheme becomes `sic11-v2`. Its identifier describes classification rules;
the data commit identifies the exact security and issuer snapshot. Both are
needed for reproducibility. Keep source SIC values unchanged. Future exceptions
must record CIK, expected SIC, target, rationale, filing URL/date, review date and
explicit approval, with a new scheme version when published behavior changes.

## Validation and review

Before writing data, reject malformed CIK keys, unknown sector labels, missing
override issuers and unexpected issuer SICs. Preserve the existing row-count,
active-ticker, SEC freshness and restricted-identifier checks.

Use `tests/fixtures/sector_cases.csv` and `tests/test_sectors.py` as the named
instrument coverage list and deterministic regression check. Pin exact approved
sectors, unchanged payment controls, an unrelated 7389 issuer, SIC precedence,
fund exclusions, missing SICs and multiple FIGIs sharing one issuer. Candidates
in [SECTOR_REVIEW.md](../SECTOR_REVIEW.md) are pending review, not active overrides.
Rank that queue by a defined quarter's holdings value without making holdings
availability a condition of a published classification.

Produce the publication proposal offline from the pinned baseline CSVs: apply the
approved rules to every eligible row, active and delisted, and list CIK, FIGI,
ticker, status, SIC, old sector and proposed sector. Confirm only the approved
CIKs change and every other row is unchanged. No SEC or OpenFIGI call is needed.
The local CSV diff is part of the review; do not update source-fetch timestamps.
For example, from the repository root with the new classifier available:

```sh
PYTHONPATH=src python3 - <<'PY'
import copy
import subprocess
import tempfile
from pathlib import Path
from build import apply_sectors, check, read_csv
from sectors import BY_CIK

baseline = "271cb9033bb56a284c161da74047e4f6a56d1258"
with tempfile.TemporaryDirectory() as tmp:
    for name in ("securities.csv", "issuers.csv"):
        Path(tmp, name).write_bytes(subprocess.check_output(
            ["git", "show", f"{baseline}:data/{name}"]))
    old = read_csv(Path(tmp, "securities.csv"), "composite_figi")
    issuers = read_csv(Path(tmp, "issuers.csv"), "cik")
new = copy.deepcopy(old)
apply_sectors(new, issuers)
problems = check(new, issuers, sum(r["status"] == "active" for r in old.values()))
assert not problems, problems
for figi, row in new.items():
    if row != old[figi]:
        assert row["cik"] in BY_CIK
        assert {**old[figi], "sector": row["sector"]} == row
        print(row["cik"], figi, row["ticker"], row["status"],
              issuers[row["cik"]]["sic"], old[figi]["sector"], row["sector"])
PY
```

Review this output and validation results before writing the proposed CSVs with
the existing `write_csv()` helper. No permanent offline-build CLI is required.

## Downstream rollout and limits

In 13f-dashboard, record scheme, source commit and build date on refreshed cache
entries and generated dataset metadata. Detect a scheme change during enrichment;
the version bump alone cannot invalidate an existing Firestore cache. Preserve
unresolved old entries and their original provenance instead of marking them as
successfully refreshed.

Pin `SECURITY_MASTER_REF` for a run. After approval and data publication, refresh
eligible entries and rebuild all retained 12 quarters under one approved scheme,
then publish a complete snapshot atomically. Those histories are restated using
the approved scheme, not point-in-time classifications. Compare sector exposures
and rotation outputs before publication, keeping portfolio totals unchanged.
Reject source snapshot drift during enrichment before cache writes so entries
cannot be labelled with a different source commit than the one used for lookups.

Production holdings impact has not been measured. This decision does not classify
every 7389 issuer, introduce a historical effective-date taxonomy, or redesign the
archive. Every additional issuer assignment requires a visible proposal and
explicit approval.
