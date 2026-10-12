#!/bin/sh
set -eu
export DEBIAN_FRONTEND=noninteractive
if ! dpkg -s python3 python3-gi gir1.2-gtk-4.0 fonts-dejavu-core >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y --no-install-recommends python3 python3-gi gir1.2-gtk-4.0 fonts-dejavu-core
fi
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$script_dir/bundle.py"
