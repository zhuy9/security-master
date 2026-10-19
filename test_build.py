"""Checks for build.py's logic. No network. Run: python test_build.py"""

from build import DEAD_TICKER, FORBIDDEN, country, usable_etp, apply_sectors, check, merge, sec_ticker, security_rows, universe


def test_sec_ticker() -> None:
    assert sec_ticker("BRK/B") == sec_ticker("brk.b") == sec_ticker("BRK B") == "BRK-B"
    assert sec_ticker("AAPL") == "AAPL"


def test_security_rows_join_sec_by_ticker() -> None:
    figi = {
        "BBG000B9XRY4": {"ticker": "AAPL", "name": "APPLE INC", "securityType": "Common Stock", "shareClassFIGI": "BBG001S5N8V8"},
        "BBG000DWG505": {"ticker": "BRK/B", "name": "BERKSHIRE HATHAWAY INC-CL B", "securityType": "Common Stock"},
        "BBG000BDTBL9": {"ticker": "SPY", "name": "SPDR S&P 500 ETF TRUST", "securityType": "ETP"},
        "BBG000BHTMY2": {"ticker": "IVV", "name": "ISHARES CORE S&P 500 ETF", "securityType": "ETP"},
    }  # fmt: skip
    exchange = [
        {"cik": 320193, "ticker": "AAPL", "exchange": "Nasdaq"},
        {"cik": 1067983, "ticker": "BRK-B", "exchange": "NYSE"},
        {"cik": 884394, "ticker": "SPY", "exchange": "NYSE"},
        {"cik": 999, "ticker": "IVV", "exchange": "OTC"},  # an OTC line is not a listing: never joined
    ]
    funds = [
        {"cik": 1100663, "seriesId": "S000004310", "classId": "C000012040", "symbol": "IVV"},
        {"cik": 7, "seriesId": "S1", "classId": "C1", "symbol": "AAPL"},  # fund series only join to funds
    ]
    rows = security_rows(figi, exchange, funds)
    assert rows["BBG000B9XRY4"].items() >= {"cik": "0000320193", "exchange": "Nasdaq", "series_id": ""}.items()
    assert rows["BBG000B9XRY4"]["share_class_figi"] == "BBG001S5N8V8"
    assert rows["BBG000DWG505"]["ticker"] == "BRK-B" and rows["BBG000DWG505"]["figi_ticker"] == "BRK/B"
    assert rows["BBG000DWG505"]["cik"] == "0001067983"
    assert rows["BBG000BDTBL9"]["cik"] == "0000884394" and rows["BBG000BDTBL9"]["exchange"] == "NYSE"
    assert rows["BBG000BHTMY2"].items() >= {"cik": "0001100663", "exchange": "", "series_id": "S000004310"}.items()


def test_merge_keeps_dropped_rows_as_delisted() -> None:
    prev = {
        "A": {"ticker": "A", "status": "active", "first_seen": "2026-01-02", "last_seen": ""},
        "B": {"ticker": "B", "status": "active", "first_seen": "2026-01-02", "last_seen": ""},
        "C": {"ticker": "C", "status": "delisted", "first_seen": "2026-01-02", "last_seen": "2026-03-01"},
        "E": {"ticker": "E", "status": "delisted", "first_seen": "2026-01-02", "last_seen": "2026-03-01"},
    }
    fresh = {k: {"ticker": k} for k in ("A", "C", "D")}
    out = merge(prev, fresh, today="2026-10-19", prev_built="2026-10-16")
    assert out["A"] == {"ticker": "A", "status": "active", "first_seen": "2026-01-02", "last_seen": ""}
    assert out["B"]["status"] == "delisted" and out["B"]["last_seen"] == "2026-10-16"
    assert out["C"] == {"ticker": "C", "status": "active", "first_seen": "2026-01-02", "last_seen": ""}  # relisted
    assert out["D"]["first_seen"] == "2026-10-19"
    assert out["E"]["last_seen"] == "2026-03-01"  # an old delisting keeps its date


def test_sector_comes_from_issuer_sic_except_for_funds() -> None:
    securities = {
        "s": {"cik": "1", "security_type": "Common Stock"},
        "f": {"cik": "1", "security_type": "ETP"},  # a commodity trust can file under a financial SIC
        "c": {"cik": "1", "security_type": "Closed-End Fund"},
        "n": {"cik": "2", "security_type": "Common Stock"},  # issuer without a SIC
        "x": {"cik": "", "security_type": "Common Stock"},
    }
    apply_sectors(securities, {"1": {"sic": "3571"}, "2": {"sic": ""}})
    assert {k: r["sector"] for k, r in securities.items()} == {"s": "Technology", "f": "", "c": "", "n": "", "x": ""}


def test_universe_prefers_the_sec_listed_line_for_a_reused_ticker() -> None:
    listed = {"BBG000NEW001": {"ticker": "XYZ", "securityType": "Common Stock"}}
    etps = {
        "BBG000OLD001": {"ticker": "XYZ", "securityType": "ETP"},  # dead fund, ticker since reused
        "BBG000ETF001": {"ticker": "QQQ", "securityType": "ETP"},
    }
    assert sorted(universe(listed, etps)) == ["BBG000ETF001", "BBG000NEW001"]
    assert DEAD_TICKER.fullmatch("2663476D") and DEAD_TICKER.fullmatch("969943Z")
    assert not DEAD_TICKER.fullmatch("AAPL") and not DEAD_TICKER.fullmatch("BRK-B")
    etp = {"compositeFIGI": "BBG000BSWKH7", "ticker": "QQQ", "name": "INVESCO QQQ TRUST SERIES 1"}
    assert usable_etp(etp) and usable_etp({**etp, "name": "CORGI ADVANTEST 2X DAILY ETF"})
    assert not usable_etp({**etp, "ticker": "2663830D"})
    assert not usable_etp({**etp, "ticker": "TESTLEV", "name": "TEST TICKER FOR LEV FIELDS"})
    assert not usable_etp({**etp, "name": "SK TEST"}) and not usable_etp({**etp, "compositeFIGI": None})


def test_check() -> None:
    def row(figi: str, ticker: str, status: str = "active") -> dict:
        return {"composite_figi": figi, "ticker": ticker, "cik": "0000320193", "series_id": "S000004310",
                "name": "ISHARES MIDCAP400 BUFFER100", "status": status}  # fmt: skip

    good = {f"F{i}": row(f"BBG00000000{i}", f"T{i}") for i in range(100)}
    assert check(good, {}, prev_active=100) == []  # 9-character words in a name are not CUSIPs
    assert any("fell" in p for p in check(good, {}, prev_active=200))
    assert any("more than one" in p for p in check({**good, "D": row("BBG0000000D1", "T1")}, {}, prev_active=0))
    assert check({**good, "D": row("BBG0000000D1", "T1", "delisted")}, {}, prev_active=0) == []
    leaky = {**good, "L": {**row("BBG0000000L1", "L"), "share_class_figi": "12345ABC9"}}
    assert any("CUSIP" in p for p in check(leaky, {}, prev_active=0))
    assert any("CUSIP" in p for p in check(good, {"1": {"cik": "1", "ein": "US12345ABC90"}}, prev_active=0))


def test_country_reads_both_sec_address_formats() -> None:
    assert country({"stateOrCountry": "CA", "stateOrCountryDescription": "CA"}) == "United States"
    assert country({"stateOrCountry": "PR"}) == "United States"
    assert country({"stateOrCountry": "L2", "stateOrCountryDescription": "Ireland"}) == "Ireland"  # Accenture
    assert country({"stateOrCountry": "A6", "stateOrCountryDescription": "Ontario, Canada"}) == "Canada"
    assert country({"isForeignLocation": 1, "country": "Taiwan", "countryCode": "F5"}) == "Taiwan"
    assert country({"isForeignLocation": 1, "country": "Ontario, Canada"}) == "Canada"
    assert country({"stateOrCountry": "XX", "stateOrCountryDescription": "UNKNOWN"}) == "" == country({})


def test_forbidden_pattern() -> None:
    for value in ("12345ABC9", "G1234A105", "US12345ABC90"):  # synthetic CUSIP, CINS and US ISIN shapes
        assert FORBIDDEN.search(value), value
    for value in ("BBG000B9XRY4", "0000320193", "S000004310", "C000012040", "AAPL", "BRK-B", "3571", "0926",
                  "SPDR S&P 500 ETF TRUST", "ISHARES IBONDS DEC 2030 TERM"):  # fmt: skip
        assert not FORBIDDEN.search(value), value


if __name__ == "__main__":
    tests = [f for name, f in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"{len(tests)} checks passed")
