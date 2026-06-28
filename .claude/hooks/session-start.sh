#!/bin/bash
# SessionStart hook — installs dependencies so tests and linters work in
# Claude Code on the web sessions. Covers both projects in this repo:
#   * UIGen  (Next.js, repo root)
#   * HP Mainstream EQMS (Python, eqms/)
# Idempotent and non-interactive; each ecosystem is independent and best-effort
# so a network hiccup in one never blocks the other.
set -uo pipefail

# Only run in the remote (Claude Code on the web) environment.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# --- HP Mainstream EQMS (Python) ------------------------------------------
# Done first because it is the primary test target for this work. Minimal set
# required to run the pytest suite (UI/SharePoint deps are imported lazily and
# not needed for tests).
if [ -f eqms/requirements.txt ]; then
  echo "[hook] Installing EQMS Python test dependencies…"
  python3 -m pip install --quiet openpyxl pandas matplotlib msal requests pytest \
    || echo "[hook] WARNING: EQMS pip install reported an error"
  # Make the eqms package importable for pytest in every session.
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    echo "export PYTHONPATH=\"${CLAUDE_PROJECT_DIR:-$PWD}/eqms/src:\${PYTHONPATH:-}\"" >> "$CLAUDE_ENV_FILE"
  fi
fi

# --- UIGen (Next.js) -------------------------------------------------------
# Best-effort: a dependency's postinstall may require network not allowed by the
# session's policy; we don't let that abort the hook.
if [ -f package.json ]; then
  echo "[hook] Installing Node dependencies (npm install)…"
  npm install --no-audit --no-fund || echo "[hook] WARNING: npm install reported an error"
  echo "[hook] Generating Prisma client…"
  npx prisma generate || echo "[hook] prisma generate skipped"
fi

echo "[hook] Session start hook complete."
