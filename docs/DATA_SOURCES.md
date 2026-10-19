# Data sources

What each source is used for, what its terms allow, and what is deliberately left out.

A permission recorded here is the result of reading the terms on the date given. It is not legal
advice and does not itself grant a license. Terms change: re-read them before relying on this
file, and before adding a source or a column.

## Summary

| Source | Columns | Published | Terms checked |
| --- | --- | --- | --- |
| OpenFIGI (Bloomberg) | `composite_figi`, `share_class_figi`, `figi_ticker`, `name`, `security_type` | Yes, with the FIGI MIT notice in `data/LICENSE` | 2026-10-19 |
| SEC EDGAR ticker files | `cik`, `exchange`, `series_id`, `class_id` | Yes | 2026-10-19 |
| SEC EDGAR submissions | every column of `issuers.csv` | Yes | 2026-10-19 |
| This project | `ticker` (SEC form), `sector`, `status`, `first_seen`, `last_seen` | Yes, CC0 | — |
| CUSIP, CINS, ISIN | — | Never | 2026-10-19 |
| Nasdaq Trader symbol directory | — | Never | 2026-10-19 |
| GICS, ICB, TRBC, BICS | — | Never | 2026-10-19 |

## OpenFIGI

Used for: each security's FIGIs, OpenFIGI ticker, name and type, and the list of ETPs.

- `POST https://api.openfigi.com/v3/mapping`: every ticker SEC lists on a US exchange, with
  `exchCode: "US"`, for its composite FIGI and type. 25 requests a minute of 10 tickers without
  an API key, 250 of 100 with a free one.
- `POST https://api.openfigi.com/v3/filter`: `securityType: "ETP"` on the NYSE Arca venue line
  (`exchCode: "UP"`), where every US-listed ETP trades. 5 requests a minute without a key, 20
  with one.

Measured 2026-10-19: OpenFIGI keeps venue lines for securities long after they delist or move to
OTC (586 stock lines on Arca had no SEC listing, some delisted years ago), so SEC, not OpenFIGI,
decides whether a stock is listed. ETPs have no complete SEC list, so OpenFIGI decides, and some
closed funds stay active.

Terms: <https://www.openfigi.com/docs/terms-of-service>, "Last Updated: November 27, 2018".

- Section 1: Bloomberg "hereby dedicates FIGI Identifiers to the public domain"; they "may be
  freely reproduced, distributed, transmitted, used, modified, built upon, or otherwise exploited
  by anyone for any purpose, commercial or non-commercial".
- Section 5: "under no circumstance shall Bloomberg terminate, modify or repudiate the license
  grant in paragraph 1".
- Section 4: no trademark license. The FIGI and OPENFIGI marks are used here only to say where
  the data comes from, with no implied endorsement.

The descriptive fields are covered by the FIGI specification 1.3 (September 2026), Annex D.6:
FIGI and its associated metadata "are freely redistributable, can be used, transmitted,
databased, stored, enriched or otherwise utilized without restrictions aside from ensuring that
the MIT Open Source permissions are included and disclosed". That notice is at the end of
`data/LICENSE`, next to the CSVs, so a copy of the data directory carries it.

## SEC EDGAR

Used for: CIK, listing exchange and fund series/class (ticker files), and every issuer field
(submissions).

- `https://www.sec.gov/files/company_tickers_exchange.json`: cik, name, ticker, exchange
- `https://www.sec.gov/files/company_tickers_mf.json`: cik, seriesId, classId, symbol
- `https://data.sec.gov/submissions/CIK##########.json`: one issuer

Terms: <https://www.sec.gov/about/privacy-information>, "Website Dissemination": "Information
presented on sec.gov is considered public information and may be copied or further distributed
by users of the web site without the SEC's permission. Please consider appropriate citation to
the SEC as the source." Source: U.S. Securities and Exchange Commission, EDGAR.

The same page says "SEC" and "EDGAR" are SEC registered trademarks that may not be used "in a
trade name, trademark, or domain name of an SEC- or EDGAR-related business without a license
from the SEC". So this project is named after neither, and is not affiliated with or approved by
the SEC.

Fair access (<https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data>):
at most 10 requests a second across all machines, with a declared User-Agent of the form
`Name email`. `src/build.py` stays under 8 a second and sends `EDGAR_IDENTITY` as the User-Agent.

Measured 2026-10-19, and handled in `src/build.py`:

- SEC's CDN serves stale copies of its ticker files: a day-old `company_tickers_exchange.json` to
  the plain URL here, and a 4-day-old one to a GitHub Actions runner even with a cache-buster.
  The build compares each file's `Last-Modified` with the last build's; if SEC hands it an older
  file, it keeps the last build instead of rolling the data back, and only fails once the data is
  more than 4 days old.
- `company_tickers_exchange.json` lists only about 200 of the roughly 5,800 US-listed ETFs (unit
  and grantor trusts such as SPY and GLD). 1940-Act ETFs such as IVV and QQQ are only in
  `company_tickers_mf.json`, and about 1,000 are in neither. That is why ETPs come from OpenFIGI
  and are joined to SEC where SEC has them.

## Sector

`sector` is this project's own mapping of SEC SIC codes to 11 sectors plus "Other" (`src/sectors.py`;
`sector_scheme` in `meta.json`). It is not GICS or any other vendor classification. Funds
(`ETP`, `Closed-End Fund`) get no sector: a fund files under its trust's or sponsor's SIC (gold
and bitcoin trusts file under 6221, commodity contracts brokers), which says nothing about what
it holds.

## Not used, and why

- **CUSIP, CINS and ISIN.** CUSIP Global Services licenses them for the American Bankers
  Association, which owns the CUSIP system. Its terms at
  <https://www.cusip.com/services/license-fees.html> require a license even below the
  500-identifier fee waiver, and say use is not intended to create "a master file or database of
  CUSIP descriptions or numbers". The SEC's own Official List of Section 13(f) Securities is
  marked "No redistribution without permission of CGS". A US ISIN contains the CUSIP. No column
  holds them, no step fetches them, and `src/build.py` refuses to publish any value shaped like one.
  A project that holds CUSIPs should map them to FIGIs itself (OpenFIGI `/v3/mapping`) and look
  the FIGI up here.
- **Nasdaq Trader symbol directory** (`nasdaqlisted.txt`, `otherlisted.txt`). The site terms at
  <https://www.nasdaqtrader.com/Trader.aspx?id=CopyDisclaimMain> forbid content being copied,
  distributed or "stored for subsequent use" without Nasdaq's written consent, apart from
  personal non-commercial use, and say "Nasdaq stock symbols are proprietary to Nasdaq, Inc."
  Not used anywhere, CI included. The tickers published here, Nasdaq-listed ones included, come
  from OpenFIGI rows selected by SEC's ticker files, both redistributable as above, never from
  Nasdaq's sites.
- **GICS, ICB, TRBC, BICS**, and lists that reproduce them (such as Wikipedia's S&P 500 table).
  Proprietary classifications. The April 2026 GICS methodology notice forbids using the
  information to redistribute it, in materials for public dissemination, to create data
  products, or to populate a database, without MSCI's written permission. "Global Industry
  Classification Standard (GICS)" is a service mark of MSCI and S&P Dow Jones Indices.
- **Yahoo Finance, Massive (formerly Polygon), Alpaca, Tiingo, EODHD, Databento, sec-api.io**, and
  datasets built from them (FinanceDatabase, Kaggle uploads). Their terms forbid redistribution,
  or the data was scraped.
- **Prices, market cap, index membership, logos, business descriptions.** Not reference data any
  source above clears for redistribution.
