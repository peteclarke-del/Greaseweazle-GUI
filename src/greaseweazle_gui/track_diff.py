"""Work out which physical tracks differ between two versions of a sector image."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

_SCRIPT = """
import json, sys
from greaseweazle.codec.codec import get_diskdef
from greaseweazle.image.img import IMG
disk = get_diskdef(sys.argv[1])
size = int(sys.argv[2])
img = IMG("x", disk)
sequential = getattr(img, "sequential", False)
out, pos = [], 0
for cyl, head in img.track_list():
    track = disk.mk_track(cyl, head)
    if track is None:
        continue
    length = track.set_img_track(bytes(size - pos))
    out.append([cyl, head, pos, length])
    pos += length
print(json.dumps(out))
"""


def _gw_python() -> str:
    executable = shutil.which("gw")
    if executable is not None:
        try:
            with open(executable, "rb") as handle:
                first = handle.readline().decode("utf-8", "replace").strip()
            if first.startswith("#!"):
                return first[2:].split()[0]
        except OSError:
            pass
    return sys.executable


def track_layout(gw_format: str, image_size: int) -> list[tuple[int, int, int, int]]:
    """Return (cylinder, head, offset, length) for each track of the image."""
    completed = subprocess.run(
        [_gw_python(), "-c", _SCRIPT, gw_format, str(image_size)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(completed.stderr.strip() or "Could not map image tracks.")
    return [tuple(item) for item in json.loads(completed.stdout)]  # type: ignore[misc]


def changed_tracks(gw_format: str, old: bytes, new: bytes) -> list[tuple[int, int]]:
    """Return the (cylinder, head) pairs whose image data changed."""
    if len(old) != len(new):
        raise ValueError("The image size changed unexpectedly.")
    return [
        (cyl, head)
        for cyl, head, offset, length in track_layout(gw_format, len(new))
        if old[offset : offset + length] != new[offset : offset + length]
    ]


def track_specs(tracks: list[tuple[int, int]]) -> list[str]:
    """Group changed tracks into gw ``--tracks`` arguments, one per cylinder."""
    by_cylinder: dict[int, list[int]] = {}
    for cyl, head in tracks:
        by_cylinder.setdefault(cyl, []).append(head)
    return [
        f"c={cyl}:h={','.join(str(h) for h in sorted(heads))}"
        for cyl, heads in sorted(by_cylinder.items())
    ]
