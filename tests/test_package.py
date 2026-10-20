"""Check the release files after running python -m build. No network."""

import email.parser
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_package() -> None:
    wheels = list((ROOT / "dist").glob("*.whl"))
    sources = list((ROOT / "dist").glob("*.tar.gz"))
    assert len(wheels) == len(sources) == 1, "Build into an empty dist/ directory first"
    client = (ROOT / "src/security_master/__init__.py").read_bytes()
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = email.parser.BytesParser().parsebytes(wheel.read(metadata_name))
        assert metadata["Name"] == "security-master"
        assert metadata["Requires-Python"] == ">=3.10"
        assert wheel.read("security_master/__init__.py") == client
        assert all(name.startswith(("security_master/", metadata_name.rsplit("/", 1)[0] + "/")) for name in names)
        license_dir = metadata_name.rsplit("/", 1)[0] + "/licenses/"
        for name in ("LICENSE", "data/LICENSE"):
            assert wheel.read(license_dir + name) == (ROOT / name).read_bytes()
    with tarfile.open(sources[0]) as source:
        names = {name.partition("/")[2] for name in source.getnames()}
        assert {"pyproject.toml", "README.md", "LICENSE", "data/LICENSE", "src/security_master/__init__.py"} <= names
        assert all(not name.startswith("data/") or name == "data/LICENSE" for name in names)
        assert not any(name.startswith((".env", ".git/")) for name in names)
        assert not {"src/build.py", "src/sectors.py"} & names


if __name__ == "__main__":
    test_package()
    print("Release contents check passed")
