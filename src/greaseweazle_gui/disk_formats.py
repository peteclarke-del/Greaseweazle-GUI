"""Disk formats offered by the initial read workflow."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiskFormat:
    label: str
    description: str
    gw_format: str
    suffix: str
    cylinders: int
    heads: int
    sectors_per_track: int
    direct_write: bool = False
    raw_flux: bool = False

    @property
    def track_count(self) -> int:
        return self.cylinders * self.heads


DISK_FORMATS = (
    DiskFormat("Amiga DD", "880 KB AmigaDOS disk", "amiga.amigados", ".adf", 80, 2, 11),
    DiskFormat(
        "Amiga HD",
        "1.76 MB AmigaDOS disk",
        "amiga.amigados_hd",
        ".adf",
        80,
        2,
        22,
    ),
    DiskFormat(
        "Atari ST 720 KB", "80 cylinders, double-sided", "atarist.720", ".st", 80, 2, 9
    ),
    DiskFormat(
        "Atari ST 800 KB", "80 cylinders, 10 sectors", "atarist.800", ".st", 80, 2, 10
    ),
    DiskFormat(
        "Atari ST 880 KB", "80 cylinders, 11 sectors", "atarist.880", ".st", 80, 2, 11
    ),
    DiskFormat(
        "Atari ST 360 KB", "80 cylinders, single-sided", "atarist.360", ".st", 80, 1, 9
    ),
    DiskFormat(
        "Atari ST 400 KB",
        "80 cylinders, single-sided, 10 sectors",
        "atarist.400",
        ".st",
        80,
        1,
        10,
    ),
    DiskFormat(
        "Atari ST 440 KB",
        "80 cylinders, single-sided, 11 sectors",
        "atarist.440",
        ".st",
        80,
        1,
        11,
    ),
)


AUTO_DETECT_FORMAT = DiskFormat("Auto-detect", "Raw flux scan", "", ".scp", 80, 2, 0)

PROBE_FORMAT = DiskFormat(
    "Format probe", "Cylinder zero raw flux scan", "", ".scp", 1, 2, 0
)

PRESERVATION_FORMAT = DiskFormat(
    "Protected or nonstandard disk",
    "Raw flux preservation capture including protection tracks",
    "",
    ".scp",
    83,
    2,
    0,
)

# A raw flux image already contains the physical track timing. Passing a
# sector format to ``gw write`` would decode and re-encode it, potentially
# losing copy protection or other nonstandard data.
RAW_FLUX_FORMAT = DiskFormat(
    "Raw flux image",
    "Write captured flux directly without format conversion",
    "",
    ".scp",
    84,
    2,
    0,
    True,
    True,
)
