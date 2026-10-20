"""Checks for the security_master client against a fake GitHub and a fake clock. No network.
Run: python tests/test_client.py"""

import io
import json
import os
import sys
import tempfile
import threading
import types
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import security_master as sm

REAL_HTTP = sm._http  # captured before fresh() swaps in the fake GitHub

HEADER = "composite_figi,share_class_figi,ticker,figi_ticker,name,security_type,exchange,cik,series_id,class_id,sector,status,first_seen,last_seen\n"
ROWS = (
    "BBG000B9XRY4,BBG001S5N8V8,AAPL,AAPL,APPLE INC,Common Stock,Nasdaq,0000320193,,,Technology,active,2026-10-19,\n"
    'BBG000DWG505,BBG001S5PRB1,BRK-B,BRK/B,"BERKSHIRE HATHAWAY, CL B",Common Stock,NYSE,0001067983,,,Financials,active,2026-10-19,\n'
    "BBG000OLD001,,XYZ,XYZ,OLD XYZ CORP,Common Stock,NYSE,0000000001,,,Industrials,delisted,2026-10-19,2026-10-20\n"
    "BBG000NEW001,,XYZ,XYZ,NEW XYZ ETF,ETP,,,,,,active,2026-10-21,\n"
)
ISSUERS = (
    "cik,name,entity_type,sic,sic_description,state_of_incorporation,fiscal_year_end,country\n"
    "0000320193,Apple Inc.,operating,3571,Electronic Computers,CA,0926,United States\n"
    "0001067983,BERKSHIRE HATHAWAY INC,operating,6331,Fire & Casualty Insurance,DE,1231,United States\n"
)
V1, V2, V3 = "1" * 40, "2" * 40, "3" * 40
COMMITS = {
    V1: {"meta.json": json.dumps({"built": "2026-10-21"}), "securities.csv": HEADER + ROWS, "issuers.csv": ISSUERS},
    V2: {
        "meta.json": json.dumps({"built": "2026-10-22"}),
        "securities.csv": HEADER + ROWS + "BBG000NVDA01,,NVDA,NVDA,NVIDIA CORP,Common Stock,Nasdaq,0001045810,,,Technology,active,2026-10-22,\n",
        "issuers.csv": ISSUERS,
    },
    V3: {"meta.json": "{}", "securities.csv": "ticker,renamed_columns\nAAPL,x\n", "issuers.csv": ISSUERS},  # a schema this client can't read
}


class FakeGitHub:
    def __init__(self) -> None:
        self.head, self.offline, self.calls, self.gate = V1, False, [], None

    def http(self, url: str) -> bytes:
        if self.offline:
            raise urllib.error.URLError("offline")
        if url.endswith("info/refs?service=git-upload-pack"):
            self.calls.append("head")
            if self.gate:
                self.gate.wait()
            return f"001e# service=git-upload-pack\n0000003f{self.head} refs/heads/main\n0000".encode()
        commit, name = url.split("/security-master/")[1].split("/data/")
        self.calls.append(f"get {name}@{commit[:1]}")
        return COMMITS[commit][name].encode()


def fresh(ttl: int = 3600, pin: str | None = None) -> tuple[FakeGitHub, list[float]]:
    """A new 'process': empty memory, its own cache directory, a fake GitHub and a fake clock."""
    github, clock = FakeGitHub(), [1_000_000.0]
    sm._http, sm.time, sm._snapshot = github.http, types.SimpleNamespace(time=lambda: clock[0]), None
    os.environ["SECURITY_MASTER_CACHE"] = tempfile.mkdtemp()
    os.environ["SECURITY_MASTER_TTL"] = str(ttl)
    os.environ.pop("SECURITY_MASTER_REF", None)
    if pin:
        os.environ["SECURITY_MASTER_REF"] = pin
    return github, clock


def test_http_retries_a_dropped_connection_then_gives_up() -> None:
    reset = urllib.error.URLError("connection reset")
    flaky = [reset, reset, io.BytesIO(b"data")]
    with mock.patch.object(sm, "time"), mock.patch("urllib.request.urlopen", side_effect=flaky) as urlopen:  # no sleeps
        assert REAL_HTTP("https://example.org/x") == b"data" and urlopen.call_count == 3
        urlopen.reset_mock()
        urlopen.side_effect = reset
        try:
            REAL_HTTP("https://example.org/x")
            raise AssertionError("expected URLError after three tries")
        except urllib.error.URLError:
            assert urlopen.call_count == 3


def test_lookups() -> None:
    fresh()
    for form in ("BRK-B", "BRK.B", "brk/b", "BRK B", "BBG000DWG505"):
        assert sm.security(form)["composite_figi"] == "BBG000DWG505", form
    assert sm.security("BRK-B")["name"] == "BERKSHIRE HATHAWAY, CL B"  # quoted comma survives
    assert sm.security("XYZ")["name"] == "NEW XYZ ETF"  # the active row wins a reused ticker
    assert sm.security("BBG000OLD001")["status"] == "delisted"  # still reachable by FIGI
    assert sm.security("NOPE") is None and sm.issuer(42) is None
    assert sm.issuer(320193)["name"] == sm.issuer("0000320193")["name"] == "Apple Inc."
    assert len(sm.securities()) == 3 and len(sm.securities(active_only=False)) == 4
    assert len(sm.issuers()) == 2 and sm.meta() == {"built": "2026-10-21", "commit": V1}
    sm.security("AAPL")["ticker"] = "MUTATED"  # callers get copies
    assert sm.security("AAPL")["ticker"] == "AAPL"


def test_refreshes_only_after_the_ttl_and_only_downloads_a_new_commit() -> None:
    github, clock = fresh(ttl=3600)
    sm.security("AAPL")
    assert github.calls == ["head", "get meta.json@1", "get securities.csv@1", "get issuers.csv@1"]
    github.calls.clear()
    clock[0] += 3599
    sm.security("AAPL")
    assert github.calls == []  # within the TTL: memory only
    clock[0] += 2
    sm.security("AAPL")
    assert github.calls == ["head"]  # checked, main had not moved, nothing downloaded
    github.calls.clear()
    before = sm.security("AAPL")
    github.head = V2
    clock[0] += 3601
    assert sm.security("NVDA")["cik"] == "0001045810"  # the new build is picked up
    assert github.calls == ["head", "get meta.json@2", "get securities.csv@2", "get issuers.csv@2"]
    assert before["ticker"] == "AAPL" and sm.meta()["commit"] == V2
    github.calls.clear()
    github.head = V1
    assert sm.refresh()["commit"] == V1 and github.calls[0] == "head"  # refresh() ignores the TTL


def test_a_new_process_reuses_a_recently_checked_disk_cache() -> None:
    github, clock = fresh(ttl=3600)
    sm.security("AAPL")
    github.calls.clear()
    sm._snapshot = None  # a second process sharing the cache directory
    clock[0] += 600
    assert sm.security("AAPL") and github.calls == []
    sm._snapshot = None
    clock[0] += 3600
    assert sm.security("AAPL") and github.calls == ["head"]


def test_offline_serves_the_cache_and_retries_a_minute_later() -> None:
    github, clock = fresh(ttl=3600)
    sm.security("AAPL")
    github.offline, github.calls = True, []
    clock[0] += 3601
    assert sm.security("AAPL")["sector"] == "Technology"
    clock[0] += 30
    sm.security("AAPL")  # no retry storm: next attempt is a minute after the failure
    github.offline = False
    assert github.calls == []
    clock[0] += 31
    sm.security("AAPL")
    assert github.calls == ["head"]

    github, _ = fresh()
    github.offline = True
    try:
        sm.security("AAPL")
        raise AssertionError("expected RuntimeError with no cache and no network")
    except RuntimeError:
        pass


def test_offline_keeps_serving_memory_even_without_the_disk_copy() -> None:
    github, clock = fresh()
    sm.security("AAPL")
    for f in Path(os.environ["SECURITY_MASTER_CACHE"]).iterdir():
        f.unlink()
    github.offline = True
    clock[0] += 3601
    assert sm.security("AAPL")["cik"] == "0000320193"


def test_an_unwritable_cache_runs_from_memory_without_redownloading() -> None:
    github, clock = fresh()
    blocker = Path(tempfile.mkdtemp()) / "a-file"
    blocker.write_text("")
    os.environ["SECURITY_MASTER_CACHE"] = str(blocker / "cache")  # mkdir under a file fails
    assert sm.security("AAPL")
    github.calls.clear()
    clock[0] += 3601
    assert sm.security("AAPL") and github.calls == ["head"]  # main unchanged: nothing downloaded

    github, _ = fresh(pin=V1)
    os.environ["SECURITY_MASTER_CACHE"] = str(blocker / "cache")
    assert sm.security("AAPL") and sm.security("BRK-B")  # pinned works too, from memory


def test_a_build_this_client_cannot_parse_is_not_cached_and_old_data_keeps_serving() -> None:
    github, clock = fresh()
    sm.security("AAPL")
    github.head = V3
    clock[0] += 3601
    assert sm.security("AAPL")["cik"] == "0000320193" and sm.meta()["commit"] == V1
    assert json.loads(next(Path(os.environ["SECURITY_MASTER_CACHE"]).iterdir()).read_text())["commit"] == V1
    github.calls.clear()
    clock[0] += 30
    sm.security("AAPL")
    assert github.calls == []  # retries a minute later, not on every call


def test_other_threads_serve_the_stale_copy_while_one_checks() -> None:
    github, clock = fresh()
    sm.security("AAPL")
    github.gate, clock[0] = threading.Event(), clock[0] + 3601
    checker = threading.Thread(target=sm.security, args=("AAPL",))
    checker.start()
    while "head" not in github.calls:  # the checker is now inside the network call, holding the lock
        pass
    assert sm.security("AAPL")["ticker"] == "AAPL"  # returns at once instead of queueing
    github.gate.set()
    checker.join()


def test_a_pinned_commit_never_checks_for_updates() -> None:
    github, clock = fresh(pin=V1)
    github.head = V2
    assert sm.security("NVDA") is None and sm.meta()["commit"] == V1
    clock[0] += 10**9
    sm.security("AAPL")
    assert "head" not in github.calls and github.calls.count("get securities.csv@1") == 1


def test_concurrent_callers_share_one_check() -> None:
    github, clock = fresh(ttl=3600)
    sm.security("AAPL")
    github.calls.clear()
    github.head = V2
    clock[0] += 3601
    threads = [threading.Thread(target=sm.security, args=("AAPL",)) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert github.calls.count("head") == 1 and github.calls.count("get securities.csv@2") == 1


if __name__ == "__main__":
    tests = [f for name, f in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"{len(tests)} checks passed")
