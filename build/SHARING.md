# Sharing Redgear A-17 for Linux

Share only `Redgear-A17-x86_64.AppImage`. It includes Python and GTK; recipients
do not need the source script or your desktop shortcut.

This build is for x86_64 Linux with glibc 2.35 or newer (for example, Ubuntu
22.04 or newer). It is not a Windows/macOS/ARM build, and does not target Alpine
Linux's musl runtime. GUI and mouse access were tested on Fedora 44; bundled
Python/GTK imports were also tested in a clean Ubuntu 22.04 container.

Only the tested Redgear A-17 protocol is enabled: USB 1bcf:08a0 and identity
aa0cfd. Other retail models and A-17 revisions are not guaranteed. Unsupported
identity responses are rejected before reading the configuration or enabling
controls. Only the side buttons can be remapped.

First launch:

1. Put the AppImage somewhere permanent and mark it executable using the file
   manager's Properties/Permissions, or `chmod +x Redgear-A17-x86_64.AppImage`.
2. Open it with the mouse connected.
3. Permissions are required to read or change settings. Click **Add permissions** and authenticate with your own administrator account. Reconnect the
   mouse if needed. The mouse works normally without configuration access.

The permission rule is restricted to USB 1bcf:08a0 and grants access to the active
local desktop user, including other devices that share that USB ID. The app
runs as your normal user. Setup adds no desktop launcher or Bash settings.
Automatic setup needs PolicyKit and a desktop authentication
agent. A selectable terminal command is provided if that is unavailable:

```bash
./Redgear-A17-x86_64.AppImage setup
```

If FUSE is unavailable:

```bash
./Redgear-A17-x86_64.AppImage --appimage-extract-and-run
```

The app reads the recipient's mouse settings; it does not apply the sender's
settings on startup. It writes changes only when Apply settings is pressed.
Settings changes are verified by reading them back from the mouse. No automatic
backups are created. No sender settings or credentials are included.
To undo setup, click **Remove permissions** in the app, then authenticate. Or run:

```bash
./Redgear-A17-x86_64.AppImage remove-access
```

The app immediately blocks configuration after rule removal, including after
Refresh or reopening. Unplug and reconnect the mouse to clear the old Linux
access grant on the connected device.
Removal does not reset the mouse settings or remove other permission rules.

GTK/Python and other bundled dependency copyright notices are included under
`usr/share/doc/bundled-licenses/` inside the AppImage.
