# Sector review queue

These are **unapproved candidates**, not additional overrides. The four approved exceptions
are Accenture, Akamai, Uber and Alibaba; their policy and evidence belong in the sector ADR.
Do not change a candidate's published classification until its proposed CIK-specific change
and evidence have been reviewed and approved.

Current CIKs, SICs and sectors below come from the frozen input snapshot
[`271cb9033bb56a284c161da74047e4f6a56d1258`](https://github.com/zhuy9/security-master/commit/271cb9033bb56a284c161da74047e4f6a56d1258),
built on 2026-11-05. Candidate sectors are review hypotheses inferred from business activities;
they are not verified vendor classifications. A difference from GICS alone is not an error:
this project defines its own sector policy.

The list groups mapping concerns; it is not a ranking by holdings value. Prioritize using a
pinned 13f-dashboard holdings snapshot and named reporting quarter, then aggregate positions
by issuer CIK across share classes. Do not infer dollar impact from security counts or market
prominence. SIC 7389 has 104 stored issuers, 103 active issuers and 104 active securities in
the snapshot; SIC 7370 has 79 active issuers and 80 active securities.

| Label | CIK | SIC | Current sector | Candidate sector | Evidence needed before proposing a change |
|---|---|---|---|---|---|
| MELI | `0001099590` | 7389 | Financials | Consumer Discretionary | Commerce versus payments segment revenue and stated principal business |
| PDD | `0001737806` | 7389 | Financials | Consumer Discretionary | Commerce platform business description and segment revenue |
| EBAY | `0001065088` | 7389 | Financials | Consumer Discretionary | Marketplace business description and revenue sources |
| ETSY | `0001370637` | 7389 | Financials | Consumer Discretionary | Marketplace business description and revenue sources |
| LYFT | `0001759509` | 7389 | Financials | Industrials | Transportation activities under the same policy used for Uber |
| DASH | `0001792789` | 7389 | Financials | Consumer Discretionary or Industrials | Delivery versus marketplace policy and current segment disclosures |
| CSGP | `0001057352` | 7389 | Financials | Real Estate or Technology | Real estate services versus software/data policy and revenue composition |
| RELX | `0000929869` | 7389 | Financials | Industrials | Analytics, information services and exhibitions segment mix |
| FICO | `0000814547` | 7389 | Financials | Technology | Software versus financial information policy and segment revenue |
| ZM | `0001585521` | 7370 | Communication | Technology | Enterprise communications software business description |
| WIX | `0001576789` | 7370 | Communication | Technology | Website software business description and revenue sources |
| DOCN | `0001582961` | 7370 | Communication | Technology | Cloud infrastructure services business description |
| NBIS | `0001513845` | 7370 | Communication | Technology | Current post-restructuring business and principal revenue sources |
| FDS | `0001013237` | 7370 | Communication | Financials | Financial information policy and data/services revenue sources |
| TMO | `0000097745` | 3829 | Technology | Health Care | Life-science instruments and diagnostics segment composition |
| ROK | `0001024478` | 3829 | Technology | Industrials | Industrial automation activities and revenue sources |
| MATX | `0000003453` | 4400 | Consumer Discretionary | Industrials | Freight transportation activities, distinct from cruise operators |
| KEX | `0000056047` | 4400 | Consumer Discretionary | Industrials | Freight transportation and distribution segment composition |
| XPO | `0001166003` | 4700 | Consumer Discretionary | Industrials | Current freight business, distinct from online travel |
| GXO | `0001852244` | 4700 | Consumer Discretionary | Industrials | Contract logistics activities and revenue sources |
| RXO | `0001929561` | 4700 | Consumer Discretionary | Industrials | Freight brokerage and transportation activities |
| GATX | `0000040211` | 4700 | Consumer Discretionary | Industrials | Railcar leasing and related principal business activities |
| NGG | `0001004315` | 4922 | Energy & Mining | Utilities | Regulated electricity/gas utility activities and segment mix |
| NFLX | `0001065280` | 7841 | Consumer Discretionary | Communication | Streaming content activities and consistency with media policy |
| CTVA | `0001755672` | 0100 | Other | Materials | Seed/crop protection mix; policy for agricultural inputs |
| CALM | `0000016160` | 0200 | Other | Consumer Staples | Egg production activities; policy for agricultural food producers |
| DOLE | `0001857475` | 0100 | Other | Consumer Staples | Food production activities; policy for agricultural food producers |

Before approval, record the exact public annual filing or issuer report URL, filing/accession
or report date, a concise business rationale, review date, and reviewer/approval reference.
Use SEC/issuer business facts and independently authored reasoning. Record reuse terms for any
new source in [DATA_SOURCES.md](DATA_SOURCES.md); do not copy a proprietary sector database.
Retain expected SIC in each exception so a later SIC change requires renewed review.

For each proposed batch, show CIK, affected composite FIGIs, old/new sector, source snapshot,
candidate policy version and holdings impact by reporting quarter. Keep ambiguous issuers in
this queue rather than asserting a target in the regression list. Mortgage versus equity
REITs under 6798 and other mixed industry codes also need a stated policy before any change.

The frozen regression list is [tests/fixtures/sector_cases.csv](../tests/fixtures/sector_cases.csv).
It samples accepted policy examples, every four-digit industry exception and the approved CIK
exceptions. It is not an assertion that every company sharing those SICs is correctly classified.
Unknown-SIC `Other` behavior uses synthetic inputs in the offline tests so pending real issuers
are not accidentally treated as approved reference classifications.
