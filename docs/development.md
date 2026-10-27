# Development

## Overview

`morpheus-vlt` fakes VLT protocols so the reader integrations can be tested without the actual machines. The
codebase is small on purpose. Protocols in one place, plumbing in another, and every change small enough to
verify before lunch. The [architecture](architecture.md) page has the map.

## Prerequisites

- Python 3.10+
- `pip`, or whatever virtual environment manager you've sworn loyalty to this year
- Linux or macOS for the PTY tests

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pip install -e .
```

## Run locally

```bash
morpheus-vlt --protocol unidesa --port 9000
morpheus-vlt --protocol sas --port 9001 --sas-addr 0x01
morpheus-vlt --protocol vdai --port 9002 --vdai-type m
morpheus-vlt --protocol dex --port 9003 --dex-file ./evadts.txt
morpheus-vlt --protocol rfranco --port 9004
```

## Tests and coverage

```bash
pytest
pytest --cov=src/morpheus_vlt --cov-report=term-missing
ruff check src tests
```

Target coverage is 90%+. Tests go under `tests/` as `test_*.py`. CI runs them on Python 3.10, 3.11 and 3.12,
then runs ruff. If it's red, it's red. It's not "flaky".

The ruff rules live in `[tool.ruff.lint]` in `pyproject.toml`, listed one by one: pycodestyle, pyflakes, import
order, pyupgrade, bugbear, simplify, comprehensions and ruff's own. Don't delete the list to "use the defaults".
CI installs whatever ruff is newest, ruff changes its defaults between releases, and you get a red build for
code nobody touched. Ask me how I know.

Two exceptions are on purpose:

- `SIM108` is off. It wants every if/else turned into a ternary, including the ones with a comment in a branch,
  and a ternary has nowhere to put the comment.
- `tests/test_vdai.py` skips `B905` and `RUF005`. Its parser is copied from oblivion, warts included, so the
  tests read pages exactly the way the reader does.

The PTY tests need Linux or macOS. The pyserial test skips itself if pyserial isn't installed.

`tests/conftest.py` loads the pytest plugin when the package isn't installed, so the fixture works from a bare
checkout too. When it is installed, the entry point already loaded it and the conftest stays out of the way.

## Docs

The site you're reading is MkDocs with the Material theme. Sources live in `docs/`, config in `mkdocs.yml`.

```bash
python -m pip install -r requirements-docs.txt
mkdocs serve           # live preview on http://127.0.0.1:8000
mkdocs build --strict  # what CI runs. Warnings are errors
```

The [API reference](reference/index.md) is generated from the docstrings by mkdocstrings. Write a docstring,
get a page. Write a bad docstring, get a bad page. It's very fair.

### Publishing

`.github/workflows/docs.yml` builds the site on every push and pull request, and deploys it to GitHub Pages on
pushes to `main`. One-time setup, done by a human with admin rights on the repo:

1. **Settings > Pages > Build and deployment > Source**: pick **GitHub Actions**.
2. Push to `main`. The site shows up at `https://well-it-wasnt-me.github.io/Morpheus/`.

Or from a terminal, if you trust `gh` more than you trust menus:

```bash
gh api -X POST repos/well-it-wasnt-me/Morpheus/pages -f build_type=workflow
```

## Coding conventions

- PEP 8, 4-space indentation. Ruff is configured in `pyproject.toml` and has the final word.
- Protocol-specific logic lives in `src/morpheus_vlt/protocols/`. Nowhere else. I will find it.
- Keep new modules small, with only the state and logic they need. Nobody ever regretted a file being too
  short.
- Every behavior change ships with its tests and its docs, in the same change. Docs that lie are worse than no
  docs, and I've read enough of both.

## Writing style

Docs, docstrings, comments and log lines all share one voice: dry, plain-spoken, a little tired of computers,
and still precise about the technical facts. Think a comedian with twenty years in IT.

- ASCII only. `->` instead of arrows, straight quotes, `...` instead of the ellipsis character.
- No em dashes, and no ` -- ` standing in for one. CLI flags are fine.
- Don't string clauses together with semicolons. Split them into sentences.
- 120 characters per line at most. Ruff enforces it on the Python. The Markdown is on the honor system.
- The joke never gets to make the fact wrong. If it's funny and inaccurate, it's just inaccurate.

## Adding a protocol

1. Write `src/morpheus_vlt/protocols/<name>.py` with a dataclass that has `name`, `state` and
   `handle(self, data: bytes) -> bytes`. Return `b""` for empty input unless the protocol really does talk on an
   idle line.
2. Wire it into `build_protocol` in `core/factory.py`.
3. Add it to the `--protocol` choices in `cli/main.py`.
4. Add `tests/test_<name>.py`. Call `handle()` with bytes, check the bytes that come back. No sockets, no
   threads, no tears.
5. Write `docs/protocols/<name>.md`, add it to `nav` in `mkdocs.yml`, add it to the reference page, and list it
   in the README.

## Tips

- Prefer unit tests for protocol handlers and framing helpers. They're fast and they don't flake.
- Reproduce issues with the CLI before adding features. Half the time the bug is in the reader anyway.
- When a reader and the spec disagree, match the reader and write down why. The reader is what has to work.
