# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, name it explicitly and ask before picking it. Don't silently choose the simpler path — the user may have constraints you haven't seen.
- If something is unclear, stop. Name what's confusing. Ask.

## Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If a diff is mostly config, types, and error paths around a small core change, it's overcomplicated.

If a future maintainer can't tell *why* a line exists from the code around it, it's overcomplicated.

## Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## Spec-Driven Development (SDD)

**Default to no spec. Default to a spec when uncertain on a big change.**

### When a spec is required

Write a spec when the change meets **any** of:

- Creates or changes a **public interface** (exported function, HTTP route, CLI command, schema field, message type, env var).
- Touches **2+ modules** or crosses a domain boundary.
- Involves a **data migration, schema change, or destructive operation**.
- Is **security-, auth-, privacy-, or money-sensitive**.
- Carries **design rationale not obvious from the code**.
- Would benefit from **senior review before merge**.

### When to skip the spec

- One-line bug fix in a single file.
- Internal rename, refactor inside one function, formatting.
- Dependency bump with no behavior change.
- Test, comment, or doc-only change.

### Spec shape

5-30 lines covering: inputs/outputs, behavioral contract, error modes, what this does NOT do, and testable properties a test would assert on. Tests are derived from those properties. One critical-review pass on the spec (did we miss an edge case, is a simpler design possible) before implementation. The critical-review step is an LLM-specific forcing function, not standard practice in non-AI workflows.

**Gray zone:** when in doubt, write a 3-line spec and skip the critical-review pass. The spec is the cheap artifact.

**Spec, not test, is the source of truth.** A test is a derived artifact that verifies behavior the spec already committed to. If a test surfaces behavior the spec didn't commit to, amend the spec to match — the test is the discovery mechanism.

---

# Python Coding Style Guide

## Toolchain

- **Package manager:** uv. **Formatter & linter:** Ruff. **Type checker:** pyright (standard mode, not strict). **Testing:** pytest
- **Installs always through uv** (never `pip`, never system). For one-off scripts that don't touch project code, the system interpreter is fine. For anything that imports from the project, use `uv run`.
- All config in `pyproject.toml`; `.env` is for secrets and `APP_ENV` only

## Type Hints

**Required everywhere** on function/method signatures. Use `dict`, `list`, `tuple` — not `Dict`, `List`, `Tuple` from `typing`. Use `X | None` instead of `Optional[X]`.

## Docstrings

**Google style**, minimal. Rely on type annotations and naming; add docstrings only when the name would be too long to disambiguate.

## Project Structure

**Package-by-feature:** `project/users/models.py`, `project/orders/services.py`, etc. Tests co-located or parallel `/tests` — be consistent per project.

## Error Handling

Built-in exceptions with descriptive messages. No bare `except:`. No custom hierarchy unless the domain demands it.

## Configuration

No hardcoded secrets — no exceptions. No hardcoded configs — use private module-level variables: `_DEFAULT_TIMEOUT_S = 30`, `_MAX_RETRIES = 3`.

## Async, API & Database

**Async-first** (asyncio, FastAPI). Sync is the exception. SQLAlchemy (async) as primary ORM; may vary by project.

## Dependencies

Separate groups in `pyproject.toml`: `[project.dependencies]` for prod, `[dependency-groups]` for dev/test/ai-agents/data-pipelines.

## Git

**Conventional Commits:** `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`. Protected main branch. One concern per PR. Squash-merge or rebase-merge (consistent per repo).

## CI (all must pass)

`ruff format --check`, `ruff check`, `pytest`, `pyright`. See [Ruff](https://docs.astral.sh/ruff/) and [pyright](https://microsoft.github.io/pyright/) docs for current config.

## Anti-Patterns: Banned

- `import *` — namespace pollution.
- `from typing import Dict, List, Optional` — use modern built-ins.
- Mutable default arguments (`def f(x=[])`).
- Bare `except:` and hardcoded secrets/configs — already covered above; listed here as a scan-list.
