# AppImage build files

`bundle.py` collects Python 3.10, PyGObject, GTK 4.6, shared libraries, fonts,
icons and dependency license notices from Ubuntu 22.04 x86_64. It reads the
repository's `redgear.py` and produces `build/Redgear-A17.AppDir`.
The resulting AppImage targets x86_64 Linux with glibc 2.35 or newer.

From the repository root, create the bundle in a temporary Ubuntu container:

```sh
podman run --rm --volume "$PWD:/repo:Z" docker.io/library/ubuntu:22.04 \
  sh /repo/build/build-in-container.sh
```

The container script installs the required Ubuntu packages. It must run with
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
