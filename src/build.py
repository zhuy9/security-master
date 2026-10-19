"""Build data/securities.csv and data/issuers.csv: US exchange-listed stocks, ETFs and closed-end
funds keyed by composite FIGI, with issuer fields and a sector from SEC EDGAR.

    EDGAR_IDENTITY="Name email" [OPENFIGI_API_KEY=...] python src/build.py [--full]

Universe, in two halves:
- Stocks and closed-end funds: every ticker SEC lists on a US exchange, mapped through OpenFIGI
  /v3/mapping to its US composite FIGI and type. SEC's list is what says a security is still
  listed; OpenFIGI keeps lines for long-dead and OTC securities.
- ETFs and ETNs: OpenFIGI /v3/filter for type ETP on the NYSE Arca venue line, which carries
  every US-listed ETP (and keeps some that have since closed). About 1 in 6 are in neither of
  SEC's ticker files, so SEC can't be the list here.
CIK and listing exchange come from SEC's ticker files, issuer fields from SEC submissions.

Only fields these sources allow to be redistributed are published -- see docs/DATA_SOURCES.md. No
CUSIP, ISIN, Nasdaq symbol-directory or GICS data, ever.
"""

import argparse
import csv
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from sectors import sic_to_sector

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MAPPING_URL = "https://api.openfigi.com/v3/mapping"
FILTER_URL = "https://api.openfigi.com/v3/filter"
SEC_FILES = {
    "exchange": "https://www.sec.gov/files/company_tickers_exchange.json",
    "mf": "https://www.sec.gov/files/company_tickers_mf.json",
}
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{}.json"
EQUITY_TYPES = ("Common Stock", "REIT", "ADR", "MLP", "Tracking Stk", "NY Reg Shrs", "Royalty Trst", "Ltd Part")
FUND_TYPES = ("ETP", "Closed-End Fund")  # no sector: a fund sponsor's SIC says nothing about its holdings
LISTED = {"Nasdaq", "NYSE", "CBOE", "TXSE"}  # SEC's exchange labels; "OTC" and blank are not listings
DEAD_TICKER = re.compile(r"[0-9]+[A-Z]")  # Bloomberg renames a delisted line's ticker like this: 2663476D
SECURITY_COLS = [
    "composite_figi", "share_class_figi", "ticker", "figi_ticker", "name", "security_type", "exchange",
    "cik", "series_id", "class_id", "sector", "status", "first_seen", "last_seen",
]  # fmt: skip
ISSUER_COLS = [
    "cik", "name", "entity_type", "sic", "sic_description", "state_of_incorporation", "fiscal_year_end", "country",
]  # fmt: skip
# CUSIP/CINS (9 chars, check digit last) or US ISIN. CUSIP Global Services forbids redistributing
# them, so one reaching a published file is a bug, whatever column it hides in. Free-text columns
# are skipped: fund names are full of 9-character words like MIDCAP400.
FORBIDDEN = re.compile(r"\b(?:[0-9A-Z]{8}[0-9]|US[0-9A-Z]{9}[0-9])\b")
FREE_TEXT = {"name", "sic_description"}


def fetch(url: str, headers: dict, body: dict | None = None) -> tuple[dict | None, dict]:
    """JSON from a GET, or a POST of `body`; retries 429/5xx; (None, headers) on a 404."""
    data = None if body is None else json.dumps(body).encode()
    if data:
        headers = {**headers, "Content-Type": "application/json"}
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=60) as resp:
                return json.load(resp), resp.headers
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, e.headers
            if e.code == 403 and "sec.gov" in url:
                sys.exit("SEC refused the request (403). EDGAR_IDENTITY must be a plain 'Name email' it accepts.")
            if e.code not in (429, 500, 502, 503, 504) or attempt == 5:
                raise
            wait = e.headers.get("Retry-After") or e.headers.get("ratelimit-reset") or ""
            time.sleep(int(wait) if wait.isdigit() else 2 ** (attempt + 2))
        except (OSError, http.client.HTTPException):  # resets, timeouts, truncated bodies
            if attempt == 5:
                raise
            time.sleep(2 ** (attempt + 2))
    raise AssertionError("unreachable")


def sec_table(name: str, identity: str, prev_meta: dict) -> tuple[list[dict], str]:
    """One of SEC's ticker files as rows, refusing a copy older than the one the last build used."""
    # The cache-buster matters: SEC's CDN has been seen serving a day-old copy to the plain URL.
    body, headers = fetch(f"{SEC_FILES[name]}?t={int(time.time())}", {"User-Agent": identity})
    modified, seen = headers["Last-Modified"], prev_meta.get("sec_last_modified", {}).get(name)
    if seen and parsedate_to_datetime(modified) < parsedate_to_datetime(seen):
        sys.exit(f"SEC served a stale {name} file: {modified}, older than the last build's {seen}")
    return [dict(zip(body["fields"], row)) for row in body["data"]], modified


def openfigi_headers(api_key: str | None) -> dict:
    return {"X-OPENFIGI-APIKEY": api_key} if api_key else {}


def openfigi_listed(tickers: list[str], api_key: str | None) -> dict[str, dict]:
    """compositeFIGI -> OpenFIGI's US composite row, for the SEC-listed tickers it types as in scope.
    Preferreds, warrants, units, rights and notes come back with other types and drop out here."""
    size, per_minute = (100, 250) if api_key else (10, 25)  # /mapping: jobs per request, requests a minute
    rows: dict[str, dict] = {}
    for i in range(0, len(tickers), size):
        batch = tickers[i : i + size]
        jobs = [{"idType": "TICKER", "idValue": t.replace("-", "/"), "exchCode": "US"} for t in batch]
        results, _ = fetch(MAPPING_URL, openfigi_headers(api_key), jobs)
        time.sleep(60 / per_minute + 0.05)
        for result in results:
            match = next((d for d in result.get("data", []) if d.get("securityType") in EQUITY_TYPES + FUND_TYPES), None)
            if match and match.get("compositeFIGI"):
                rows.setdefault(match["compositeFIGI"], match)
    print(f"  openfigi: {len(rows)} of {len(tickers)} SEC-listed tickers in scope", flush=True)
    return rows


def openfigi_etps(api_key: str | None) -> dict[str, dict]:
    """compositeFIGI -> OpenFIGI row, for every ETP on the NYSE Arca venue line."""
    pause = 60 / (20 if api_key else 5) + 0.1  # /filter allows 20 requests a minute with a key, 5 without
    body: dict = {"exchCode": "UP", "securityType": "ETP"}
    rows: dict[str, dict] = {}
    while True:
        page, _ = fetch(FILTER_URL, openfigi_headers(api_key), body)
        time.sleep(pause)
        if "error" in page:
            sys.exit(f"OpenFIGI filter: {page['error']}")
        if page.get("total", 0) >= 15_000:  # /filter stops there; split the query if this ever trips
            sys.exit(f"OpenFIGI filter: {page['total']} ETPs reaches the 15,000-result cap")
        for row in page["data"]:
            if usable_etp(row):
                rows.setdefault(row["compositeFIGI"], row)
        if not page.get("next"):
            break
        body["start"] = page["next"]
    print(f"  openfigi: {len(rows)} ETPs", flush=True)
    return rows


def usable_etp(row: dict) -> bool:
    """Drops Arca ETP lines that can't be a fund: no composite or ticker, a dead-renamed ticker, or a
    Bloomberg test line ("TEST TICKER FOR LEV FIELDS", "SK TEST").
    ponytail: the TEST word is a heuristic; it would also drop a real fund named with the word TEST."""
    ticker = row.get("ticker") or ""
    return bool(row.get("compositeFIGI") and ticker and not DEAD_TICKER.fullmatch(ticker)
                and "TEST" not in (row.get("name") or "").split())  # fmt: skip


def universe(listed: dict[str, dict], etps: dict[str, dict]) -> dict[str, dict]:
    """Both halves. An ETP line whose ticker an SEC-listed security now holds is a dead fund whose
    ticker was reused, so the SEC-listed one wins."""
    taken = {sec_ticker(r["ticker"]) for r in listed.values()}
    return {**{k: r for k, r in etps.items() if sec_ticker(r["ticker"]) not in taken}, **listed}


def sec_ticker(ticker: str) -> str:
    """SEC's (and Yahoo's) dash form: BRK/B, BRK.B and 'BRK B' all become BRK-B. Separators are
    mapped, never stripped -- stripping makes distinct tickers collide."""
    return re.sub(r"[./ ]", "-", ticker.strip().upper())


def security_rows(figi_rows: dict[str, dict], exchange: list[dict], funds: list[dict]) -> dict[str, dict]:
    """The fresh universe as output rows, joined to SEC's CIK, exchange and fund series by ticker."""
    listed = {sec_ticker(r["ticker"]): r for r in exchange if r["exchange"] in LISTED}
    by_symbol = {sec_ticker(r["symbol"]): r for r in funds}
    out = {}
    for figi, f in figi_rows.items():
        ticker = sec_ticker(f["ticker"])
        sec = listed.get(ticker, {})
        fund = by_symbol.get(ticker, {}) if f["securityType"] in FUND_TYPES else {}
        cik = sec.get("cik") or fund.get("cik")
        out[figi] = {
            "composite_figi": figi,
            "share_class_figi": f.get("shareClassFIGI") or "",
            "ticker": ticker,
            "figi_ticker": f["ticker"],
            "name": f.get("name") or "",
            "security_type": f["securityType"],
            "exchange": sec.get("exchange") or "",
            "cik": f"{int(cik):010d}" if cik else "",
            "series_id": fund.get("seriesId") or "",
            "class_id": fund.get("classId") or "",
        }
    return out


def merge(prev: dict[str, dict], fresh: dict[str, dict], today: str, prev_built: str) -> dict[str, dict]:
    """Fresh rows are active. A row that drops out is kept as delisted, never deleted, so its FIGI
    keeps resolving; last_seen is the last build that still listed it."""
    out = {figi: {**row, "status": "active", "last_seen": "", "first_seen": prev.get(figi, {}).get("first_seen") or today}
           for figi, row in fresh.items()}  # fmt: skip
    for figi, row in prev.items():
        if figi not in out:
            out[figi] = row if row["status"] == "delisted" else {**row, "status": "delisted", "last_seen": prev_built}
    return out


def country(biz: dict) -> str:
    """Business-address country. SEC writes addresses two ways: a stateOrCountry code (two letters
    for a US state or territory, a letter and a digit abroad, X1 for the US, XX unknown), or, in
    newer records, isForeignLocation plus a country name."""
    if biz.get("isForeignLocation") == 1:
        name = biz.get("country") or ""
    else:
        code = biz.get("stateOrCountry") or ""
        if code in ("", "XX"):
            return ""
        if code == "X1" or code.isalpha():
            return "United States"
        name = biz.get("stateOrCountryDescription") or ""
    return name.rsplit(", ", 1)[-1]  # "Ontario, Canada" -> "Canada"


def issuer_row(cik: str, sub: dict) -> dict:
    return {
        "cik": cik,
        "name": sub.get("name") or "",
        "entity_type": sub.get("entityType") or "",
        "sic": sub.get("sic") or "",
        "sic_description": sub.get("sicDescription") or "",
        # SEC's label: a two-letter code for a US state, else e.g. "Ireland" or "Ontario, Canada".
        "state_of_incorporation": sub.get("stateOfIncorporationDescription") or sub.get("stateOfIncorporation") or "",
        "fiscal_year_end": sub.get("fiscalYearEnd") or "",
        "country": country((sub.get("addresses") or {}).get("business") or {}),
    }


def fetch_issuers(ciks: list[str], prev: dict[str, dict], identity: str, full: bool) -> dict[str, dict]:
    """New CIKs only, unless `full`. Issuers no longer referenced are kept, like delisted rows."""
    out = dict(prev)
    todo = [c for c in ciks if full or c not in prev]
    for i, cik in enumerate(todo, 1):
        started = time.monotonic()
        sub, _ = fetch(SUBMISSIONS_URL.format(cik), {"User-Agent": identity})
        time.sleep(max(0.0, started + 0.125 - time.monotonic()))  # at most 8/s, under SEC's limit of 10
        if sub:
            out[cik] = issuer_row(cik, sub)
        if i % 500 == 0:
            print(f"  sec submissions {i}/{len(todo)}", flush=True)
    return out


def apply_sectors(securities: dict[str, dict], issuers: dict[str, dict]) -> None:
    for row in securities.values():
        sic = issuers.get(row["cik"], {}).get("sic")
        row["sector"] = sic_to_sector(int(sic)) if sic and row["security_type"] not in FUND_TYPES else ""


def check(securities: dict[str, dict], issuers: dict[str, dict], prev_active: int) -> list[str]:
    """Reasons not to publish this build. Empty means publish."""
    active = [r for r in securities.values() if r["status"] == "active"]
    problems = []
    if len(active) < 0.95 * prev_active:
        problems.append(f"active rows fell from {prev_active} to {len(active)}, more than 5%")
    dupes = [t for t, n in Counter(r["ticker"] for r in active).items() if n > 1]
    if dupes:
        problems.append(f"{len(dupes)} tickers on more than one active row: {sorted(dupes)[:10]}")
    for row in [*securities.values(), *issuers.values()]:
        hits = [v for k, v in row.items() if k not in FREE_TEXT and FORBIDDEN.search(v)]
        if hits:
            problems.append(f"CUSIP/ISIN-shaped value in {row.get('composite_figi') or row['cik']}: {hits}")
    return problems


def read_csv(path: Path, key: str) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        return {row[key]: row for row in csv.DictReader(f)}


def write_csv(path: Path, rows: dict[str, dict], cols: list[str]) -> None:
    """Sorted by key, so a daily rebuild diffs only where the data changed."""
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, cols, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows[k] for k in sorted(rows))


def load_dotenv(path: Path) -> None:
    """KEY=value lines from a .env file into the environment. Variables already set win, so CI
    secrets override a stray .env. ponytail: no `export`, multi-line values or inline comments."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key, value.strip().strip("'\""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--full", action="store_true", help="refetch every issuer from SEC, not only new ones")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    identity = os.environ.get("EDGAR_IDENTITY") or sys.exit("EDGAR_IDENTITY is not set: SEC requires 'Name email'.")
    meta_path = DATA / "meta.json"
    prev_meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    today = datetime.now(timezone.utc).date().isoformat()

    exchange, exchange_modified = sec_table("exchange", identity, prev_meta)
    funds, funds_modified = sec_table("mf", identity, prev_meta)
    api_key = os.environ.get("OPENFIGI_API_KEY")
    listed = sorted({sec_ticker(r["ticker"]) for r in exchange if r["exchange"] in LISTED})
    figi_rows = universe(openfigi_listed(listed, api_key), openfigi_etps(api_key))
    fresh = security_rows(figi_rows, exchange, funds)
    prev = read_csv(DATA / "securities.csv", "composite_figi")
    securities = merge(prev, fresh, today, prev_meta.get("built", today))
    ciks = sorted({r["cik"] for r in securities.values() if r["status"] == "active" and r["cik"]})
    issuers = fetch_issuers(ciks, read_csv(DATA / "issuers.csv", "cik"), identity, args.full)
    apply_sectors(securities, issuers)

    problems = check(securities, issuers, sum(r["status"] == "active" for r in prev.values()))
    if problems:
        sys.exit("not publishing this build:\n  " + "\n  ".join(problems))

    active = [r for r in securities.values() if r["status"] == "active"]
    meta = {
        "built": today,
        "sector_scheme": "sic11-v1",
        "sec_last_modified": {"exchange": exchange_modified, "mf": funds_modified},
        "counts": {
            "active": len(active),
            "delisted": len(securities) - len(active),
            "active_with_cik": sum(bool(r["cik"]) for r in active),
            "issuers": len(issuers),
            "by_type": dict(sorted(Counter(r["security_type"] for r in active).items())),
        },
    }
    write_csv(DATA / "securities.csv", securities, SECURITY_COLS)
    write_csv(DATA / "issuers.csv", issuers, ISSUER_COLS)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta["counts"]))


if __name__ == "__main__":
    main()
