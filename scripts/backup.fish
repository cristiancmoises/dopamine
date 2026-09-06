#!/usr/bin/env fish
set -l root (path resolve (path dirname (status filename))/..)
python3 "$root/scripts/backup.py" $argv
exit $status
