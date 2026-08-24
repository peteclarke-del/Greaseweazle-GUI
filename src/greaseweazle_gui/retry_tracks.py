"""Selective recovery of damaged sector-image track sides."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .disk_formats import DiskFormat
from .operation import OperationController
from .read_disk import ReadProgress, read_disk
from .track_health import TrackCondition, TrackHealthReport


@dataclass(frozen=True, slots=True)
class RetryTracksResult:
    succeeded: bool
    summary: str
    diagnostic: str = ""
    progress: tuple[ReadProgress, ...] = ()


def retry_damaged_tracks(
    image_path: Path,
    disk_format: DiskFormat,
    report: TrackHealthReport,
    *,
    progress: Callable[[ReadProgress], None] | None = None,
    controller: OperationController | None = None,
    revolutions: int = 3,
    retries: int = 8,
    seek_retries: int = 2,
    drive: str | None = None,
) -> RetryTracksResult:
    """Re-read only damaged track sides and atomically merge recovered sectors.

    Flat ADF/ST images store one fixed-size sector block per cylinder/head. A
    temporary partial read is therefore safe to splice into a copy; the source
    image is replaced only after every requested read has completed.
    """
    damaged = tuple(
        track for track in report.tracks if track.condition is TrackCondition.DAMAGED
    )
    if not damaged:
        return RetryTracksResult(True, "There are no damaged tracks to retry.")
    if image_path.suffix.lower() not in {".adf", ".st"}:
        return RetryTracksResult(
            False, "Selective retry is available only for flat ADF and ST images."
        )
    if disk_format.sectors_per_track <= 0:
        return RetryTracksResult(False, "This format has no fixed sector geometry.")
    track_size = disk_format.sectors_per_track * 512
    expected_size = disk_format.track_count * track_size
    try:
        original = image_path.read_bytes()
    except OSError as error:
        return RetryTracksResult(
            False, "The captured image could not be opened.", str(error)
        )
    if len(original) != expected_size:
        return RetryTracksResult(
            False,
            "The image size does not match the selected format geometry.",
            f"Expected {expected_size} bytes, found {len(original)}.",
        )

    merged = bytearray(original)
    updates: list[ReadProgress] = []
    diagnostics: list[str] = []
    with tempfile.TemporaryDirectory(
        prefix=".greaseweazle-retry-", dir=image_path.parent
    ) as temporary:
        temporary_path = Path(temporary)
        for number, track in enumerate(damaged, start=1):
            if controller is not None and controller.cancelled:
                return RetryTracksResult(
                    False,
                    "Track retry was cancelled safely.",
                    "\n".join(diagnostics),
                    tuple(updates),
                )
            partial = (
                temporary_path
                / f"track-{track.cylinder}-{track.head}{image_path.suffix}"
            )

            def forward(
                update: ReadProgress,
                completed: int = number - 1,
                track_number: int = number,
            ) -> None:
                adjusted = ReadProgress(
                    fraction=min((completed + update.fraction) / len(damaged), 1.0),
                    cylinder=update.cylinder,
                    head=update.head,
                    track_number=track_number,
                    track_count=len(damaged),
                    sectors_read=update.sectors_read,
                    sectors_total=update.sectors_total,
                    retry=update.retry,
                    message=update.message,
                )
                updates.append(adjusted)
                if progress is not None:
                    progress(adjusted)

            result = read_disk(
                disk_format,
                partial,
                tracks=f"c={track.cylinder}:h={track.head}",
                progress=forward,
                controller=controller,
                revolutions=revolutions,
                retries=retries,
                seek_retries=seek_retries,
                drive=drive,
            )
            if result.diagnostic:
                diagnostics.append(result.diagnostic)
            if not result.succeeded:
                return RetryTracksResult(
                    False, result.summary, "\n".join(diagnostics), tuple(updates)
                )
            try:
                partial_data = partial.read_bytes()
            except OSError as error:
                return RetryTracksResult(
                    False,
                    "A retried track could not be loaded.",
                    str(error),
                    tuple(updates),
                )
            index = track.cylinder * disk_format.heads + track.head
            offset = index * track_size
            if len(partial_data) == expected_size:
                replacement = partial_data[offset : offset + track_size]
            elif len(partial_data) == track_size:
                replacement = partial_data
            else:
                return RetryTracksResult(
                    False,
                    "Greaseweazle returned an unexpected partial-image layout.",
                    f"Expected {track_size} or {expected_size} bytes, found {len(partial_data)}.",
                    tuple(updates),
                )
            merged[offset : offset + track_size] = replacement

        staged = temporary_path / image_path.name
        try:
            staged.write_bytes(merged)
            os.replace(staged, image_path)
        except OSError as error:
            return RetryTracksResult(
                False,
                "The recovered image could not be saved.",
                str(error),
                tuple(updates),
            )
    return RetryTracksResult(
        True,
        f"Retried {len(damaged)} damaged track side(s).",
        "\n".join(diagnostics),
        tuple(updates),
    )
