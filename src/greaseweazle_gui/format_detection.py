"""Automatic disk-format detection from a single raw flux capture."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .disk_formats import DISK_FORMATS, DiskFormat
from .filesystems import DiskContents, FilesystemError, open_image
from .operation import OperationController

_TRACK_SECTORS = re.compile(r"^T(\d+)\.(\d+):.*?\((\d+)/(\d+) sectors\)")


def _run_conversion(
    command: list[str],
    timeout: float,
    controller: OperationController | None,
) -> subprocess.CompletedProcess[str]:
    if controller is None:
        return subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    controller.register(process)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    finally:
        controller.unregister(process)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


@dataclass(frozen=True, slots=True)
class DetectionProgress:
    current: int
    total: int
    label: str


@dataclass(frozen=True, slots=True)
class DetectionResult:
    disk_format: DiskFormat | None
    image_path: Path
    contents: DiskContents | None
    confidence: float
    diagnostic: str
    classification: str = "recognised"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    disk_format: DiskFormat | None
    confidence: float
    diagnostic: str


def _atari_boot_geometry(image_path: Path) -> tuple[int, int, int] | None:
    """Return cylinders, heads and sectors/track from a plausible FAT BPB."""
    try:
        boot = image_path.read_bytes()[:512]
    except OSError:
        return None
    if len(boot) < 512:
        return None
    little = lambda offset, size: int.from_bytes(boot[offset : offset + size], "little")
    bytes_per_sector = little(11, 2)
    sectors_per_cluster = boot[13]
    reserved = little(14, 2)
    fat_count = boot[16]
    root_entries = little(17, 2)
    total_sectors = little(19, 2) or little(32, 4)
    sectors_per_track = little(24, 2)
    heads = little(26, 2)
    if not (
        bytes_per_sector == 512
        and sectors_per_cluster > 0
        and sectors_per_cluster & (sectors_per_cluster - 1) == 0
        and reserved > 0
        and fat_count > 0
        and root_entries > 0
        and total_sectors > 0
        and sectors_per_track > 0
        and heads in (1, 2)
    ):
        return None
    track_size = heads * sectors_per_track
    if total_sectors % track_size:
        return None
    return total_sectors // track_size, heads, sectors_per_track


def probe_format(
    raw_probe: Path,
    work_directory: Path,
    candidates: tuple[DiskFormat, ...] = DISK_FORMATS,
    controller: OperationController | None = None,
) -> ProbeResult:
    """Identify a standard disk from cylinder zero without a full capture."""
    executable = shutil.which("gw")
    if executable is None:
        return ProbeResult(None, 0, "The ‘gw’ tool is unavailable.")

    scored_candidates: list[tuple[float, int, DiskFormat, str]] = []
    diagnostics: list[str] = []
    for index, disk_format in enumerate(candidates, start=1):
        if controller is not None and controller.cancelled:
            return ProbeResult(None, 0, "Format detection was cancelled.")
        output_path = work_directory / f"initial-probe-{index}{disk_format.suffix}"
        try:
            completed = _run_conversion(
                [
                    executable,
                    "convert",
                    "--tracks",
                    f"c=0:h=0-{disk_format.heads - 1}",
                    "--format",
                    disk_format.gw_format,
                    str(raw_probe),
                    str(output_path),
                ],
                60,
                controller,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            diagnostics.append(f"{disk_format.label}: {error}")
            continue
        output = "\n".join(
            part for part in (completed.stdout, completed.stderr) if part
        ).strip()
        decoded, _full_disk_ratio = conversion_score(output, disk_format)
        expected_probe = disk_format.heads * disk_format.sectors_per_track
        ratio = min(decoded / expected_probe, 1.0) if expected_probe else 0.0
        if completed.returncode != 0 or decoded == 0 or not output_path.is_file():
            diagnostics.append(
                f"{disk_format.label}: no usable sectors on cylinder zero"
            )
            continue

        if disk_format.gw_format.startswith("atarist."):
            geometry = _atari_boot_geometry(output_path)
            expected = (
                disk_format.cylinders,
                disk_format.heads,
                disk_format.sectors_per_track,
            )
            if geometry != expected:
                diagnostics.append(
                    f"{disk_format.label}: boot geometry was {geometry or 'not valid FAT'}"
                )
                continue
            confidence = ratio
        else:
            try:
                signature = output_path.read_bytes()[:4]
            except OSError:
                signature = b""
            if len(signature) != 4 or signature[:3] != b"DOS" or signature[3] > 7:
                diagnostics.append(f"{disk_format.label}: AmigaDOS signature not found")
                continue
            confidence = ratio

        scored_candidates.append((confidence, decoded, disk_format, output))

    if not scored_candidates:
        return ProbeResult(
            None,
            0,
            "\n".join(diagnostics)
            or "Cylinder zero did not identify a supported format.",
        )
    scored_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    confidence, _decoded, disk_format, output = scored_candidates[0]
    if confidence < 0.75:
        return ProbeResult(
            None, confidence, "The cylinder-zero result was not reliable.\n" + output
        )
    return ProbeResult(disk_format, confidence, output)


def conversion_score(output: str, disk_format: DiskFormat) -> tuple[int, float]:
    """Return unique decoded sectors and their proportion of expected sectors."""
    tracks: dict[tuple[int, int], int] = {}
    for line in output.splitlines():
        match = _TRACK_SECTORS.search(line)
        if match is None:
            continue
        cylinder, head = int(match.group(1)), int(match.group(2))
        if cylinder >= disk_format.cylinders or head >= disk_format.heads:
            continue
        recovered = int(match.group(3))
        key = (cylinder, head)
        tracks[key] = max(tracks.get(key, 0), recovered)
    decoded = sum(tracks.values())
    expected = disk_format.track_count * disk_format.sectors_per_track
    return decoded, decoded / expected if expected else 0.0


def detect_format(
    raw_image: Path,
    work_directory: Path,
    progress: Callable[[DetectionProgress], None] | None = None,
    candidates: tuple[DiskFormat, ...] = DISK_FORMATS,
    controller: OperationController | None = None,
) -> DetectionResult:
    """Try supported decoders and select the strongest valid filesystem."""
    executable = shutil.which("gw")
    if executable is None:
        return DetectionResult(
            None, raw_image, None, 0, "The ‘gw’ tool is unavailable."
        )

    # Probe a few representative tracks first. Fully decoding every candidate
    # makes format identification unnecessarily slow on multi-revolution SCPs.
    probes: list[tuple[int, float, int, DiskFormat]] = []
    diagnostics: list[str] = []
    total = len(candidates) + 1
    for index, disk_format in enumerate(candidates, start=1):
        if controller is not None and controller.cancelled:
            return DetectionResult(
                None, raw_image, None, 0, "Format detection was cancelled.", "cancelled"
            )
        if progress is not None:
            progress(DetectionProgress(index, total, disk_format.label))
        output_path = work_directory / f"probe-{index}{disk_format.suffix}"
        probe_cylinders = sorted(
            {0, disk_format.cylinders // 2, disk_format.cylinders - 1}
        )
        tracks = ",".join(str(cylinder) for cylinder in probe_cylinders)
        try:
            completed = _run_conversion(
                [
                    executable,
                    "convert",
                    "--tracks",
                    f"c={tracks}:h=0-{disk_format.heads - 1}",
                    "--format",
                    disk_format.gw_format,
                    str(raw_image),
                    str(output_path),
                ],
                120,
                controller,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            diagnostics.append(f"{disk_format.label}: {error}")
            continue
        output = "\n".join(
            part for part in (completed.stdout, completed.stderr) if part
        ).strip()
        decoded, ratio = conversion_score(output, disk_format)
        if completed.returncode != 0 or decoded == 0:
            diagnostics.append(f"{disk_format.label}: no usable sectors")
            continue
        probes.append((decoded, ratio, index, disk_format))

    if not probes:
        return DetectionResult(
            None,
            raw_image,
            None,
            0,
            "\n".join(diagnostics) or "No supported decoder recognised the disk.",
            "unrecognised",
        )

    probes.sort(key=lambda candidate: (candidate[0], candidate[1]), reverse=True)
    best_ratio = 0.0
    for _probe_count, _probe_ratio, index, disk_format in probes:
        if controller is not None and controller.cancelled:
            return DetectionResult(
                None,
                raw_image,
                None,
                best_ratio,
                "Format detection was cancelled.",
                "cancelled",
            )
        if progress is not None:
            progress(DetectionProgress(total, total, f"Confirming {disk_format.label}"))
        image_path = work_directory / f"detected-{index}{disk_format.suffix}"
        try:
            completed = _run_conversion(
                [
                    executable,
                    "convert",
                    "--format",
                    disk_format.gw_format,
                    str(raw_image),
                    str(image_path),
                ],
                120,
                controller,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            diagnostics.append(f"{disk_format.label} confirmation: {error}")
            continue
        output = "\n".join(
            part for part in (completed.stdout, completed.stderr) if part
        ).strip()
        decoded, ratio = conversion_score(output, disk_format)
        best_ratio = max(best_ratio, ratio)
        if completed.returncode != 0 or ratio < 0.5 or not image_path.is_file():
            diagnostics.append(
                f"{disk_format.label}: full decode recovered {ratio:.0%} of sectors"
            )
            continue
        try:
            contents = open_image(image_path)
        except (FilesystemError, OSError) as error:
            diagnostics.append(
                f"{disk_format.label}: {decoded} sectors, filesystem rejected ({error})"
            )
            continue
        contents = DiskContents(
            contents.volume_label, contents.entries, disk_format.label
        )
        return DetectionResult(
            disk_format,
            image_path,
            contents,
            ratio,
            output,
        )

    return DetectionResult(
        None,
        raw_image,
        None,
        best_ratio,
        "\n".join(diagnostics) or "No supported filesystem was found.",
        "unrecognised",
    )
