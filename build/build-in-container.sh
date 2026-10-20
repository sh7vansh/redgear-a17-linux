#!/bin/sh
set -eu
export DEBIAN_FRONTEND=noninteractive
if ! dpkg -s python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 librsvg2-common fonts-dejavu-core >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y --no-install-recommends python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 librsvg2-common fonts-dejavu-core
fi
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 - <<'CHECK'
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw
for library, expected in ((Gtk, (4, 24, 1)), (Adw, (1, 10, 0))):
    actual = (library.get_major_version(), library.get_minor_version(), library.get_micro_version())
    if actual != expected:
        raise SystemExit(f'Expected {expected}, got {actual}. Review and update the release pins.')
    print(library.__name__, '.'.join(map(str, actual)))
CHECK
exec python3 "$script_dir/bundle.py"
