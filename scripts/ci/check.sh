#!/bin/bash
# Everything CI checks, with one Python: the whole suite, in parallel, then the package and its
# budgets.
# Usage: check.sh [python]
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
python="${1:-${CI_PYTHON:-python3}}"
"$python" -c 'import sys; sys.exit(None if sys.version_info >= (3, 11) else "Python 3.11 or newer is needed; this is " + sys.version.split()[0])'
cd "$root"
printf 'Python: %s\nGit: %s\nNode: %s\nSource: %s\n' "$("$python" --version 2>&1)" \
  "$(git --version 2>&1)" "$(node --version 2>/dev/null || echo 'not installed')" \
  "$(git rev-parse HEAD 2>/dev/null || echo 'not a checkout')"
"$python" scripts/ci/run_tests.py
"$python" skills/training-studio/scripts/validate_package.py
