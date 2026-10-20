# AppImage build files

`bundle.py` collects Python 3.14, PyGObject, GTK 4.24.1, libadwaita 1.10.0, shared libraries, fonts,
icons and dependency license notices from Ubuntu 26.10 x86_64. It reads the
repository's `redgear.py` and produces `build/Redgear-A17.AppDir`.
The resulting AppImage targets x86_64 Linux. It includes glibc and its dynamic
loader so GTK does not depend on the host glibc version. The launchers use the
bundled loader's library path without exporting it to host subprocesses.

The font configuration includes the host's `/etc/fonts/fonts.conf` so desktop
font choices, hinting and antialiasing rules apply. Bundled DejaVu fonts provide
fallback glyphs. An existing `FONTCONFIG_FILE` is respected. GTK selects its
renderer automatically; the launchers do not force Cairo.

From the repository root, create the bundle in a temporary Ubuntu container:

```sh
podman run --rm --volume "$PWD:/repo:Z" docker.io/library/ubuntu:26.10 \
  sh /repo/build/build-in-container.sh
```

The container script installs the required Ubuntu packages and checks the GTK
and libadwaita release versions before bundling. Move any previous
`build/Redgear-A17.AppDir` aside before rebuilding to prevent stale libraries
from entering the new image. It must run with
administrator privileges inside the container; it does not install host packages.

Packaging requires an x86_64 appimagetool executable and compatible Type 2
AppImage runtime. These downloaded tools and generated bundles are not tracked.
Place them at `build/appimagetool.AppImage` and `build/runtime-x86_64`, mark the
tool executable, then run from the repository root:

```sh
ARCH=x86_64 build/appimagetool.AppImage --appimage-extract-and-run \
  --runtime-file build/runtime-x86_64 --no-appstream \
  build/Redgear-A17.AppDir build/Redgear-A17-x86_64.AppImage
```

The staged result stays under `build/`. After validation, replace the root
AppImage with it. Close a running instance before launching the rebuilt version.

Run the permission regression tests without a mouse or administrator privileges:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s build/tests
```

The tests use a synthetic configuration and temporary permission rule. They
check device selection, missing permissions, unsupported identities, permission
removal and administrator-command handling without changing system rules.

`smoke-launch` runs the packaged GTK GUI using `Redgear-A17.AppDir`. It requires
a desktop session and a compatible connected mouse with existing OS access.
The checks read the mouse; they do not write settings. Permission setup is
simulated using temporary rules and never changes the host rule:

```sh
REDGEAR_SMOKE_MODE=revoked build/smoke-launch
REDGEAR_SMOKE_MODE=external build/smoke-launch
REDGEAR_SMOKE_MODE=permission build/smoke-launch
REDGEAR_SMOKE_MODE=unsupported build/smoke-launch
```

The `revoked` check drives Remove → Refresh → Apply and verifies that the write
path stays blocked, then adds simulated permissions to verify recovery.
The `external` check verifies that externally removing the rule disables Apply.
GUI screenshot output is saved as `build/appimage-gui.png` when captured.
See [SHARING.md](SHARING.md) for recipient instructions.

To check the source GUI with simulated mouse data on a desktop with GTK4,
PyGObject and libadwaita installed, run:

```sh
REDGEAR_SMOKE_SOURCE="$PWD/redgear.py" REDGEAR_SMOKE_SYNTHETIC=1 \
  python3 build/smoke.py
```

Set `REDGEAR_SMOKE_MODE` to `permission`, `removal`, `unsupported`, `revoked`
or `external` to check those flows. The `apply` mode requires synthetic data
and verifies DPI, lighting and button changes through readback.
Synthetic runs never open a HID device or
change system permission rules. Button-action search is available with
libadwaita 1.4 or newer and is enabled in the bundle.

To check that the package loads your desktop font, set the expected family:

```sh
REDGEAR_SMOKE_SYNTHETIC=1 REDGEAR_SMOKE_EXPECT_FONT='Adwaita Sans' build/smoke-launch
```

The normal GUI check reports the loaded font family and selected renderer.
