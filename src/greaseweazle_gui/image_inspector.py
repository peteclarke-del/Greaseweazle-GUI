"""Read-only image metadata and integrity inspection."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from .filesystems import FilesystemError, open_image
from .image_detection import ImageFormatGuess, detect_image_format


@dataclass(frozen=True, slots=True)
class ImageInspection:
    path: Path
    size: int
    sha256: str
    guess: ImageFormatGuess
    filesystem: str | None
    volume_label: str | None
    integrity: str


def inspect_image(path: Path) -> ImageInspection:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    guess = detect_image_format(path)
    filesystem: str | None = None
    volume_label: str | None = None
    integrity = "The image container was readable; filesystem validation is unavailable."
    try:
        contents = open_image(path)
    except FilesystemError as error:
        if path.suffix.lower() in {".adf", ".st"}:
            integrity = f"Filesystem validation failed: {error}"
    else:
        filesystem = contents.format_label
        volume_label = contents.volume_label
        integrity = "Filesystem structures and root directory are readable."
    return ImageInspection(
        path,
        path.stat().st_size,
        digest.hexdigest(),
        guess,
        filesystem,
        volume_label,
        integrity,
    )
