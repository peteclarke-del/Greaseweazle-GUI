# Installing Greaseweazle-GUI for linux

## Supported release package

The v0.3.0 native package targets 64-bit Ubuntu 24.04 and Linux Mint 22. It
contains the application, screenshots and help content, Greaseweazle Host Tools
1.23, and the official Greaseweazle udev rules. The distribution supplies
Python 3.12, GTK 4, libadwaita, and PyGObject.

1. Open the required version under GitHub Releases.
2. Download `Greaseweazle-GUI_0.3.0_ubuntu24.04_amd64.deb` and `SHA256SUMS`
   into the same folder.
3. Verify the download:

   ```sh
   sha256sum --check --ignore-missing SHA256SUMS
   ```

4. Install the package and its distribution dependencies:

   ```sh
   sudo apt install ./Greaseweazle-GUI_0.3.0_ubuntu24.04_amd64.deb
   ```

5. Unplug and reconnect Greaseweazle. The package reloads the udev rules, but a
   physical reconnect is required for the new access tags to apply.
6. Start **Greaseweazle-GUI** from the GNOME application grid.

The application can also be started from a terminal with
`greaseweazle-gui`. Use **Help, Diagnostic Log** if hardware detection fails.

## Upgrading

Choose **Help, About Greaseweazle-GUI** and press **Check for Application
Updates**. When GitHub has a newer release, **Update to** downloads the package
made for the same system as the installed one, checks it against the release's
`SHA256SUMS`, and installs it with `pkexec apt-get install` after the system
asks for your password. It then offers to restart the application. The check
sends one request to api.github.com, and only when you press the button. No
update is installed while a disk is being read or written.

The installed package records the system it was built for in
`/usr/lib/greaseweazlegui/package-target`, and the update takes only the package
built for that system. When a release has no package for it, the About window
says so and opens the release page instead. A copy run from the source tree or
installed from the wheel has no such record and is also sent to the release
page.

To upgrade by hand, or from a release up to 0.2.2, which does not have the
button, download the newer `.deb`, verify its checksum, and install it with the
same `apt install ./FILE.deb` command. A download that Check for Application
Updates could not install is kept in `~/.cache/greaseweazle-gui/updates` and can
be installed the same way.

User-created disk images and capture reports are outside the package and are
not replaced.

## Removing

```sh
sudo apt remove greaseweazlegui
```

Removal deletes the application, bundled host tools, desktop metadata, and
device rule. It does not delete disk images or capture reports in user folders.

## Source and developer installation

The `greaseweazle_gui-0.3.0-py3-none-any.whl` wheel attached to this release is
for development and integration use. It does not configure desktop metadata,
GTK dependencies, the Greaseweazle host tool, or hardware access. Users of
other Linux distributions can currently run from the source tree after
installing Python 3.10 or newer, GTK 4.8 or newer, libadwaita, PyGObject, and
the upstream `gw` command.

```sh
./greaseweazle-gui
```

Native packages for other distribution families are planned and will be listed
here only after their installation is tested by the release workflow.
