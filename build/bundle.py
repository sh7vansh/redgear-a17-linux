from pathlib import Path
import os
import re
import shutil
import subprocess

project = Path(__file__).resolve().parent.parent
out = project / 'build/Redgear-A17.AppDir'
out.mkdir(exist_ok=True)
def copy(source, dest):
    source, dest = Path(source), out / dest
    if not source.exists():
        raise RuntimeError(f'Missing bundle ingredient: {source}')
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    else:
        # Host SELinux labels must not be copied into a portable bundle.
        shutil.copyfile(source.resolve(), dest)
        shutil.copymode(source.resolve(), dest)

copy('/usr/bin/python3.10', 'usr/bin/python3.10')
copy('/usr/lib/python3.10', 'usr/lib/python3.10')
copy('/usr/lib/python3/dist-packages/gi', 'usr/lib/python3/dist-packages/gi')
copy('/usr/lib/x86_64-linux-gnu/girepository-1.0', 'usr/lib/girepository-1.0')
if Path('/usr/lib/girepository-1.0').exists():
    copy('/usr/lib/girepository-1.0', 'usr/lib/girepository-1.0')
copy('/usr/share/glib-2.0/schemas', 'usr/share/glib-2.0/schemas')
copy('/usr/share/fonts/truetype/dejavu', 'usr/share/fonts/truetype/dejavu')
copy(project / 'redgear.py', 'usr/share/redgear-a17/redgear.py')
copy(project / 'build/SHARING.md', 'usr/share/doc/redgear-a17/SHARING.md')
copy('/usr/share/icons/Adwaita', 'usr/share/icons/Adwaita')
copy('/usr/share/icons/hicolor', 'usr/share/icons/hicolor')
copy('/usr/share/common-licenses', 'usr/share/common-licenses')
(out / 'usr/lib/gio/modules').mkdir(parents=True, exist_ok=True)
for module in Path('/usr/lib/x86_64-linux-gnu/gio/modules').glob('*'):
    copy(module, 'usr/lib/gio/modules/' + module.name)

# Bindings load some libraries by name through GI instead of linking them.
ldcache = subprocess.check_output(['ldconfig', '-p'], text=True)
libraries = dict(re.findall(r'^\s*(\S+) .* => (\S+)$', ldcache, re.M))
seeds = [out / 'usr/bin/python3.10', *out.glob('usr/lib/python3.10/lib-dynload/*.so'),
         *out.glob('usr/lib/python3/dist-packages/gi/*.so'),
         *out.glob('usr/lib/gio/modules/*.so')]
for typelib in (out / 'usr/lib/girepository-1.0').glob('*.typelib'):
    for name in re.findall(rb'lib[\w.+-]+\.so(?:\.[\d]+)*', typelib.read_bytes()):
        name = name.decode()
        if name in libraries:
            seeds.append(Path(libraries[name]))
base_libs = {'libc.so.6', 'libm.so.6', 'libpthread.so.0', 'libdl.so.2', 'librt.so.1',
             'libresolv.so.2', 'ld-linux-x86-64.so.2', 'libutil.so.1'}
pending = list(seeds)
seen = set()
while pending:
    source = pending.pop()
    if str(source) in seen:
        continue
    seen.add(str(source))
    result = subprocess.run(['ldd', str(source)], text=True, capture_output=True)
    if 'not found' in result.stdout:
        raise RuntimeError(result.stdout)
    if not str(source).startswith(str(out)) and source.name not in base_libs:
        copy(source, 'usr/lib/' + source.name)
    for name, path in re.findall(r'^\s*(\S+) => (/\S+)', result.stdout, re.M):
        if name not in base_libs:
            pending.append(Path(path))

# Use included fonts when a host has no suitable sans-serif font installed.
(out / 'etc/fonts').mkdir(parents=True, exist_ok=True)
(out / 'etc/fonts/fonts.conf').write_text('''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig><dir prefix="relative">../../usr/share/fonts/truetype/dejavu</dir>
<cachedir prefix="xdg">fontconfig</cachedir>
<alias><family>sans-serif</family><prefer><family>DejaVu Sans</family></prefer></alias>
</fontconfig>
''')

notices = out / 'usr/share/doc/bundled-licenses'
notices.mkdir(parents=True, exist_ok=True)
for copyright in Path('/usr/share/doc').glob('*/copyright'):
    shutil.copy2(copyright, notices / (copyright.parent.name + '.txt'))
(out / 'usr/share/doc/package-versions.txt').write_text(subprocess.check_output(
    ['dpkg-query', '-W', '-f=${Package}\t${Version}\n'], text=True))

(out / 'AppRun').write_text('''#!/bin/sh
set -eu
APPDIR="${APPDIR:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
export APPDIR
export PYTHONHOME="$APPDIR/usr"
export PYTHONPATH="$APPDIR/usr/lib/python3/dist-packages"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export LD_LIBRARY_PATH="$APPDIR/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export GI_TYPELIB_PATH="$APPDIR/usr/lib/girepository-1.0"
export GSETTINGS_SCHEMA_DIR="$APPDIR/usr/share/glib-2.0/schemas"
export GIO_MODULE_DIR="$APPDIR/usr/lib/gio/modules"
export FONTCONFIG_FILE="$APPDIR/etc/fonts/fonts.conf"
export XDG_DATA_DIRS="$APPDIR/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export GSK_RENDERER=cairo
export REDGEAR_DATA_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/redgear-a17"
mkdir -p "$REDGEAR_DATA_DIR"
export FONTCONFIG_FILE="$REDGEAR_DATA_DIR/fonts.conf"
"$APPDIR/usr/bin/python3.10" -c 'import os; from pathlib import Path; from xml.sax.saxutils import escape; fonts=escape(os.environ["APPDIR"] + "/usr/share/fonts/truetype/dejavu"); Path(os.environ["FONTCONFIG_FILE"]).write_text("<fontconfig><dir>" + fonts + "</dir><cachedir prefix=\\"xdg\\">fontconfig</cachedir><alias><family>sans-serif</family><prefer><family>DejaVu Sans</family></prefer></alias></fontconfig>")'
exec "$APPDIR/usr/bin/python3.10" "$APPDIR/usr/share/redgear-a17/redgear.py" "$@"
''')
(out / 'AppRun').chmod(0o755)
(out / 'redgear-a17.desktop').write_text('''[Desktop Entry]
Type=Application
Name=Redgear A-17
Comment=Configure DPI, lighting and side buttons
Exec=redgear-a17
Icon=redgear-a17
Terminal=false
Categories=Settings;HardwareSettings;
''')
(out / 'redgear-a17.svg').write_text('''<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
<rect width="256" height="256" rx="56" fill="#263342"/>
<rect x="70" y="34" width="116" height="190" rx="58" fill="#e6edf3"/>
<path d="M128 34v78M70 112h116" fill="none" stroke="#263342" stroke-width="9"/>
<rect x="118" y="57" width="20" height="38" rx="10" fill="#3288e6"/>
<path d="M83 137v22" stroke="#3288e6" stroke-width="9" stroke-linecap="round"/>
</svg>
''')
if not (out / '.DirIcon').is_symlink():
    (out / '.DirIcon').symlink_to('redgear-a17.svg')
print('AppDir built; shared libraries:', len(list((out / 'usr/lib').glob('*.so*'))))
