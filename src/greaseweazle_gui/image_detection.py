"""Identify a disk image before writing it to physical media."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from .disk_formats import RAW_FLUX_FORMAT, DiskFormat
from .format_catalog import supported_formats


@dataclass(frozen=True, slots=True)
class ImageFormatGuess:
    disk_format: DiskFormat | None
    method: str
    explanation: str


def _find_format(name: str) -> DiskFormat | None:
    return next((item for item in supported_formats() if item.gw_format == name), None)


def _hfe_format(header: bytes, image_size: int) -> DiskFormat | None:
    """Return container geometry for a valid HxC HFE v1 or v3 header."""
    signature = header[:8]
    if signature not in {b"HXCPICFE", b"HXCHFEV3"} or len(header) < 20:
        return None
    cylinders, heads = header[9], header[10]
    track_list_offset = int.from_bytes(header[18:20], "little") * 512
    if (
        not cylinders
        or heads not in {1, 2}
        or track_list_offset < 512
        or track_list_offset + cylinders * 4 > image_size
    ):
        return None
    version = "v3" if signature == b"HXCHFEV3" else "v1"
    return DiskFormat(
        f"HxC HFE {version}",
        "HxC floppy-emulator track image; write encoded tracks directly",
        "",
        ".hfe",
        cylinders,
        heads,
        0,
        direct_write=True,
    )


def _atari_geometry(header: bytes) -> tuple[int, int, int] | None:
    if len(header) < 64:
        return None
    little = lambda offset, size: int.from_bytes(
        header[offset : offset + size], "little"
    )
    if little(11, 2) != 512:
        return None
    sectors_per_cluster = header[13]
    total_sectors = little(19, 2) or little(32, 4)
    sectors_per_track = little(24, 2)
    heads = little(26, 2)
    if not (
        sectors_per_cluster
        and sectors_per_cluster & (sectors_per_cluster - 1) == 0
        and total_sectors
        and sectors_per_track
        and heads in (1, 2)
    ):
        return None
    track_sectors = sectors_per_track * heads
    if total_sectors % track_sectors:
        return None
    return total_sectors // track_sectors, heads, sectors_per_track


_EXTENSION_DEFAULTS = {
    ".adf": "amiga.amigados",
    ".ssd": "acorn.dfs.ss",
    ".dsd": "acorn.dfs.ds",
    ".adm": "acorn.adfs.160",
    ".ads": "acorn.adfs.320",
    ".adl": "acorn.adfs.640",
    ".do": "apple2.appledos.140",
    ".po": "apple2.prodos.140",
    ".d64": "commodore.1541",
    ".d71": "commodore.1571",
    ".d81": "commodore.1581",
    ".d1m": "commodore.cmd.fd2000.dd",
    ".d2m": "commodore.cmd.fd2000.hd",
    ".d4m": "commodore.cmd.fd4000.ed",
    ".sf7": "sega.sf7000",
}


def detect_image_format(path: Path) -> ImageFormatGuess:
    """Inspect image content, falling back to its filename extension."""
    try:
        size = path.stat().st_size
        with path.open("rb") as image:
            header = image.read(4096)
    except OSError as error:
        return ImageFormatGuess(
            None, "error", f"The image could not be opened: {error}"
        )

    if header[:3] == b"DOS":
        name = {
            80 * 2 * 11 * 512: "amiga.amigados",
            80 * 2 * 22 * 512: "amiga.amigados_hd",
        }.get(size)
        if name and (disk_format := _find_format(name)) is not None:
            return ImageFormatGuess(
                disk_format,
                "content",
                f"AmigaDOS signature and {size // 1024} KB image size",
            )

    geometry = _atari_geometry(header)
    if geometry is not None:
        cylinders, heads, sectors = geometry
        disk_format = next(
            (
                item
                for item in supported_formats()
                if item.gw_format.startswith("atarist.")
                and (item.cylinders, item.heads, item.sectors_per_track)
                == (cylinders, heads, sectors)
            ),
            None,
        )
        if disk_format is not None:
            return ImageFormatGuess(
                disk_format,
                "content",
                f"FAT boot sector: {cylinders} cylinders, {heads} heads, {sectors} sectors/track",
            )

    if hfe_format := _hfe_format(header, size):
        return ImageFormatGuess(
            hfe_format,
            "content",
            f"{hfe_format.label} header: {hfe_format.cylinders} cylinders, "
            f"{hfe_format.heads} {'head' if hfe_format.heads == 1 else 'heads'}; "
            "encoded tracks will be written directly",
        )

    if header[:3] == b"SCP":
        # SCP has 168 track offsets at 0x10. Their indices are physical track
        # numbers (cylinder * 2 + head), so the table tells us the actual range
        # to show while writing without interpreting the flux itself.
        cylinders, heads = RAW_FLUX_FORMAT.cylinders, RAW_FLUX_FORMAT.heads
        if len(header) >= 0x2B0:
            offsets = struct.unpack_from("<168I", header, 0x10)
            populated = [index for index, offset in enumerate(offsets) if offset]
            if populated:
                cylinders = max(populated) // 2 + 1
                heads = 2 if any(index % 2 for index in populated) else 1
        disk_format = DiskFormat(
            RAW_FLUX_FORMAT.label,
            RAW_FLUX_FORMAT.description,
            "",
            ".scp",
            cylinders,
            heads,
            0,
        )
        return ImageFormatGuess(
            disk_format,
            "content",
            f"SCP raw-flux track table: {cylinders} cylinders, {heads} "
            f"{'head' if heads == 1 else 'heads'}; no conversion will be applied",
        )

    if header[:4] in {b"A2R2", b"A2R3"}:
        return ImageFormatGuess(
            RAW_FLUX_FORMAT,
            "content",
            "AppleSauce A2R raw-flux image; no conversion will be applied",
        )

    extension = path.suffix.lower()
    if extension == ".adf":
        name = {
            80 * 2 * 11 * 512: "amiga.amigados",
            80 * 2 * 22 * 512: "amiga.amigados_hd",
        }.get(size, "amiga.amigados")
        if disk_format := _find_format(name):
            return ImageFormatGuess(
                disk_format,
                "extension",
                f"Guessed from .adf extension and {size // 1024} KB image size",
            )
    if extension == ".st":
        size_formats = {
            80 * 1 * 9 * 512: "atarist.360",
            80 * 1 * 10 * 512: "atarist.400",
            80 * 1 * 11 * 512: "atarist.440",
            80 * 2 * 9 * 512: "atarist.720",
            80 * 2 * 10 * 512: "atarist.800",
            80 * 2 * 11 * 512: "atarist.880",
        }
        if (name := size_formats.get(size)) and (disk_format := _find_format(name)):
            return ImageFormatGuess(
                disk_format,
                "extension",
                f"Guessed from .st extension and {size // 1024} KB image size",
            )
    if extension in {".scp", ".a2r"}:
        return ImageFormatGuess(
            RAW_FLUX_FORMAT,
            "extension",
            f"Guessed raw flux from the {extension} filename extension",
        )
    if extension == ".hfe":
        return ImageFormatGuess(
            None,
            "unknown",
            "The .hfe filename does not contain a valid HxC HFE v1 or v3 header.",
        )
    if (name := _EXTENSION_DEFAULTS.get(extension)) and (
        disk_format := _find_format(name)
    ):
        return ImageFormatGuess(
            disk_format,
            "extension",
            f"Guessed from the {extension} filename extension",
        )
    return ImageFormatGuess(
        None,
        "unknown",
        "The image contents and filename extension did not identify a format.",
    )
