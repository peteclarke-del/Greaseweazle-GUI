# Format and filesystem support

Greaseweazle-GUI uses two separate layers when reading a disk.

1. Greaseweazle identifies and decodes the physical track format. The format
   catalogue is loaded from the installed `gw` host tools and is grouped by
   manufacturer in the application.
2. Greaseweazle-GUI opens the decoded sector image with a bounded filesystem
   reader. This second step produces the normal files and folders shown in the
   browser.

A disk can therefore be captured correctly even when its directory cannot be
shown. Low-level format recognition is not a promise that the disk contains a
filesystem, or that Greaseweazle-GUI understands that filesystem.

## Browseable filesystems

| Filesystem | Image suffixes | Current behaviour |
| --- | --- | --- |
| AmigaDOS OFS and FFS | `.adf` | Directories and files are read lazily. DD and HD images are accepted. |
| FAT12 | `.st`, `.img`, `.ima` | Atari TOS, PC, MS-DOS, and other compatible FAT12 sector images can be browsed. Long names and nested directories are bounded. |
| Acorn DFS | `.ssd`, `.dsd` | Single-sided and interleaved double-sided catalogues can be browsed. |
| Commodore 1541 DOS | `.d64` | Standard 35-track images, with or without error bytes, can be browsed. |

These readers reject allocation loops, recursive directory chains, invalid
sector pointers, overlapping files, impossible sizes, and truncated images.
That rejection is a safety result, not proof of physical disk damage.

## Other Greaseweazle formats

The manufacturer menu contains every usable format advertised by the installed
Greaseweazle host tools. Those formats can be selected for extraction, image
creation where the codec supports creation, image conversion, and physical
writing. Read and Browse is enabled when the selected format produces one of
the browseable image suffixes above.

Formats with unsupported filesystems can still be retained in their native
sector-image form through **Disk, Extract Disk to Image**. Protected, unusual,
or unrecognised media should be retained as SCP with the Protected Software
capture profile.

Raw flux formats such as SCP and A2R do not contain a normal directory image.
They must first be decoded to a suitable sector format. Conversion can lose
weak bits, deliberate checksum errors, unusual timing, and other protection
features, so retain the raw source.

## HxC HFE images

HFE v1 (`HXCPICFE`) and HFE v3 (`HXCHFEV3`) containers are recognised from
their headers. The application reports their cylinder and head geometry,
catalogues and hashes them, and writes their encoded tracks directly without
selecting a sector decoder. HFE can also be selected as the output container
for disk extraction, image conversion, and blank-image creation.

An HFE container stores encoded track data rather than a directly browseable
filesystem image. Convert it to a compatible sector image before browsing its
files. Conversion requires the correct machine format and may not preserve all
weak-bit, timing, or multi-revolution behaviour from an SCP or A2R source. The
HFE codec comes from the included Greaseweazle host tools; HxCFE itself is not
bundled or required.

## Automatic identification

Automatic detection currently performs a quick cylinder-zero check for the
standard Atari ST and Amiga layouts that have strong boot-sector signatures.
If that check is inconclusive, the disk is captured once as raw flux and tested
without another physical read. A user who knows another machine family should
select its exact Greaseweazle format from the manufacturer menu.

Filesystem coverage is deliberately expanded one reader at a time. Planned
families include ADFS, Apple DOS, ProDOS, CP/M, and other documented layouts
that can be parsed with strict bounds and deterministic corruption tests.
