# Greaseweazle-GUI

## for linux

A native GNOME application for reading, writing, and managing floppy-disk
images with a Greaseweazle device.

The current application:

- uses a restrained main workspace with conventional **File**, **Disk**,
  **Drive**, and **Help** menus instead of presenting every operation at once;
- keeps progress, browsing, inspection, comparison, catalogue, diagnostics,
  health reports, and completion results inside the main application window;
- includes a comprehensive in-app user guide with real screenshots, detailed
  workflows, preservation guidance, troubleshooting, and keyboard reference;
- checks for the `gw` command and a connected Greaseweazle at startup;
- continues in offline image mode when no device is available, while clearly
  disabling physical operations;
- opens and browses existing AmigaDOS, FAT12, Acorn DFS/ADFS, Commodore 1541,
  Tandy Color Disk BASIC, and Tandy/Dragon OS-9 images, automatically decoding
  HFE, SCP, and A2R containers without attached hardware;
- probes cylinder zero and automatically identifies standard disk formats;
- reads browseable filesystems through a temporary sector image;
- optionally extracts a permanent sector image using the suffix appropriate to
  the selected Greaseweazle format;
- preserves unrecognised or special-format disks as lossless `.scp` captures;
- treats a recognised geometry with an invalid filesystem as potentially
  protected, then captures cylinders 0–82 on both heads as lossless SCP;
- browses Amiga OFS/FFS, Atari TOS and compatible PC FAT12, Acorn DFS/ADFS,
  Commodore 1541 DOS, Color Disk BASIC, and OS-9 RBF directories through
  bounded read-only filesystem plugins;
- copies files and folders to GNOME Files using drag-and-drop or Copy/Paste;
- provides a toggleable Directory Opus-style dual-pane browser with the disk on
  the left and the local filesystem on the right;
- provides menu-bar, toolbar, keyboard and context-menu actions for Open, Cut,
  Copy, Paste, Rename, New Folder, Properties, Select All, Refresh and Trash;
- accepts file-list clipboard and drag-and-drop transfers from GNOME Files;
- offers Skip, Keep Both, or Replace for transfer conflicts and reports partial
  copy/move results accurately;
- retains per-track read/write quality, displays a cylinder/head health map, and
  can selectively retry damaged ADF/ST track sides;
- safely cancels reads, automatic detection, writes, conversion, retries,
  maintenance, and blank-image creation using the Greaseweazle cleanup path;
- offers Normal, Difficult Media, Archival, and raw Protected Software capture profiles without
  requiring users to understand Greaseweazle command-line switches;
- writes sector images using a content-detected or extension-guessed format,
  always asking for confirmation from the complete supported-format list;
- writes SCP/A2R raw-flux images without lossy sector-format conversion;
- displays live cylinder, head, track and verification progress while writing;
- inspects images offline, showing format, geometry, filesystem, volume,
  integrity, size, and SHA-256;
- atomically converts images while preserving the source and warning before a
  potentially lossy raw-flux conversion;
- recognises HxC HFE v1 and v3 images by header, writes their encoded tracks
  directly, and creates or converts captures and blank media as `.hfe`;
- compares captures by hash and changed track side, and optionally writes a
  JSON capture report with device/profile/provenance information;
- catalogues a local image folder and identifies duplicate captures;
- monitors device removal/reconnection and supports physical drive A/B;
- measures RPM and USB bandwidth and runs a confirmed cleaning-disk cycle; and
- creates blank media images for every creatable format advertised by the
  installed Greaseweazle, with ready-to-use Atari FAT12 or AmigaDOS OFS
  filesystems where supported.

## Reading a disk

1. Start the application and select **Read disk** to browse, or
   choose **Disk → Extract Disk to Image** to retain the complete image.
2. Choose **Detect automatically**, or **Choose format** if the disk family or
   exact geometry is already known. The generic **Atari ST** choice detects its
   360/400/440/720/800/880 KB subtype automatically.
   Select Normal, Difficult Media, or Archival capture according to the disk's
   condition and preservation needs.
3. Automatic detection first reads only cylinder zero. Standard disks are then
   read directly as the correct image type; unusual disks fall back to a full
   lossless raw-flux capture.
4. For extraction, choose the native sector container or HxC HFE for a
   recognised format, then choose where the image should be saved. Unusual or
   protected media remains a raw `.scp` capture.
5. **Extract Disk to Image** opens a completion result in the main window.
   Use the Back button to return to the start page.
   **Read disk** opens the image-backed directory browser; double-click folders
   to browse them.
6. Select one or more items and either drag them into GNOME Files, or
   right-click, choose **Copy**, and paste them into a folder.

Only copied or dragged files are materialized in a temporary cache, which is
removed when the application closes. Images created with **Extract disk to
image** are retained.

Exact Amiga and Atari geometry can also be selected from the normal read dialog
when automatic detection is not appropriate.

The known-format menu is generated from the installed Greaseweazle version. It
contains every format advertised by `gw`, sorted into manufacturer submenus,
and loads each format's cylinder and head geometry for accurate progress.
The format menu and filesystem browser solve different parts of the job.
Greaseweazle decodes the physical track format. Greaseweazle-GUI then needs a
filesystem reader to show normal files and folders. Current readers support
Atari TOS FAT12 (`.st`), compatible FAT12 sector images (`.img` and `.ima`),
AmigaDOS OFS/FFS (`.adf`), Acorn DFS (`.ssd` and `.dsd`), Acorn ADFS S/M/L
(`.adm`, `.ads`, and `.adl`), Commodore 1541 DOS (`.d64`), Tandy Color Disk
BASIC, and OS-9 RBF (`.img`). Suitable PC, MS-DOS, and other FAT12 disks are
therefore not limited to the Atari path. Shared `.img` files are identified by
their filesystem structures rather than their filename. Other listed formats
can still be captured, inspected, converted, and written, but the application
will report that their filesystem is unsupported instead of showing an empty
directory.

See [Format and filesystem support](docs/FORMAT_SUPPORT.md) for the exact
boundary between Greaseweazle media support and in-app directory browsing.

The Protected Software profile bypasses sector decoding and records five raw
revolutions to SCP. Permanent captures can also receive an adjacent
`.capture.json` report containing SHA-256, format decision, capture profile,
device details, and per-track results.

## Writing a disk

1. Select **Write disk** and open a local image file.
2. The app first examines the image contents. If that is inconclusive, it uses
   the extension and image size as a fallback.
3. Confirm or replace the suggested format using the complete manufacturer-
   grouped list from the installed Greaseweazle version.
4. Confirm the destructive operation. The app shows live track, cylinder, head,
   and verification progress, then reports **Complete** and returns to the menu.

Raw SCP and A2R captures are offered as **raw flux (no conversion)** so unusual
tracks and copy protection are retained when written back.

HxC HFE v1 and v3 images are identified from their container header, browsed
through an automatically decoded temporary sector image, and written as encoded
tracks without forcing a sector format. HFE is also available as an output
container when extracting, converting, or creating an image. These features use
the bundled Greaseweazle HFE codec; the separate HxCFE application is not
required or bundled.

## Creating a blank image

1. Select **Create blank image** and choose a format from the complete,
   manufacturer-grouped Greaseweazle list.
2. Choose the image location. The app supplies the appropriate suffix and shows
   live cylinder, head, and track progress while building the image.
3. For Atari ST and AmigaDOS formats, leave **Create a ready-to-use filesystem**
   enabled and optionally set a volume label. Other formats are created as
   media-level blanks and clearly marked for initialisation on the target.
4. Enable **Create as HxC HFE container** when the blank image is intended for
   an HxC-compatible floppy emulator.

## Offline image tools

**Inspect or convert image** works without a connected drive. Inspection shows
detected geometry, filesystem/volume, integrity, and SHA-256. It can compare a
second capture or, when the `gw` host tools are installed, convert to any
creatable supported format. Source images are never modified.

For HxC floppy emulators, enable the HFE output option after choosing the target
machine format. HFE conversion needs both pieces of information: the disk
format defines the track encoding and geometry, while `.hfe` selects the HxC
container.

**Image library** scans a chosen local folder read-only and groups duplicate
images by SHA-256. Nothing is uploaded or stored outside that folder.

## Drive maintenance

Choose drive A or B from the Drive menu. RPM measurement takes five samples;
USB bandwidth testing does not access a disk. Head cleaning requires an explicit
confirmation and must only be used with a proper cleaning disk.

## In-app help

Choose **Help → User Guide** or press **F1**. The guide opens inside the main
window and covers every application operation, filesystem and format behaviour,
capture profiles, track-health interpretation, selective retry, safety rules,
diagnostics, and keyboard controls. Its screenshots are captured from real,
deterministic application states by `tools/capture_help_screenshots.sh` and do
not contain local user files.

## Requirements

- Python 3.10 or newer
- GTK 4.8 or newer and Libadwaita with PyGObject bindings
- Greaseweazle host tools (`gw`) available on `PATH`

On Debian or Ubuntu, the GNOME dependencies are normally provided by
`python3-gi`, `gir1.2-gtk-4.0`, and `gir1.2-adw-1`. Install the Greaseweazle
host tools according to the upstream Greaseweazle documentation.

## Install a release

GitHub Releases provide a native `.deb` installer for 64-bit Ubuntu 24.04 and
Linux Mint 22. The installer includes Greaseweazle-GUI, the illustrated guide,
Greaseweazle Host Tools 1.23, and the official Linux device-access rules. GTK,
libadwaita, and Python are installed or updated through the distribution package
manager.

1. Download `Greaseweazle-GUI_0.2.2_ubuntu24.04_amd64.deb` and `SHA256SUMS`
   from the matching GitHub Release.
2. From the download folder, run
   `sha256sum --check --ignore-missing SHA256SUMS`.
3. Install with
   `sudo apt install ./Greaseweazle-GUI_0.2.2_ubuntu24.04_amd64.deb`.
4. Unplug and reconnect the Greaseweazle so the new device rule takes effect.
5. Open **Greaseweazle-GUI** from the GNOME application grid, or run
   `greaseweazle-gui` from a terminal.

Remove it with `sudo apt remove greaseweazlegui`. User disk images, capture
reports, and application data are not removed.

The `greaseweazle_gui-0.2.2-py3-none-any.whl` wheel is also attached for
developers. It does not install GTK, libadwaita, the Greaseweazle host tools,
desktop metadata, or device rules, so normal desktop users should install the
`.deb` package.

Maintainers create a release by updating the version in `pyproject.toml`,
merging the release commit, and pushing a matching tag such as `v0.2.2`. The
release workflow tests the exact tag, builds and installs the package on Ubuntu
24.04, generates SHA-256 checksums, and publishes all files to GitHub Releases.

To build the installer locally on Ubuntu 24.04, run
`./packaging/build-deb.sh dist`. The Greaseweazle host-tool version is pinned in
`packaging/greaseweazle-version.txt` for reproducible release review.

## Run from the source tree

```sh
./greaseweazle-gui
```

For UI development without attached hardware, opt in to the simulated device:

```sh
GREASEWEAZLE_GUI_DEMO=1 ./greaseweazle-gui
```

The simulation is never enabled by default.

When no hardware or host tools are available, choose **Use images offline**.
Existing AmigaDOS, FAT12, Acorn DFS/ADFS, Commodore 1541, Color Disk BASIC,
and OS-9 images can still be opened and browsed. Physical read, extract, and
write controls remain disabled until device detection succeeds.

Additional technical documentation:

- [Current implementation status](docs/CURRENT_STATUS.md)
- [Format and filesystem support](docs/FORMAT_SUPPORT.md)
- [Release installation](docs/INSTALLATION.md)
- [Maintainer release process](docs/RELEASING.md)

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the ordered reliability, preservation, image,
filesystem, browser, catalogue, and hardware milestones.

## Tests

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```
