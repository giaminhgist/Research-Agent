#!/usr/bin/env bash
# Runs a Research-Agent hook with the first Python >= 3.11 found. Never fails the hook.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ok() { "$@" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; }
for py in "$RA_PYTHON" "$HOME/.research-agent/venv/bin/python" "$HOME/.research-agent/venv/Scripts/python.exe" python3 python; do
  [ -z "$py" ] && continue
  if ok "$py"; then
    exec "$py" "$HERE/dispatch.py" "$@"
  fi
done
if ok py -3; then
  exec py -3 "$HERE/dispatch.py" "$@"
fi
exit 0
