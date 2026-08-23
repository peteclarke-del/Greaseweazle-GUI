"""Discover and organise formats supported by the installed Greaseweazle."""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path
import re
import shutil
import subprocess

from .disk_formats import DISK_FORMATS, DiskFormat


_FORMAT_BLOCK = re.compile(
    r"FORMAT options:\s*(.*?)\n\s*Supported file suffixes:", re.DOTALL
)
_FORMAT_NAME = re.compile(r"\b[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+\b")

_MANUFACTURERS = {
    "acorn": "Acorn",
    "akai": "Akai",
    "amiga": "Amiga",
    "apple2": "Apple",
    "atari": "Atari",
    "atarist": "Atari",
    "coco": "Tandy / Radio Shack",
    "commodore": "Commodore",
    "datageneral": "Data General",
    "dec": "DEC",
    "dragon": "Dragon Data",
    "eagle": "Eagle Computer",
    "ensoniq": "Ensoniq",
    "epson": "Epson",
    "gem": "GEM",
    "hp": "Hewlett-Packard",
    "ibm": "IBM",
    "kaypro": "Kaypro",
    "luxor": "Luxor",
    "mac": "Apple",
    "micropolis": "Micropolis",
    "mm1": "IMS MM/1",
    "msx": "MSX",
    "northstar": "North Star",
    "occ1": "Osborne",
    "olivetti": "Olivetti",
    "pc98": "NEC PC-98",
    "raw": "Raw formats",
    "sci": "Sequential Circuits",
    "sega": "Sega",
    "thomson": "Thomson",
    "tsc": "Technical Systems Consultants",
    "xerox": "Xerox",
    "zx": "Sinclair ZX Spectrum",
}

_GEOMETRY_SCRIPT = """
import json, sys
from greaseweazle.codec.codec import get_diskdef
result = {}
for name in sys.argv[1:]:
    disk = get_diskdef(name)
    if disk is None:
        continue
    sectors = [
        getattr(disk.mk_track(cylinder, head), 'nsec', 0) or 0
        for cylinder, head in disk.track_map
    ]
    result[name] = [disk.cyls, disk.heads, max(sectors, default=0)]
print(json.dumps(result))
"""


def parse_format_names(help_text: str) -> tuple[str, ...]:
    """Parse the format block printed by ``gw read --help``."""
    match = _FORMAT_BLOCK.search(help_text)
    if match is None:
        return ()
    return tuple(sorted(set(_FORMAT_NAME.findall(match.group(1)))))


def manufacturer_name(format_name: str) -> str:
    prefix = format_name.partition(".")[0]
    return _MANUFACTURERS.get(prefix, prefix.replace("_", " ").title())


def format_menu_label(format_name: str) -> str:
    prefix, _separator, detail = format_name.partition(".")
    qualifiers = {
        "apple2": "Apple II",
        "mac": "Macintosh",
        "atari": "8-bit",
        "atarist": "ST",
    }
    if prefix in qualifiers:
        return f"{qualifiers[prefix]} — {detail}"
    return detail


def _image_suffix(format_name: str) -> str:
    if format_name.startswith("raw."):
        return ".scp"
    if format_name == "epson.qx10.logo":
        # This definition deliberately leaves several tracks unformatted.
        # A flat IMG cannot represent that layout, while SCP can.
        return ".scp"
    if format_name.startswith("amiga."):
        return ".adf"
    if format_name.startswith("atarist."):
        return ".st"
    if format_name.startswith("apple2.appledos.") or format_name.startswith("apple2.nofs."):
        return ".do"
    if format_name.startswith("apple2.prodos."):
        return ".po"
    if format_name == "acorn.dfs.ss" or format_name == "acorn.dfs.ss80":
        return ".ssd"
    if format_name == "acorn.dfs.ds" or format_name == "acorn.dfs.ds80":
        return ".dsd"
    if format_name == "acorn.adfs.160":
        return ".adm"
    if format_name == "acorn.adfs.320":
        return ".ads"
    if format_name == "acorn.adfs.640":
        return ".adl"
    commodore_suffixes = {
        "commodore.1541": ".d64",
        "commodore.1571": ".d71",
        "commodore.1581": ".d81",
        "commodore.cmd.fd2000.dd": ".d1m",
        "commodore.cmd.fd2000.hd": ".d2m",
        "commodore.cmd.fd4000.ed": ".d4m",
    }
    if format_name in commodore_suffixes:
        return commodore_suffixes[format_name]
    if format_name == "sega.sf7000":
        return ".sf7"
    return ".img"


def _query_geometry(executable: str, names: tuple[str, ...]) -> dict[str, tuple[int, int, int]]:
    try:
        resolved = Path(executable).resolve()
        first_line = resolved.read_text(errors="replace").splitlines()[0]
        interpreter = first_line[2:].strip() if first_line.startswith("#!") else ""
        if not interpreter:
            return {}
        completed = subprocess.run(
            [interpreter, "-c", _GEOMETRY_SCRIPT, *names],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            return {}
        raw = json.loads(completed.stdout)
        return {
            name: (int(values[0]), int(values[1]), int(values[2]))
            for name, values in raw.items()
        }
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return {}


@lru_cache(maxsize=1)
def supported_formats() -> tuple[DiskFormat, ...]:
    """Return every format advertised by the installed ``gw`` command."""
    executable = shutil.which("gw")
    if executable is None:
        return DISK_FORMATS
    try:
        completed = subprocess.run(
            [executable, "read", "--help"],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
        )
        names = parse_format_names(f"{completed.stdout}\n{completed.stderr}")
    except (OSError, subprocess.TimeoutExpired):
        names = ()
    if not names:
        return DISK_FORMATS

    known = {item.gw_format: item for item in DISK_FORMATS}
    geometry = _query_geometry(executable, names)
    formats: list[DiskFormat] = []
    for name in names:
        if name in known:
            formats.append(known[name])
            continue
        cylinders, heads, sectors = geometry.get(name, (80, 2, 0))
        formats.append(
            DiskFormat(
                name,
                f"Greaseweazle format {name}",
                name,
                _image_suffix(name),
                cylinders,
                heads,
                sectors,
            )
        )
    return tuple(formats)


def grouped_formats() -> tuple[tuple[str, tuple[DiskFormat, ...]], ...]:
    groups: dict[str, list[DiskFormat]] = defaultdict(list)
    for disk_format in supported_formats():
        groups[manufacturer_name(disk_format.gw_format)].append(disk_format)
    return tuple(
        (
            manufacturer,
            tuple(sorted(formats, key=lambda item: format_menu_label(item.gw_format).casefold())),
        )
        for manufacturer, formats in sorted(groups.items(), key=lambda item: item[0].casefold())
    )
