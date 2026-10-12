# Redgear A-17 for Linux

A Linux controller for the tested Redgear A-17 mouse protocol. Configure DPI,
lighting, effect speed and the two side buttons, including volume controls.

## Run

Download `Redgear-A17-x86_64.AppImage`, mark it executable, and open it:

```sh
chmod +x Redgear-A17-x86_64.AppImage
./Redgear-A17-x86_64.AppImage
```

Requires x86_64 Linux with glibc 2.35 or newer. If FUSE is unavailable:

```sh
./Redgear-A17-x86_64.AppImage --appimage-extract-and-run
```

## Permissions

Click **Add permissions** and authenticate with your own administrator account
before configuring the mouse. This installs `/etc/udev/rules.d/70-redgear-a17.rules`
for USB ID `1bcf:08a0`, granting access to the active local desktop user.
Click **Remove permissions** to undo setup; configuration is immediately blocked.
Unplug and reconnect the mouse to clear the old device access grant.

Terminal alternatives:

```sh
./Redgear-A17-x86_64.AppImage setup
./Redgear-A17-x86_64.AppImage remove-access
```

Setup adds no desktop launcher or Bash settings. Mouse settings are read on
startup and changed only when applied. Changes are verified by reading them back.
No automatic backups are created.

## Compatibility

Only the tested USB `1bcf:08a0` / identity `aa0cfd` protocol is supported.
Other mouse models and hardware revisions are not guaranteed; unsupported
identities are rejected. Windows, macOS and ARM builds are not included.

## Source and sharing

`redgear.py` is the standalone source. Running its GUI requires Python 3,
GTK 4 and PyGObject. Use `--help` for command-line options.

To share the app, send only the AppImage. It includes Python, GTK and dependency
license notices under `usr/share/doc/bundled-licenses/` inside the image.
Each recipient enables access on their own machine.
