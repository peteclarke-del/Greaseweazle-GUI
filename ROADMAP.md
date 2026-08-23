# Roadmap

The application is developed in preservation-first stages. A workflow is only
considered complete when failures are recoverable, progress is meaningful, and
the original disk or image cannot be altered accidentally.

## 1. Reliable physical operations

- [Complete] Add safe cancellation for reads, writes, image creation, and
  multi-stage format detection using Greaseweazle's interrupt cleanup path.
- [Complete] Detect device removal and reconnection without freezing the interface.
- [Complete] Retain post-read and post-write per-track results with health maps,
  plus selective damaged-track retry for fixed-sector ADF/ST captures.
- [Complete] Retain a session diagnostic log that can be copied or saved.

Complete when an operation can be stopped safely, unplugging the device produces
an actionable error, and the result clearly identifies unreadable or mismatched
track sides.

## 2. Image creation and inspection

- [Complete] Implement **Create blank image** using the installed Greaseweazle
  format list.
- [Complete] Open and browse existing supported images without requiring
  attached hardware.
- [Complete] Show detected format, geometry, filesystem, volume label, image
  integrity, file size, and SHA-256.
- [Complete] Convert between compatible image formats without claiming that a lossy
  conversion preserves protection or weak-bit data.

Complete when users can create, inspect, browse, and safely convert standard
images entirely from the GUI.

## 3. Preservation workflows

- [Complete] Add Normal, Difficult Media, Archival, and Protected Software
  profiles; the latter retains five revolutions as raw SCP.
- [Complete] Preserve raw source captures and never modify them during conversion.
- [Complete] Optionally record capture metadata, device details, format,
  diagnostics, per-track results, and SHA-256 in an atomic JSON sidecar.
- [Complete] Compare two captures by hash and identify changed track sides for
  fixed-sector formats.

Complete when a capture is reproducible and its provenance can be audited later.

## 4. Filesystem coverage

- [Complete] Move filesystem readers behind a small bounded plugin interface.
- [In progress] Read-only browsing covers Atari FAT12, AmigaDOS OFS/FFS, Acorn
  DFS SSD/DSD, and Commodore 1541 D64. Apple, ADFS, ProDOS, and further
  filesystems for which the image format provides sufficient sector data.
- Add fixtures for damaged directories, cyclic allocation chains, unusual names,
  and files spanning non-contiguous blocks.
- Keep unsupported and copy-protected media browse-safe by offering the raw image
  and diagnostics rather than treating it as an empty disk.

Complete when adding a filesystem does not require modifying the browser and every
reader is bounded against corrupt or hostile image metadata.

## 5. File browser

- [Complete] Replace the overcrowded operation dashboard with a stable main
  workspace and conventional File, Disk, Drive, and Help menus. Substantial
  results and tools are presented in the window container rather than dialogs.
- [Complete] Revisit the dual-pane layout, navigation model, selection behaviour, menus,
  shortcuts, drag-and-drop, and accessible labels as one focused milestone.
- [In progress] Add conflict choices, partial-result reporting, and clear
  read-only state before allowing any write-back into an image.
- Add optional image editing as a transactional workflow with undo and an explicit
  **Save image** step; never modify the source capture in place.

Complete when normal GNOME file-manager behaviour is consistent in both panes and
all mutations are transactional and recoverable.

## 6. Library and hardware tools

- [In progress] Add an optional local catalogue. Folder scanning, format/volume
  labels, hashes, and duplicate detection are implemented; thumbnails and notes remain.
- [In progress] Drive A/B selection is implemented; explicit selection among
  multiple USB Greaseweazle devices remains.
- [Complete] Add USB bandwidth testing, cleaning confirmation, RPM reporting, and guidance
  where the hardware and `gw` expose reliable measurements.
- [Complete] Export a privacy-scoped session log containing tool diagnostics and
  filenames but no disk-file contents.

Complete when collections and hardware can be managed without weakening the
simple read, extract, and write workflows.
