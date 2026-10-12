#!/bin/sh
# Find a Python new enough to run the installer, and run it.
installer_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1
for candidate in python3 python3.14 python3.13 python3.12 python3.11 \
  /opt/homebrew/bin/python3 /usr/local/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
    exec "$candidate" "$installer_dir/install.py" "$@"
  fi
done
printf '%s\n' 'Training Studio setup needs Python 3.11 or newer.' \
  'Install it from https://www.python.org/downloads/ and run setup again.' >&2
exit 1
