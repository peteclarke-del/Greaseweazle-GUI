# Greaseweazle GUI

A native GNOME application for reading, writing, and managing floppy-disk
images with a Greaseweazle device.

The current application:

- checks for the `gw` command and a connected Greaseweazle at startup;
- explains the problem and exits when no device is available;
- probes cylinder zero and automatically identifies standard disk formats;
- reads and browses AmigaDOS and Atari ST disks through a temporary image;
- optionally extracts a permanent `.adf` or `.st` image;
- preserves unrecognised or special-format disks as lossless `.scp` captures;
- treats a recognised geometry with an invalid filesystem as potentially
  protected, then captures cylinders 0–82 on both heads as lossless SCP;
- browses Amiga OFS/FFS and Atari FAT12 directories without extracting every file; and
- copies files and folders to GNOME Files using drag-and-drop or Copy/Paste.
- provides a toggleable Directory Opus-style dual-pane browser with the disk on
  the left and the local filesystem on the right;
- provides menu-bar, toolbar, keyboard and context-menu actions for Open, Cut,
  Copy, Paste, Rename, New Folder, Properties, Select All, Refresh and Trash;
- accepts file-list clipboard and drag-and-drop transfers from GNOME Files;
- writes sector images using a content-detected or extension-guessed format,
  always asking for confirmation from the complete supported-format list;
- writes SCP/A2R raw-flux images without lossy sector-format conversion; and
- displays live cylinder, head, track and verification progress while writing.

The blank-image control remains disabled until that workflow is implemented.

## Reading a disk

1. Start the application and select **Read disk** to browse, or
   **Extract disk to image** to retain the complete image.
2. Choose **Detect automatically**, or **Choose format** if the disk family or
   exact geometry is already known. The generic **Atari ST** choice detects its
   360/400/440/720/800/880 KB subtype automatically.
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
Directory browsing currently supports Atari ST FAT12 and AmigaDOS OFS/FFS;
other listed formats can be saved with **Extract disk to image**.

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

## Tests

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```
