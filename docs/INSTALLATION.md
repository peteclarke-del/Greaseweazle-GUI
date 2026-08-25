# Installing Greaseweazle-GUI for linux

## Supported release package

The v0.2.1 native package targets 64-bit Ubuntu 24.04 and Linux Mint 22. It
contains the application, screenshots and help content, Greaseweazle Host Tools
1.23, and the official Greaseweazle udev rules. The distribution supplies
Python 3.12, GTK 4, libadwaita, and PyGObject.

1. Open the required version under GitHub Releases.
2. Download `Greaseweazle-GUI_0.2.1_ubuntu24.04_amd64.deb` and `SHA256SUMS`
   into the same folder.
3. Verify the download:

   ```sh
   sha256sum --check --ignore-missing SHA256SUMS
   ```

4. Install the package and its distribution dependencies:

   ```sh
   sudo apt install ./Greaseweazle-GUI_0.2.1_ubuntu24.04_amd64.deb
   ```

5. Unplug and reconnect Greaseweazle. The package reloads the udev rules, but a
   physical reconnect is required for the new access tags to apply.
6. Start **Greaseweazle-GUI** from the GNOME application grid.

The application can also be started from a terminal with
`greaseweazle-gui`. Use **Help, Diagnostic Log** if hardware detection fails.

## Upgrading

Download the newer `.deb`, verify its checksum, and install it with the same
`apt install ./FILE.deb` command. User-created disk images and capture reports
are outside the package and are not replaced.

## Removing

```sh
sudo apt remove greaseweazlegui
```

Removal deletes the application, bundled host tools, desktop metadata, and
device rule. It does not delete disk images or capture reports in user folders.

## Source and developer installation

The `greaseweazle_gui-0.2.1-py3-none-any.whl` wheel attached to this release is
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
