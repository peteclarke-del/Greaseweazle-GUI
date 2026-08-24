"""Auditable sidecar metadata for preservation captures."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .disk_formats import DiskFormat
from .read_disk import ReadResult


def write_capture_report(
    image_path: Path,
    disk_format: DiskFormat,
    result: ReadResult,
    *,
    profile_name: str,
    device_model: str,
    device_port: str,
) -> Path:
    """Write a JSON report beside an image using an atomic replacement."""
    digest = hashlib.sha256()
    with image_path.open("rb") as image:
        while chunk := image.read(1024 * 1024):
            digest.update(chunk)
    report_path = image_path.with_suffix(f"{image_path.suffix}.capture.json")
    payload = {
        "schema": "com.github.pclarke.GreaseweazleGUI.capture.v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "image": {
            "filename": image_path.name,
            "bytes": image_path.stat().st_size,
            "sha256": digest.hexdigest(),
        },
        "format": {
            "greaseweazle": disk_format.gw_format or "raw.scp",
            "label": disk_format.label,
            "cylinders": disk_format.cylinders,
            "heads": disk_format.heads,
            "sectors_per_track": disk_format.sectors_per_track,
        },
        "capture_profile": profile_name,
        "device": {"model": device_model, "port": device_port},
        "track_reads": [asdict(update) for update in result.progress],
        "diagnostic": result.diagnostic,
    }
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{report_path.name}.",
        suffix=".tmp",
        dir=report_path.parent,
        delete=False,
    ) as temporary:
        json.dump(payload, temporary, indent=2, ensure_ascii=False)
        temporary.write("\n")
        staged = Path(temporary.name)
    try:
        os.replace(staged, report_path)
    except OSError:
        staged.unlink(missing_ok=True)
        raise
    return report_path
