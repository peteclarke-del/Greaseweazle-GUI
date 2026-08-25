# Current implementation status

This document describes the functionality in version 0.2.0.

## Complete workflows

- Startup detection of the Greaseweazle host tools and connected hardware
- Local device detection remains available when the optional online firmware
  release check is unavailable or rate limited
- Offline image work when physical hardware is unavailable
- Drive A or B selection and reconnection monitoring
- Read and Browse with format choice or standard Amiga and Atari detection
- Extract Disk to Image with native sector suffixes or preservation-grade SCP
- Live track, cylinder, head, sector, retry, and verification progress
- Safe cancellation and subprocess cleanup
- Write Image to Disk with content inspection and explicit format confirmation
- Blank media creation for creatable Greaseweazle formats
- Ready-to-use Atari FAT12 and AmigaDOS OFS blank filesystems
- Read-only dual-pane browser with multiple selection, drag and drop, clipboard,
  conflict handling, local file operations, and GNOME Files integration
- Image inspection, conversion, comparison, SHA-256, and local cataloguing
- HxC HFE v1/v3 inspection, direct writing, capture, conversion, and blank-image
  output using the bundled Greaseweazle codecs
- Track health maps and selective retry for fixed-sector ADF and ST images
- RPM, USB bandwidth, and confirmed cleaning-disk operations
- Session diagnostics and optional JSON capture reports
- Illustrated in-app user and technical guide
- Native Ubuntu 24.04 and Linux Mint 22 release package

## Filesystem coverage in progress

Browseable filesystems are AmigaDOS OFS/FFS, FAT12 in ST/IMG/IMA images, Acorn
DFS in SSD/DSD images, and Commodore 1541 DOS in D64 images. Greaseweazle can
read many more low-level formats than this list. Unsupported filesystems remain
extractable as images and are never shown as empty directories.

See [Format and filesystem support](FORMAT_SUPPORT.md) for details.

## Planned work

- Additional bounded filesystem readers, with corrupt-image fixtures
- Transactional image editing with undo and explicit Save Image
- Optional catalogue notes and thumbnails
- Explicit selection when multiple Greaseweazle USB devices are attached
- Native packages for additional Linux distribution families
