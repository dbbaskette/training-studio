#!/bin/bash
# Run the whole suite in a disposable macOS virtual machine on this Mac.
# Needs Tart, the shared Tart test runner, and the name of a stopped base to clone.
# Extra arguments go to the runner; --dry-run shows the plan without starting anything.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
runner="${TART_TEST_SUITE_HOME:-$HOME/Projects/macos-test-suite}/scripts/tart-test-vm.sh"
base="${TRAINING_STUDIO_TART_BASE:?Set TRAINING_STUDIO_TART_BASE to the name of a stopped Tart base to clone}"
[[ -f "$runner" ]] || { printf 'Set TART_TEST_SUITE_HOME to the folder that holds the Tart test runner.\n' >&2; exit 1; }
exec env TART_NO_AUTO_PRUNE=1 bash "$runner" --project "$root" --name training-studio \
  --guest scripts/ci/guest-test.sh --base "$base" --auto "$@"
