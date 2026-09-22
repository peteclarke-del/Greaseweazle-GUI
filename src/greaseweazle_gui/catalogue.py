"""Optional, read-only catalogue of a local floppy-image folder."""

from __future__ import annotations

import tempfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from .image_inspector import ImageInspection, inspect_image
from .image_sources import (
    ARCHIVE_SUFFIXES,
    IMAGE_SUFFIXES,
    ZipSourceError,
    unpack_each_zipped_image,
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
    #: The image's name inside the zip at *path*, or None for a loose image.
    member: str | None = None
    #: Why a zipped image could not be catalogued; its hash is then empty.
    problem: str | None = None

    @property
    def name(self) -> str:
        return PurePosixPath(self.member).name if self.member else self.path.name

    @property
    def location(self) -> str:
        return f"{self.path} › {self.member}" if self.member else str(self.path)


def _entry(
    path: Path, inspection: ImageInspection, member: str | None = None
) -> CatalogueEntry:
    disk_format = inspection.guess.disk_format
    return CatalogueEntry(
        path,
        inspection.size,
        inspection.sha256,
        disk_format.label if disk_format else "Unknown",
        inspection.filesystem,
        inspection.volume_label,
        member=member,
    )


def _unreadable(archive: Path, problem: str, member: str | None) -> CatalogueEntry:
    return CatalogueEntry(
        archive, 0, "", "Unknown", None, None, member=member, problem=problem
    )


def _archive_entries(archive: Path, scratch: Path) -> Iterator[CatalogueEntry]:
    """Catalogue the disk images in a zip without unpacking anything else.

    Images are chosen from the zip's directory and inspected one at a time in
    *scratch*, exactly as a loose image is, so their hashes are comparable with
    loose copies of the same disk.
    """
    try:
        for member, unpacked in unpack_each_zipped_image(archive, scratch):
            if isinstance(unpacked, ZipSourceError):
                yield _unreadable(archive, str(unpacked), member)
            else:
                yield _entry(archive, inspect_image(unpacked), member)
    except ZipSourceError as error:
        yield _unreadable(archive, str(error), None)


def scan_catalogue(folder: Path, limit: int = 10000) -> tuple[CatalogueEntry, ...]:
    if not folder.is_dir():
        raise OSError("The catalogue folder does not exist.")
    paths = sorted(
        (
            path
            for path in folder.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() in IMAGE_SUFFIXES | ARCHIVE_SUFFIXES
        ),
        key=lambda path: str(path).casefold(),
    )
    limit_error = f"The folder contains more than the {limit} image safety limit."
    if len(paths) > limit:
        raise OSError(limit_error)
    entries: list[CatalogueEntry] = []
    with tempfile.TemporaryDirectory(prefix="greaseweazle-library-") as scratch:
        for path in paths:
            found = (
                _archive_entries(path, Path(scratch))
                if path.suffix.lower() in ARCHIVE_SUFFIXES
                else (_entry(path, inspect_image(path)),)
            )
            # Checked per image, so an archive with thousands of members stops
            # at the limit instead of being unpacked in full first.
            for entry in found:
                entries.append(entry)
                if len(entries) > limit:
                    raise OSError(limit_error)
    counts = Counter(entry.sha256 for entry in entries if entry.sha256)
    return tuple(
        replace(entry, duplicate_count=counts[entry.sha256]) if entry.sha256 else entry
        for entry in entries
    )
