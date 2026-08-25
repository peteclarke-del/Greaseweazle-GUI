"""Open native and track-container images through supported filesystem readers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .convert_image import convert_image
from .disk_formats import DiskFormat
from .filesystems import DiskContents, FilesystemError, browsable_suffixes, open_image
from .format_catalog import supported_formats
from .format_detection import conversion_score
from .image_detection import detect_image_format
from .operation import OperationController

TRACK_CONTAINER_SUFFIXES = frozenset({".a2r", ".hfe", ".scp"})


@dataclass(frozen=True, slots=True)
class BrowsableImage:
    contents: DiskContents
    image_path: Path
    disk_format: DiskFormat | None
    diagnostic: str = ""


def browsable_image_suffixes() -> frozenset[str]:
    """Return native and decodable container suffixes offered by the browser."""
    return browsable_suffixes() | TRACK_CONTAINER_SUFFIXES


def _decode_candidates(source: Path) -> tuple[DiskFormat, ...]:
    candidates = tuple(
        disk_format
        for disk_format in supported_formats()
        if disk_format.gw_format and disk_format.suffix in browsable_suffixes()
    )
    priority = {
        ".adf": 0,
        ".adm": 1,
        ".ads": 1,
        ".adl": 1,
        ".ssd": 2,
        ".dsd": 2,
        ".st": 3,
        ".d64": 4,
        ".img": 5,
    }
    candidates = tuple(
        sorted(candidates, key=lambda item: (priority[item.suffix], item.gw_format))
    )
    if source.suffix.lower() == ".a2r":
        return candidates

    container_format = detect_image_format(source).disk_format
    if container_format is None:
        return ()
    return tuple(
        disk_format
        for disk_format in candidates
        if disk_format.heads == container_format.heads
        and 0 <= container_format.cylinders - disk_format.cylinders <= 4
    )


def open_browsable_image(
    source: Path,
    work_directory: Path,
    *,
    controller: OperationController | None = None,
) -> BrowsableImage:
    """Open an image directly or decode its tracks to a temporary sector image."""
    suffix = source.suffix.lower()
    if suffix in browsable_suffixes():
        contents = open_image(source)
        disk_format = detect_image_format(source).disk_format
        if disk_format is not None:
            contents = DiskContents(
                contents.volume_label, contents.entries, disk_format.label
            )
        return BrowsableImage(contents, source, disk_format)

    if suffix not in TRACK_CONTAINER_SUFFIXES:
        raise FilesystemError(
            f"Browsing {suffix or 'this image format'} is not supported yet."
        )

    guess = detect_image_format(source)
    candidates = _decode_candidates(source)
    if guess.disk_format is None or not candidates:
        raise FilesystemError(
            f"The track container could not be decoded safely. {guess.explanation}"
        )
    diagnostics: list[str] = []
    for index, disk_format in enumerate(candidates, start=1):
        if controller is not None and controller.cancelled:
            raise FilesystemError("Opening the track container was cancelled.")
        probe = work_directory / f"browse-probe-{index}{disk_format.suffix}"
        probe_result = convert_image(
            source,
            probe,
            disk_format,
            controller=controller,
            timeout=30,
            tracks=f"c=0:h=0-{disk_format.heads - 1}",
        )
        recovered, _ratio = conversion_score(probe_result.diagnostic, disk_format)
        minimum_recovered = max(1, disk_format.sectors_per_track // 2)
        if not probe_result.succeeded or recovered < minimum_recovered:
            diagnostics.append(
                f"{disk_format.label}: "
                f"{probe_result.diagnostic or probe_result.summary}"
            )
            continue
        decoded = work_directory / f"browse-{index}{disk_format.suffix}"
        result = convert_image(
            source,
            decoded,
            disk_format,
            controller=controller,
            timeout=120,
        )
        if not result.succeeded:
            diagnostics.append(
                f"{disk_format.label}: {result.diagnostic or result.summary}"
            )
            continue
        try:
            contents = open_image(decoded)
        except (FilesystemError, OSError) as error:
            diagnostics.append(f"{disk_format.label}: {error}")
            continue
        contents = DiskContents(
            contents.volume_label, contents.entries, disk_format.label
        )
        return BrowsableImage(
            contents,
            decoded,
            disk_format,
            result.diagnostic,
        )
    raise FilesystemError(
        "No supported filesystem could be decoded from the track container."
        + ("\n\n" + "\n".join(diagnostics) if diagnostics else "")
    )
