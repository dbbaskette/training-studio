#!/bin/bash
# Runs inside a disposable macOS guest that tart-macos.sh started. Not for the host.
set -euo pipefail
source_dir='/Volumes/My Shared Files/source'
results_dir='/Volumes/My Shared Files/results'
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
work="$(mktemp -d "${TMPDIR:-/tmp}/training-studio-guest.XXXXXX")"
trap 'rm -rf "$work"' EXIT
rm -f "$results_dir/result.txt"
python=''
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" > /dev/null && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2> /dev/null; then
    python="$(command -v "$candidate")"
    break
  fi
done
if [[ -z "$python" ]]; then
  # Provide what is missing in this disposable guest, never in the base.
  HOMEBREW_NO_AUTO_UPDATE=1 brew install python@3.13 > "$results_dir/provisioning.log" 2>&1
  python="$(command -v python3.13)"
fi
rsync -a --exclude=.worktrees --exclude=__pycache__ --exclude=.DS_Store "$source_dir/" "$work/repo/"
cd "$work/repo"
printf 'OS: %s\n' "$(sw_vers -productVersion)" | tee "$results_dir/environment.txt"
bash scripts/ci/check.sh "$python" 2>&1 | tee -a "$results_dir/environment.txt" "$results_dir/tests.log"
printf 'PASS\n' > "$results_dir/result.txt"
