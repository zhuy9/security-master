"""Check the Java client after mvn -f java/pom.xml verify: the jar holds only the client and its licenses, and the
client answers every lookup on data/ exactly as the Python client does. No network. Run: python java/check.py"""

import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "java/target"
sys.path.insert(0, str(ROOT / "src"))
import security_master as sm
from build import ISSUER_COLS, SECURITY_COLS

ALLOWED = re.compile(r"module-info\.class|META-INF/(MANIFEST\.MF|LICENSE|data/|data/LICENSE|maven/.*)?|io/(github/(zhuy9/(securitymaster/([\w$]+\.class)?)?)?)?")
JAVA_17 = 61  # class file major version: Java 17 users can load the jar
ODD = ["NOPE", "", "   ", "BBG000000000", "bbg", "-", ".", "ZZZZZZZZZZ", "brk..b", "AAPL\u2003", "\u00a0AAPL\x1f"]
ODD_CIKS = ["0", "", "abc", "-5", " 42 ", "99999999999"]
ODD_INTS = [0, 42, -5, 99999999999]


def check_jar() -> None:
    version = ET.parse(ROOT / "java/pom.xml").find("{http://maven.apache.org/POM/4.0.0}version").text
    path = TARGET / f"security-master-{version}.jar"
    assert path.exists(), "Run mvn -f java/pom.xml verify first"
    with zipfile.ZipFile(path) as jar:
        names = jar.namelist()
        assert all(ALLOWED.fullmatch(name) for name in names), [name for name in names if not ALLOWED.fullmatch(name)]
        for name, source in (("META-INF/LICENSE", "LICENSE"), ("META-INF/data/LICENSE", "data/LICENSE")):
            assert jar.read(name) == (ROOT / source).read_bytes(), name
        for name in ("io/github/zhuy9/securitymaster/SecurityMaster.class", "module-info.class"):
            assert int.from_bytes(jar.read(name)[6:8], "big") == JAVA_17, name


def esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def row(r: dict | None, cols: list[str]) -> str:
    # A column the builder has but data/ doesn't yet is "" in the Java client.
    return "NONE" if r is None else "\t".join(esc(r.get(c, "")) for c in cols)


def camel(cols: list[str]) -> str:
    return ",".join(re.sub(r"_(.)", lambda m: m.group(1).upper(), c) for c in cols)


def queries() -> list[tuple[str, str]]:
    qs = [("COLS", ""), ("COUNTS", ""), ("META", ""), ("ROWS", ""), ("ISSUERS", "")]
    for r in sm.securities(active_only=False):
        f, t = r["composite_figi"], r["ticker"]
        forms = (f, f.lower(), t, t.replace("-", "."), t.replace("-", "/"), t.replace("-", " "), t.lower(), f" {t}\u00a0")
        qs += [("SEC", q) for q in forms] + [("CIK", r["cik"])]
    for i in sm.issuers():
        qs += [("CIK", i["cik"]), ("CIKINT", str(int(i["cik"])))]
    return qs + [("SEC", q) for q in ODD] + [("CIK", q) for q in ODD_CIKS] + [("CIKINT", str(q)) for q in ODD_INTS]


def answer(kind: str, q: str, meta_json: str) -> list[str]:
    if kind == "COLS":
        return [camel(SECURITY_COLS) + "\t" + camel(ISSUER_COLS)]
    if kind == "COUNTS":
        return [f"{len(sm.securities())} {len(sm.securities(active_only=False))} {len(sm.issuers())}"]
    if kind == "META":
        return [f"{sm.meta()['commit']}\t{esc(meta_json)}"]
    if kind == "ROWS":
        return [row(r, SECURITY_COLS) for r in sm.securities(active_only=False)]
    if kind == "ISSUERS":
        return [row(r, ISSUER_COLS) for r in sm.issuers()]
    if kind == "SEC":
        return [row(sm.security(q), SECURITY_COLS)]
    return [row(sm.issuer(int(q) if kind == "CIKINT" else q), ISSUER_COLS)]


def check_parity() -> int:
    """Both clients load data/ as a pinned commit named "local", so neither touches the network."""
    raw = {"commit": "local", **{name: (ROOT / "data" / name).read_bytes().decode() for name in sm.FILES}}
    cache = tempfile.mkdtemp()
    Path(cache, "local.json").write_text(json.dumps(raw))
    os.environ.update(SECURITY_MASTER_CACHE=cache, SECURITY_MASTER_REF="local")
    assert sm.meta() == {**json.loads(raw["meta.json"]), "commit": "local"}
    qs = queries()
    python = [line for kind, q in qs for line in answer(kind, q, raw["meta.json"])]
    files = {name: TARGET / f"parity-{name}.tsv" for name in ("queries", "python", "java")}
    files["queries"].write_text("".join(f"{kind}\t{q}\n" for kind, q in qs), encoding="utf-8", newline="\n")
    files["python"].write_text("".join(line + "\n" for line in python), encoding="utf-8", newline="\n")
    classpath = os.pathsep.join(str(TARGET / d) for d in ("classes", "test-classes"))
    subprocess.run(["java", "-cp", classpath, "io.github.zhuy9.securitymaster.ParityDump", str(ROOT / "data"),
                    str(files["queries"]), str(files["java"])], check=True)  # fmt: skip
    java = files["java"].read_text(encoding="utf-8").split("\n")[:-1]
    for n, (p, j) in enumerate(zip(python, java), 1):
        assert p == j, f"line {n} of {files['python'].name} and {files['java'].name} differs:\n{p}\n{j}"
    assert len(python) == len(java), (len(python), len(java))
    return sum(kind in ("SEC", "CIK", "CIKINT") for kind, _ in qs)


if __name__ == "__main__":
    check_jar()
    print(f"Jar contents check passed; {check_parity()} lookups match the Python client")
