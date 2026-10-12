#!/bin/bash
# Double-click launcher for macOS. Runs the same installer as install.sh.
installer_dir="$(cd -- "$(dirname -- "$0")" && pwd)" || exit 1
printf '\nWelcome to Training Studio setup.\n\n'
/bin/sh "$installer_dir/install.sh" "$@"
installer_exit=$?
if [ -t 0 ]; then
  printf '\n'
  read -r -p 'Press Return to close. ' installer_close
fi
exit "$installer_exit"
