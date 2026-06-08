# Agent instructions

## Python environment

This project uses a **local virtual environment** at `./venv`. Always use it for Python commands.

**Do:**
```bash
./venv/bin/python -m pytest tests/ -v
./venv/bin/python script.py
./venv/bin/pip install -e .
```

**Do not** use bare `python`, `python3`, `pip`, or `pip3` from the system PATH. They may point to a different interpreter (or a broken one) and will miss project dependencies such as `curl_cffi`, `aiohttp`, and `pytest`.

If `venv` is missing, create it first:
```bash
python3 -m venv venv
./venv/bin/pip install -e .
./venv/bin/pip install pytest pytest-asyncio
```

## Running tests

```bash
./venv/bin/python -m pytest tests/test_wizzair_smoke.py -v
./venv/bin/python -m pytest tests/ -v
```

Live integration tests (network required) live in `tests/test_*_smoke.py` and `tests/test_comparison.py`.

## Project layout

- `fares_scraper/` — library package
- `fares_scraper/airlines/` — airline-specific scrapers (Ryanair, WizzAir, EasyJet, etc.)
- `fares_scraper/base/` — shared scraper framework
- `tests/` — pytest suite
- `venv/` — local virtualenv (not committed)