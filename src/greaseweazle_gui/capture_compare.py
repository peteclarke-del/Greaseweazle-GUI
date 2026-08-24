"""Compare two captures without interpreting or modifying either image."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .disk_formats import DiskFormat
from .image_detection import detect_image_format


@dataclass(frozen=True, slots=True)
class CaptureComparison:
    identical: bool
    comparable_tracks: bool
    changed_tracks: tuple[tuple[int, int], ...]
    first_sha256: str
    second_sha256: str
    summary: str


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compare_captures(first: Path, second: Path) -> CaptureComparison:
    first_data = first.read_bytes()
    second_data = second.read_bytes()
    first_hash, second_hash = _digest(first_data), _digest(second_data)
    if first_hash == second_hash:
        return CaptureComparison(
            True,
            True,
            (),
            first_hash,
            second_hash,
            "The captures are byte-for-byte identical.",
        )
    first_guess = detect_image_format(first).disk_format
    second_guess = detect_image_format(second).disk_format
    if not _same_fixed_geometry(
        first_guess, second_guess, len(first_data), len(second_data)
    ):
        return CaptureComparison(
            False,
            False,
            (),
            first_hash,
            second_hash,
            "The images differ and do not share a comparable fixed-sector geometry.",
        )
    assert first_guess is not None
    track_size = first_guess.sectors_per_track * 512
    changed = []
    for index in range(first_guess.track_count):
        start = index * track_size
        end = start + track_size
        if first_data[start:end] != second_data[start:end]:
            changed.append((index // first_guess.heads, index % first_guess.heads))
    return CaptureComparison(
        False,
        True,
        tuple(changed),
        first_hash,
        second_hash,
        f"{len(changed)} track side(s) differ.",
    )


def _same_fixed_geometry(
    first: DiskFormat | None,
    second: DiskFormat | None,
    first_size: int,
    second_size: int,
) -> bool:
    if first is None or second is None or first.sectors_per_track <= 0:
        return False
    first_geometry = (first.cylinders, first.heads, first.sectors_per_track)
    second_geometry = (second.cylinders, second.heads, second.sectors_per_track)
    expected = first.track_count * first.sectors_per_track * 512
    return first_geometry == second_geometry and first_size == second_size == expected
