"""Frozen instrument examples for the sector policy. Run: python tests/test_sectors.py.

Inputs: data/ at 271cb9033bb56a284c161da74047e4f6a56d1258 (2026-11-05).
Expected outputs include the four approved sic11-v2 CIK exceptions. These are selected
policy examples, not vendor classifications or claims that every issuer in a SIC fits.
The tests read no live data and make no network calls.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from build import apply_sectors
from sectors import BY_CIK, BY_GROUP, BY_INDUSTRY, BY_MAJOR

with (Path(__file__).parent / "fixtures" / "sector_cases.csv").open(newline="", encoding="utf-8") as f:
    CASES = list(csv.DictReader(f))


def test_frozen_instrument_sectors() -> None:
    securities = {r["composite_figi"]: dict(r) for r in CASES}
    issuers = {r["cik"]: {"sic": r["sic"]} for r in CASES}
    assert len(securities) == len(CASES), "duplicate FIGI in frozen cases"
    for row in CASES:
        assert row["cik"].isascii() and row["cik"].isdigit() and len(row["cik"]) == 10, row
        assert row["ticker"] and row["purpose"], row
    apply_sectors(securities, issuers)
    for row in CASES:
        actual = securities[row["composite_figi"]]["sector"]
        assert actual == row["expected_sector"], (row["ticker"], actual, row["expected_sector"])


def test_cases_cover_policy_and_mapping_layers() -> None:
    ciks = {r["cik"] for r in CASES}
    assert set(BY_CIK) <= ciks, "add a reviewed instrument case for each CIK exception"
    sics = {int(r["sic"]) for r in CASES if r["sic"] and r["cik"] not in BY_CIK}
    assert set(BY_INDUSTRY) <= sics, "add a reviewed case for each industry exception"
    assert any(sic not in BY_INDUSTRY and sic // 10 in BY_GROUP for sic in sics)
    assert any(sic not in BY_INDUSTRY and sic // 10 not in BY_GROUP and sic // 100 in BY_MAJOR for sic in sics)
    assert {r["expected_sector"] for r in CASES} == {
        "Technology", "Communication", "Financials", "Health Care", "Industrials", "Materials",
        "Energy & Mining", "Utilities", "Consumer Staples", "Consumer Discretionary", "Real Estate", "",
    }


def test_unlisted_ciks_keep_sic_defaults_and_unknown_sic_is_other() -> None:
    # Synthetic CIKs exercise fallbacks without blessing a pending real-world classification.
    securities = {
        "payments": {"cik": "9999999997", "security_type": "Common Stock"},
        "computer_services": {"cik": "9999999998", "security_type": "Common Stock"},
        "unknown": {"cik": "9999999999", "security_type": "Common Stock"},
    }
    issuers = {"9999999997": {"sic": "7389"}, "9999999998": {"sic": "7370"}, "9999999999": {"sic": "9999"}}
    apply_sectors(securities, issuers)
    assert {k: r["sector"] for k, r in securities.items()} == {
        "payments": "Financials", "computer_services": "Communication", "unknown": "Other",
    }


if __name__ == "__main__":
    tests = [f for name, f in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"{len(tests)} checks passed ({len(CASES)} frozen instrument cases)")
