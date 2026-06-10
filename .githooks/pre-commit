#!/usr/bin/env bash
# Pre-commit hook: refuse to stage any file named .env.
#
# Install with: make install-hooks
#
# Why: the project's .gitignore covers .env, but `git add -f` or
# a stray `git add .` can still stage it. The .env file historically
# held live API keys (EIA, FRED, Comtrade) and a Postgres password
# before the .gitignore was tightened. This hook makes the
# invariant enforceable in-process.
set -euo pipefail

# `git diff-index --cached --name-only` lists staged files
# (with --diff-filter=d to skip deletes). When HEAD doesn't
# resolve (no commits yet), use `git diff-index --cached
# --name-only --diff-filter=ACMR` against the empty tree.
if git rev-parse --verify HEAD >/dev/null 2>&1; then
  staged=$(git diff-index --cached --name-only --diff-filter=ACMR HEAD 2>/dev/null || true)
else
  staged=$(git diff-index --cached --name-only --diff-filter=ACMR 4b825dc642cb6eb9a060e54bf8d69288fbee4904 2>/dev/null || true)
fi
if echo "$staged" | grep -E '(^|/)(\.env|\.env\.local|\.env\..*\.local)$' >/dev/null; then
  echo "pre-commit: refusing to commit a staged .env file." >&2
  echo "  - Move real keys out of .env and rotate them on the external service." >&2
  echo "  - .env is gitignored; if you need a sample, edit .env.example instead." >&2
  exit 1
fi
