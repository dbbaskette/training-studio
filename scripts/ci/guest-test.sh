#!/bin/bash
# Runs inside a disposable macOS guest that tart-macos.sh started. Not for the host.
set -euo pipefail
source_dir='/Volumes/My Shared Files/source'
results_dir='/Volumes/My Shared Files/results'
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
python="$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)"
work="$(mktemp -d "${TMPDIR:-/tmp}/training-studio-guest.XXXXXX")"
trap 'rm -rf "$work"' EXIT
rm -f "$results_dir/result.txt"
rsync -a --exclude=.worktrees --exclude=__pycache__ --exclude=.DS_Store "$source_dir/" "$work/repo/"
cd "$work/repo"
printf 'OS: %s\n' "$(sw_vers -productVersion)" | tee "$results_dir/environment.txt"
bash scripts/ci/check.sh "$python" 2>&1 | tee -a "$results_dir/environment.txt" "$results_dir/tests.log"
printf 'PASS\n' > "$results_dir/result.txt"
