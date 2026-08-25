"""Optional, read-only catalogue of a local floppy-image folder."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from .image_inspector import inspect_image

IMAGE_SUFFIXES = frozenset(
    {
        ".adf",
        ".st",
        ".scp",
        ".a2r",
        ".img",
        ".ima",
        ".ssd",
        ".dsd",
        ".adm",
        ".ads",
        ".adl",
        ".do",
        ".po",
        ".d64",
        ".d71",
        ".d81",
        ".d1m",
        ".d2m",
        ".d4m",
        ".sf7",
        ".hfe",
    }
)


@dataclass(frozen=True, slots=True)
class CatalogueEntry:
    path: Path
    size: int
    sha256: str
    format_label: str
    filesystem: str | None
    volume_label: str | None
    duplicate_count: int = 1


def scan_catalogue(folder: Path, limit: int = 10000) -> tuple[CatalogueEntry, ...]:
    if not folder.is_dir():
        raise OSError("The catalogue folder does not exist.")
    paths = sorted(
        (
            path
            for path in folder.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() in IMAGE_SUFFIXES
        ),
        key=lambda path: str(path).casefold(),
    )
    if len(paths) > limit:
        raise OSError(f"The folder contains more than the {limit} image safety limit.")
    entries = []
    for path in paths:
        inspection = inspect_image(path)
        disk_format = inspection.guess.disk_format
        entries.append(
            CatalogueEntry(
                path,
                inspection.size,
                inspection.sha256,
                disk_format.label if disk_format else "Unknown",
                inspection.filesystem,
                inspection.volume_label,
            )
        )
    counts = Counter(entry.sha256 for entry in entries)
    return tuple(
        replace(entry, duplicate_count=counts[entry.sha256]) for entry in entries
    )
