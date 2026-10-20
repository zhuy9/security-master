"""Lookups into security-master: US exchange-listed stocks, ETFs and closed-end funds keyed by
composite FIGI, with issuer details from SEC EDGAR. https://github.com/zhuy9/security-master

    import security_master as sm

    sm.security("BRK.B")          # by ticker, in any form: BRK.B, BRK/B, BRK B, BRK-B
    sm.security("BBG000DWG505")   # by composite FIGI
    sm.issuer(1067983)            # by SEC CIK
    sm.securities()               # every active row; securities(active_only=False) for all
    sm.frame()                    # pandas DataFrame of securities joined to issuers
    sm.meta()                     # build date, counts, and the commit this data comes from

The data is the repo's data/ directory, cached in memory and on disk. Once the copy is older than
SECURITY_MASTER_TTL seconds (default 3600), the next call asks GitHub which commit main is at --
a small request -- and if it moved, downloads the files at that commit and swaps the new snapshot
in whole. Rows already returned never change. Offline, the copy in hand keeps serving, and other
threads keep serving it while one checks.

Environment:
    SECURITY_MASTER_TTL    seconds between checks for a new build (default 3600)
    SECURITY_MASTER_REF    a commit or tag to pin; pinned data never refreshes
    SECURITY_MASTER_CACHE  cache directory (default $XDG_CACHE_HOME/security-master, else
                           ~/.cache/security-master); if it isn't writable, or there is no
                           home directory, memory only
"""

import contextlib
import copy
import csv
import dataclasses
import http.client
import io
import json
import math
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

__all__ = ["frame", "issuer", "issuers", "meta", "refresh", "securities", "security"]

REPO = "zhuy9/security-master"
FILES = ("meta.json", "securities.csv", "issuers.csv")
FIGI = re.compile(r"BBG[0-9A-Z]{9}")


@dataclasses.dataclass(frozen=True)
class _Snapshot:
    commit: str
    meta: dict
    rows: list[dict]
    by_figi: dict[str, dict]
    by_ticker: dict[str, dict]
    issuers: dict[str, dict]
    checked: float  # when GitHub last confirmed this is the latest; inf when pinned


_lock = threading.Lock()
_snapshot: _Snapshot | None = None


def _ttl() -> float:
    return float(os.environ.get("SECURITY_MASTER_TTL") or 3600)


def _cache_file(pin: str | None) -> Path | None:
    """None when there is nowhere to cache, so the client runs from memory."""
    try:
        root = os.environ.get("SECURITY_MASTER_CACHE") or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "security-master"
    except RuntimeError:  # no home directory, e.g. a container running as an arbitrary UID
        return None
    return Path(root) / (re.sub(r"[^A-Za-z0-9._-]", "_", pin or "main") + ".json")


def _http(url: str) -> bytes:
    """GET with three tries: one dropped connection must not fail a whole run."""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return resp.read()
        except (OSError, http.client.HTTPException):
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def _head() -> str:
    """main's current commit, from git's ref advertisement: the request `git ls-remote` makes, so
    no API key and no API rate limit."""
    refs = _http(f"https://github.com/{REPO}.git/info/refs?service=git-upload-pack").decode()
    match = re.search(r"([0-9a-f]{40}) refs/heads/main\b", refs)
    if not match:
        raise OSError("could not read main's commit from GitHub")
    return match.group(1)


def _download(commit: str) -> dict:
    # Files at a commit are immutable, so the three always match -- unlike the branch URLs, which
    # GitHub's CDN caches file by file for 5 minutes after each data commit.
    base = f"https://raw.githubusercontent.com/{REPO}/{commit}/data/"
    return {"commit": commit, **{name: _http(base + name).decode() for name in FILES}}


def _touch(path: Path) -> None:
    with contextlib.suppress(OSError):
        now = time.time()
        os.utime(path, (now, now))


def _save(path: Path | None, raw: dict) -> None:
    """One file, replaced atomically: no process ever reads a half-updated set. Best effort: a
    read-only cache directory (a container, a Lambda) leaves the client running from memory.
    ponytail: last writer wins, so a slow writer can put back an older commit; that staleness is
    bounded by one TTL."""
    if path is None:
        return
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(raw))
        os.replace(tmp, path)
        _touch(path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()


def _read(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) and {"commit", *FILES} <= raw.keys() else None


def _build(raw: dict, old: _Snapshot | None, checked: float) -> _Snapshot:
    if old is not None and old.commit == raw["commit"]:
        return dataclasses.replace(old, checked=checked)  # same data: keep the indexes
    rows = list(csv.DictReader(io.StringIO(raw["securities.csv"])))
    by_ticker = {}
    # Active rows win a ticker; among delisted ones, the latest to leave.
    for row in sorted(rows, key=lambda r: (r["status"] == "active", r["last_seen"])):
        by_ticker[row["ticker"]] = row
    return _Snapshot(
        commit=raw["commit"],
        meta=json.loads(raw["meta.json"]),
        rows=rows,
        by_figi={r["composite_figi"]: r for r in rows},
        by_ticker=by_ticker,
        issuers={r["cik"]: r for r in csv.DictReader(io.StringIO(raw["issuers.csv"]))},
        checked=checked,
    )


def _refresh(old: _Snapshot | None, force: bool = False) -> _Snapshot:
    pin = os.environ.get("SECURITY_MASTER_REF")
    path = _cache_file(pin)
    raw = _read(path)
    if pin:
        if raw is None:
            raw = _download(pin)
            snap = _build(raw, old, math.inf)
            _save(path, raw)
            return snap
        return _build(raw, old, math.inf)
    if not force and old is None and raw and time.time() - path.stat().st_mtime < _ttl():
        return _build(raw, None, path.stat().st_mtime)  # another process checked recently
    try:
        head = _head()
        if raw is not None and raw["commit"] == head:
            _touch(path)  # still the latest: processes that start within the TTL skip their check
            return _build(raw, old, time.time())
        if old is not None and old.commit == head:
            return dataclasses.replace(old, checked=time.time())  # memory is current; the disk copy isn't
        fresh = _download(head)
        snap = _build(fresh, old, time.time())  # parse first: a build this client can't read never reaches the cache
        _save(path, fresh)
        return snap
    except (OSError, http.client.HTTPException, ValueError, KeyError, csv.Error) as e:
        if force:
            raise  # refresh() was asked to check now, so it says the check failed
        retry = time.time() - _ttl() + 60  # offline, or a build this client can't parse: try again in a minute
        if old is not None:
            return dataclasses.replace(old, checked=retry)
        if raw is None:
            raise RuntimeError(f"security-master: no cached data yet, and loading it from GitHub failed: {e!r}") from e
        return _build(raw, None, retry)


def _current() -> _Snapshot:
    global _snapshot
    snap = _snapshot
    if snap is not None and time.time() - snap.checked < _ttl():
        return snap
    # Only the first load waits. Once there is a copy, a call that finds another thread mid-check
    # serves that copy instead of queueing behind the network.
    if not _lock.acquire(blocking=snap is None):
        return snap
    try:
        if _snapshot is not snap:  # another thread refreshed while this one waited
            return _snapshot
        _snapshot = _refresh(snap)
        return _snapshot
    finally:
        _lock.release()


def security(id: str, /) -> dict | None:
    """A security by composite FIGI or by ticker, in any separator form (BRK.B, BRK/B, BRK B,
    BRK-B). For a ticker, the active row wins over delisted rows that once used it."""
    snap = _current()
    key = id.strip().upper()
    row = snap.by_figi.get(key) if FIGI.fullmatch(key) else snap.by_ticker.get(re.sub(r"[./ ]", "-", key))
    return dict(row) if row else None


def issuer(cik: str | int) -> dict | None:
    """An issuer by SEC CIK, with or without leading zeros."""
    row = _current().issuers.get(str(cik).strip().zfill(10))
    return dict(row) if row else None


def securities(active_only: bool = True) -> list[dict]:
    return [dict(r) for r in _current().rows if not active_only or r["status"] == "active"]


def issuers() -> list[dict]:
    return [dict(r) for r in _current().issuers.values()]


def meta() -> dict:
    """Build date, row counts, and the commit this data comes from (pin it with SECURITY_MASTER_REF)."""
    snap = _current()
    return {**copy.deepcopy(snap.meta), "commit": snap.commit}


def frame(active_only: bool = True):
    """Securities joined to their issuers as a pandas DataFrame; issuer columns that clash get an
    _issuer suffix (name_issuer). Needs pandas."""
    import pandas as pd

    snap = _current()  # one snapshot for both sides of the join
    rows = [r for r in snap.rows if not active_only or r["status"] == "active"]
    return pd.DataFrame(rows).merge(pd.DataFrame(list(snap.issuers.values())), on="cik", how="left", suffixes=("", "_issuer"))


def refresh() -> dict:
    """Check GitHub for a new build now, whatever the TTL. Returns meta(). Raises if the check
    fails; the data in hand keeps serving."""
    global _snapshot
    with _lock:
        _snapshot = _refresh(_snapshot, force=True)
    return meta()
