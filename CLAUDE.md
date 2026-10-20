# security-master

## Project

- US exchange-listed securities keyed by composite FIGI, joined to SEC issuers by CIK.
- Python 3.10+, standard library only. Pandas is optional for `frame()`.
- `src/security_master/__init__.py` is the client shipped on PyPI.
- `src/build.py` builds the data; `src/sectors.py` maps SIC codes to sectors.
- `data/` holds the public CSV files and build metadata. `docs/DATA_SOURCES.md` records source terms.
- `README.md` has user instructions, data fields, and release steps.
- Edit this file for project instructions. `AGENTS.md` is a relative symlink to it.

## Use and check

Run commands from the repository root. On Windows, use `py -3.12` if `python` points to another version.

```sh
python -m pip install -e . ruff==0.17.1
ruff check .
python tests/test_build.py
python tests/test_client.py
```

Ruff runs with its default rules. Don't run `ruff format`: the code is formatted by hand.

Use `import security_master as sm`, then `sm.security("BRK.B")` or `sm.issuer(1067983)`.
The first lookup downloads data. Later lookups use the cache and check for new data after one hour.
Set `SECURITY_MASTER_REF` to a data commit for reproducible results, or `SECURITY_MASTER_CACHE`
to choose the cache directory. Tests use fake data and make no network calls.

To check a release, start with an empty `dist/` directory:

```sh
python -m pip install build==1.6.1 twine==7.0.0
python -m build
python -m twine check --strict dist/*
python tests/test_package.py
```

## Data and releases

- `.github/workflows/refresh.yml` refreshes data every weekday and commits changes to `data/`.
- To rebuild locally, copy `.env.example` to `.env`, set `EDGAR_IDENTITY`, and run `python src/build.py`.
  `OPENFIGI_API_KEY` is optional. `--full` refetches all issuers. This makes live API calls and writes data.
- `.github/workflows/release.yml` tests and builds with Python 3.12. A manual run checks the package only.
  Publishing a GitHub release uploads it to PyPI through the `pypi` environment and Trusted Publishing.
- The release tag must be `v` plus the version in `pyproject.toml`. Follow the release steps in the README.
- Package versions control client code. Data updates do not need package releases.
- Keep the data format compatible with released clients, which keep downloading new data.
- Run both source test scripts and the package checks before a release. Verify the built wheel imports
  from a clean environment. Do not run a live data refresh just to test a code change.

## Data rules

- Composite FIGI is the security key. Tickers can change or be reused. Active rows win ticker lookups.
- Preserve leading zeros in CIKs. A delisted row stays in the dataset.
- Never distribute CUSIPs or ISINs. Keep their mapping in the consuming project.
- Sectors are this project's SIC mapping, not GICS. Funds can have no sector or issuer match.
- Preserve the build checks for missing rows, duplicate active tickers, stale SEC files, and restricted identifiers.
- The package contains the client, not the CSV files or data builder. Keep secrets out of release files.
