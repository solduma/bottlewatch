# Plan: Make `claude3` independent of the bottlewatch project

## Context

`claude3` is a 195-line pure Python launcher that selects one of three Claude Code providers via a flag (`-1`, `-2`, `-3`). It currently lives at `scripts/claude3/claude3.py` inside the bottlewatch repo and is invoked by a shell wrapper at `~/.local/bin/claude3` that uses `uv run --project /Users/iljoyoo/workspace/bottlewatch …`.

The user wants to copy it to a remote workstation via USB. The wrapper's hardcoded `uv run --project …` path makes this impossible.

## Current state

- `~/.local/bin/claude3` — shell wrapper (coupled to bottlewatch)
- `scripts/claude3/claude3.py` — pure Python module, no bottlewatch imports
- `scripts/claude3/README.md` — project-specific docs
- `scripts/claude3/tests/test_launcher.py` — comprehensive pytest suite (no project imports)
- `grep` across `Makefile`, `pyproject.toml`, `launchd/`, rest of repo: **no references**

## Target state

The launcher is a self-contained unit that installs anywhere with a standard Python 3.10+ interpreter. No `uv`, no venv, no repo dependency.

### Layout after change (user home dir)

```
~/.local/bin/claude3          → shell wrapper (replaced)
~/.local/lib/claude3/
    claude3.py                → the module (moved out of bottlewatch)
    tests/
        test_launcher.py      → the test suite (moved)
```

### New wrapper contract

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE3_HOME="${CLAUDE3_HOME:-$(dirname "$SCRIPT_DIR")/lib/claude3}"
exec python3 "$CLAUDE3_HOME/claude3.py" "$@"
```

- No `uv`, no `--project`, no bottlewatch path.
- `CLAUDE3_HOME` env var overrides the default if the user wants a non-standard layout.
- The Python module already has a `if __name__ == "__main__"` block that `sys.exit(main(sys.argv[1:]))` — the wrapper simply calls it.

## Files to create / replace (outside the repo)

1. `~/.local/lib/claude3/` — new directory
2. `~/.local/lib/claude3/claude3.py` — copy of `scripts/claude3/claude3.py` with updated docstring (remove `scripts/claude3/` references)
3. `~/.local/lib/claude3/tests/test_launcher.py` — copy of existing tests, update import path
4. `~/.local/bin/claude3` — rewrite wrapper in place

## Files to delete (inside the repo)

1. `scripts/claude3/` — the entire directory (module + tests + README)

## Docstring / comment changes in `claude3.py`

- Remove: `The vendored copy installed at ~/.local/bin/claude3 adds a __main__ block…` — this file IS the canonical copy now.
- Remove: `scripts/claude3/claude3.py` references in tests.
- Update the end-to-end test's `_LAUNCHER` path to point at the new location.

## Verification plan

1. Run the test suite: `cd ~/.local/lib/claude3 && python3 -m pytest tests/`
2. Smoke test the wrapper: `claude3 -1` with a fake `claude` shim on PATH
3. Verify old bottlewatch tests still pass: `cd /Users/iljoyoo/workspace/bottlewatch && uv run pytest` (confirm `scripts/claude3/` removal doesn't break anything)

## Why system Python3, not uv?

The module uses only `os`, `sys`, `shutil`, `collections.abc` — all stdlib, all stable. There are no third-party deps and no plans to add any. A venv adds disk + indirection with zero upside for this tool. The wrapper stays a single `exec` call.

## USB transfer instructions

After this change, the portable unit is just `~/.local/bin/claude3` + `~/.local/lib/claude3/`. Copy both to the USB, then on the remote:

```bash
mkdir -p ~/.local/bin ~/.local/lib
mv /Volumes/USB/claude3 ~/.local/bin/
chmod +x ~/.local/bin/claude3
mv /Volumes/USB/claude3-dir ~/.local/lib/claude3
# Optional: add ~/.local/bin to PATH if not already there
```
