# security-master

[![PyPI](https://img.shields.io/pypi/v/security-master)](https://pypi.org/project/security-master/)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fzhuy9%2Fsecurity-master%2Fmain%2Fpyproject.toml)](https://pypi.org/project/security-master/)
[![Data updated](https://img.shields.io/github/last-commit/zhuy9/security-master/main?path=data&label=data%20updated)](https://github.com/zhuy9/security-master/commits/main/data)
[![License](https://img.shields.io/badge/license-MIT%20code%2C%20CC0%20data-blue)](https://github.com/zhuy9/security-master#license)

Reference data for US exchange-listed stocks, ETFs and closed-end funds: about 12,000 securities
(roughly 5,000 common stocks, 6,000 ETFs and ETNs, plus ADRs, REITs, closed-end funds and MLPs)
and 6,300 issuers. Each security is keyed by its FIGI and joined to its issuer's SEC CIK, SIC
industry code and a sector. Rebuilt every weekday from SEC EDGAR and OpenFIGI, and published as two
CSV files plus a small Python client that caches them. Code is MIT. This project's data contributions
are CC0; OpenFIGI data carries the FIGI MIT notice. Both data notices are in `data/LICENSE`.

## Use it

### Python package

```sh
pip install security-master
pip install "security-master[pandas]"   # for frame()
```

To install from this checkout, run `pip install .`.

```python
import security_master as sm

sm.security("BRK.B")          # by ticker, in any form: BRK.B, BRK/B, BRK B, BRK-B
sm.security("BBG000DWG505")   # by composite FIGI
sm.issuer(1067983)            # by SEC CIK, with or without leading zeros
sm.securities()               # every active row as dicts; securities(active_only=False) for all
sm.frame()                    # pandas DataFrame of securities joined to issuers
sm.meta()                     # build date, counts, and the commit the data comes from
```

`sm.security()` and `sm.issuer()` return one row as a dict, or `None` if nothing matches. Every
value is a string, and an empty string means unknown or not applicable. [Files](#files) explains
each field. For BRK.B:

```python
>>> sm.security("BRK.B")
{'composite_figi': 'BBG000DWG505',
 'share_class_figi': 'BBG001S90346',
 'ticker': 'BRK-B',
 'figi_ticker': 'BRK/B',
 'name': 'BERKSHIRE HATHAWAY INC-CL B',
 'security_type': 'Common Stock',
 'exchange': 'NYSE',
 'cik': '0001067983',
 'series_id': '',
 'class_id': '',
 'sector': 'Financials',
 'status': 'active',
 'first_seen': '2026-10-19',
 'last_seen': ''}
>>> sm.issuer("0001067983")
{'cik': '0001067983',
 'name': 'BERKSHIRE HATHAWAY INC',
 'entity_type': 'operating',
 'sic': '6331',
 'sic_description': 'Fire, Marine & Casualty Insurance',
 'state_of_incorporation': 'DE',
 'fiscal_year_end': '1231',
 'country': 'United States'}
```

Python 3.10+, standard library only. The first call downloads the data (about 2 MB) and caches it in memory and
in a local cache directory (below), so later calls and other processes are offline lookups. Once
the copy is an hour old, the next call asks GitHub which commit `main` is at (a small request)
and, if a new build landed, downloads the files at that commit and swaps them in whole: a
long-running service picks up each weekday's build within the hour without restarting. A row you
already got back never changes. If GitHub is unreachable, the copy in hand keeps serving; if the
cache directory isn't writable, or there is no home directory, it runs from memory.

| Variable | Default | |
| --- | --- | --- |
| `SECURITY_MASTER_TTL` | `3600` | Seconds between checks for a new build. `sm.refresh()` checks now, and raises if it can't. |
| `SECURITY_MASTER_REF` | | A commit or tag to pin: reproducible results, never refreshes. `sm.meta()["commit"]` gives the current one. |
| `SECURITY_MASTER_CACHE` | `$XDG_CACHE_HOME/security-master`, else `~/.cache/security-master` | Cache directory |

The version pins the client code, not the data. The weekday data job can keep updating the CSV
files without a new package release. Use `SECURITY_MASTER_REF` to pin the data too.
To get a newer client release, run `pip install --upgrade security-master`, or with uv,
`uv lock --upgrade-package security-master`. Update any version pin in your project's requirements too.

### Any language: the CSV files

```python
import pandas as pd

BASE = "https://raw.githubusercontent.com/zhuy9/security-master/main/data"
securities = pd.read_csv(f"{BASE}/securities.csv", dtype=str, keep_default_na=False)
issuers = pd.read_csv(f"{BASE}/issuers.csv", dtype=str, keep_default_na=False)
```

`dtype=str` keeps the leading zeros in `cik`. From TypeScript or a browser, `fetch` the same URL
(it allows cross-origin requests) and parse it with any CSV library (names contain commas and
quotes). To pin a commit, use jsDelivr:
`https://cdn.jsdelivr.net/gh/zhuy9/security-master@<commit>/data/securities.csv`. For offline
prototyping, copy `data/` into your project; keep `data/LICENSE` with it.

## Lookups

- **By ticker:** `ticker` is in SEC form (`BRK-B`). Turn `BRK.B`, `BRK/B` or `BRK B` into it by
  replacing `.`, `/` and spaces with `-` (`sm.security` does this for you). Filter on `status == "active"`: a delisted row keeps its
  old ticker, which another company may have taken since.
- **By FIGI:** `composite_figi` is the US composite FIGI. It survives ticker changes, so it is
  the key to store.
- **By CIK:** `cik` joins `securities.csv` to `issuers.csv`. One issuer can have several
  securities (share classes, an ETF trust's funds).
- **By CUSIP:** not here; CUSIPs can't be redistributed (see `docs/DATA_SOURCES.md`). Map CUSIP to
  FIGI with OpenFIGI's `/v3/mapping` in your own project, then look up the FIGI.

## Files

`data/securities.csv`, one row per security, sorted by `composite_figi`:

| Column | Meaning |
| --- | --- |
| `composite_figi` | US composite FIGI. The key. |
| `share_class_figi` | Global share-class FIGI |
| `ticker` | SEC form, e.g. `BRK-B` |
| `figi_ticker` | OpenFIGI form, e.g. `BRK/B` |
| `name` | OpenFIGI's name (upper case, abbreviated). `issuers.csv` has the legal name. |
| `security_type` | OpenFIGI type: `Common Stock`, `ETP`, `ADR`, `REIT`, `Closed-End Fund`, `MLP`, `Ltd Part`, `NY Reg Shrs`, `Royalty Trst`, `Tracking Stk`. ETFs and ETNs are `ETP`. |
| `exchange` | SEC's listing label: `Nasdaq`, `NYSE` (which includes NYSE American and NYSE Arca), `CBOE`, `TXSE`. Blank where SEC doesn't say, which is most ETFs. |
| `cik` | Issuer's SEC CIK, 10 digits. For a fund, its trust's CIK. Blank if SEC has no match. |
| `series_id`, `class_id` | SEC series and class of a 1940-Act fund |
| `sector` | This project's sector from the issuer's SIC code (below). Blank for funds, and for the few issuers without a SIC (mostly business development companies). |
| `status` | `active`, or `delisted` once it drops out. Rows are never deleted. |
| `first_seen` | First build that listed it. The dataset starts 2026-10-19, so this is not a listing date. |
| `last_seen` | For delisted rows, the last build that listed it. Blank while active. |

`data/issuers.csv`, one row per CIK, from SEC submissions: `cik`, `name` (SEC conformed name),
`entity_type`, `sic`, `sic_description`, `state_of_incorporation`, `fiscal_year_end` (MMDD),
`country` (business address). `state_of_incorporation` is SEC's label: a two-letter code for a US
state, otherwise a country or province such as `Ireland`, `Ontario, Canada` or
`Canada (Federal Level)`; often blank for foreign issuers.

`data/meta.json`: build date, sector scheme, the SEC files' `Last-Modified`, and row counts.

History is git: every build that changed the data is one commit, so `git log -p data/securities.csv`
shows listings, delistings and renames day by day.

## Caveats

- `sector` is this project's mapping of SEC SIC codes to 11 sectors plus `Other` (`src/sectors.py`),
  not GICS or any vendor scheme. SIC is coarse: Alphabet and Meta file under 7370 (here
  Communication), Visa and Mastercard under 7389 (Financials), and Accenture and Akamai under
  7389 too, where Financials is wrong for them. `sic` is in `issuers.csv` if you want your own
  mapping.
- In scope: common stock, ADRs, REITs, MLPs and partnerships, closed-end funds, ETFs and ETNs
  listed on a US exchange. Out: preferreds, warrants, units, rights, notes, OTC, mutual funds.
- Stocks and closed-end funds are the tickers SEC lists on a US exchange that OpenFIGI types as
  in scope. So a brand-new ticker appears once both have it, and the few banks that file with
  bank regulators instead of the SEC (TowneBank, for one) are missing. ETFs and ETNs come from
  OpenFIGI's NYSE Arca listing, because SEC's files miss about 1 in 6 of them. OpenFIGI also keeps
  some matured, liquidated and announced-but-never-launched funds there, so a minority of active
  ETPs, mostly ones without a CIK, don't trade (about 15% of the CIK-less ones in the first build).
- `cik` and `exchange` are joined by ticker from SEC's files, which can lag: a delisting or a move
  to OTC by weeks or months, and a reused ticker, so a fund that took over a retired ticker can
  carry the previous holder's CIK for a while.

## Build it

```sh
cp .env.example .env   # then fill in EDGAR_IDENTITY and OPENFIGI_API_KEY
python tests/test_build.py && python tests/test_client.py
python src/build.py    # --full refetches every issuer
```

Python 3.10+, standard library only. `src/build.py` reads `.env`; variables already set in the
environment win. SEC requires `EDGAR_IDENTITY` as the User-Agent. The
OpenFIGI key is free and optional, but without it a daily build takes about 50 minutes instead of
about 6. The first build (and every `--full` one) makes about 6,300 SEC requests at up to 8 a
second; later builds fetch only new issuers. A build refuses to write anything if active rows
fall more than 5%, a ticker is on two active rows, or any identifier looks like a CUSIP or ISIN.
If SEC's CDN hands it older ticker files than the last build used, it keeps the last build and
passes with a warning, failing only once the data is more than 4 days old.

Layout: `src/build.py` builds the data (with `src/sectors.py`, the SIC-to-sector table);
`src/security_master/` is the Python client, the only thing the package ships; `tests/` checks both
without network; `docs/DATA_SOURCES.md` records each source's terms.

`.github/workflows/refresh.yml` runs it every weekday at 15:17 UTC, refetches every issuer on
Mondays, and commits `data/` when it changed. It needs the repository secrets `EDGAR_IDENTITY`
and `OPENFIGI_API_KEY`.

## Publish a release

Release the Python client when its code changes. The daily data refresh does not need a release.
The package downloads its data from GitHub; the CSV files are not bundled in the package.

1. Set `version` in `pyproject.toml` to one not yet on PyPI, which does not let you replace an
   uploaded file. Run these checks from the repository root, using an empty `dist/` directory so
   old release files cannot get mixed in:

   ```sh
   python -m pip install build==1.6.1 twine==7.0.0 ruff==0.17.1
   ruff check .
   python tests/test_build.py
   python tests/test_client.py
   python -m build
   python -m twine check --strict dist/*
   python tests/test_package.py
   ```

2. Commit the changes and push them to `main` when you are ready.
3. To check the workflow before publishing, open **Actions > release > Run workflow** on GitHub.
   This runs the tests and builds the package. It does not upload to PyPI.
4. Open **Releases > Draft a new release**. Create the tag `v` plus that version, such as
   `v0.1.0`, from `main`, then click **Publish release**. This starts
   `.github/workflows/release.yml` and uploads the package to PyPI after its checks pass.
5. Wait for the `release` workflow to finish, then check the
   [PyPI project page](https://pypi.org/project/security-master/) and run
   `pip install security-master==<version>`.

## License

Code: MIT (`LICENSE`). This project's data contributions: CC0 1.0. OpenFIGI identifiers and metadata
carry the FIGI MIT notice. Sources and their terms: `docs/DATA_SOURCES.md`.

Keep [data/LICENSE](https://github.com/zhuy9/security-master/blob/main/data/LICENSE) with any
redistributed CSV files, caches, or exports. Both code and data notices are included in the Python
package's license files.

Not affiliated with or endorsed by the SEC, Bloomberg, or any exchange. Provided as is, with no
warranty. Not investment advice.
