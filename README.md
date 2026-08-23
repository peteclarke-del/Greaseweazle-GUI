# Greaseweazle GUI

A native GNOME application for reading, writing, and managing floppy-disk
images with a Greaseweazle device.

The current application:

- checks for the `gw` command and a connected Greaseweazle at startup;
- continues in offline image mode when no device is available, while clearly
  disabling physical operations;
- opens and browses existing Atari ST, Amiga, Acorn DFS, and Commodore D64
  images without attached hardware;
- probes cylinder zero and automatically identifies standard disk formats;
- reads and browses AmigaDOS and Atari ST disks through a temporary image;
- optionally extracts a permanent `.adf` or `.st` image;
- preserves unrecognised or special-format disks as lossless `.scp` captures;
- treats a recognised geometry with an invalid filesystem as potentially
  protected, then captures cylinders 0–82 on both heads as lossless SCP;
- browses Amiga OFS/FFS, Atari FAT12, Acorn DFS, and Commodore 1541 DOS
  directories through bounded read-only filesystem plugins;
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
- writes SCP/A2R raw-flux images without lossy sector-format conversion; and
- displays live cylinder, head, track and verification progress while writing;
- inspects images offline, showing format, geometry, filesystem, volume,
  integrity, size, and SHA-256;
- atomically converts images while preserving the source and warning before a
  potentially lossy raw-flux conversion;
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
   **Extract disk to image** to retain the complete image.
2. Choose **Detect automatically**, or **Choose format** if the disk family or
   exact geometry is already known. The generic **Atari ST** choice detects its
   360/400/440/720/800/880 KB subtype automatically.
   Select Normal, Difficult Media, or Archival capture according to the disk's
   condition and preservation needs.
3. Automatic detection first reads only cylinder zero. Standard disks are then
   read directly as the correct image type; unusual disks fall back to a full
   lossless raw-flux capture.
4. For extraction, choose where the detected `.adf`, `.st`, or raw `.scp`
   image should be saved.
5. **Extract disk to image** reports completion and returns to the main menu.
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
Directory browsing currently supports Atari ST FAT12, AmigaDOS OFS/FFS, Acorn
DFS SSD/DSD, and Commodore 1541 D64. Other listed formats can still be saved
losslessly with **Extract disk to image**.

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

## Creating a blank image

1. Select **Create blank image** and choose a format from the complete,
   manufacturer-grouped Greaseweazle list.
2. Choose the image location. The app supplies the appropriate suffix and shows
   live cylinder, head, and track progress while building the image.
3. For Atari ST and AmigaDOS formats, leave **Create a ready-to-use filesystem**
   enabled and optionally set a volume label. Other formats are created as
   media-level blanks and clearly marked for initialisation on the target.

## Offline image tools

**Inspect or convert image** works without a connected drive. Inspection shows
detected geometry, filesystem/volume, integrity, and SHA-256. It can compare a
second capture or, when the `gw` host tools are installed, convert to any
creatable supported format. Source images are never modified.

**Image library** scans a chosen local folder read-only and groups duplicate
images by SHA-256. Nothing is uploaded or stored outside that folder.

## Drive maintenance

Choose drive A or B from the Device section. RPM measurement takes five samples;
USB bandwidth testing does not access a disk. Head cleaning requires an explicit
confirmation and must only be used with a proper cleaning disk.

## Requirements

- Python 3.10 or newer
- GTK 4.8 or newer and Libadwaita with PyGObject bindings
- Greaseweazle host tools (`gw`) available on `PATH`

On Debian or Ubuntu, the GNOME dependencies are normally provided by
`python3-gi`, `gir1.2-gtk-4.0`, and `gir1.2-adw-1`. Install the Greaseweazle
host tools according to the upstream Greaseweazle documentation.

## Run from the source tree

```sh
./run.sh
```

For UI development without attached hardware, opt in to the simulated device:

```sh
GREASEWEAZLE_GUI_DEMO=1 ./run.sh
```

The simulation is never enabled by default.

When no hardware or host tools are available, choose **Use images offline**.
Existing Atari ST, Amiga, Acorn DFS, and Commodore D64 images can still be opened and browsed; physical
read, extract, and write controls remain disabled until device detection
succeeds.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the ordered reliability, preservation, image,
filesystem, browser, catalogue, and hardware milestones.

## Tests

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```
