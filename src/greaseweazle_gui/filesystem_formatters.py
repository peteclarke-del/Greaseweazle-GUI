"""Safe initialisers for filesystems whose on-disk layout is well defined."""

from __future__ import annotations

from pathlib import Path
import struct

from .disk_formats import DiskFormat


class FilesystemFormatError(ValueError):
    pass


def filesystem_support_name(disk_format: DiskFormat) -> str | None:
    if disk_format.gw_format.startswith("atarist."):
        return "Atari TOS FAT12"
    if disk_format.gw_format in {"amiga.amigados", "amiga.amigados_hd"}:
        return "AmigaDOS OFS"
    return None


def initialise_filesystem(
    image_path: Path, disk_format: DiskFormat, volume_label: str = "BLANK"
) -> str:
    """Initialise a supported flat image and return its filesystem name."""
    filesystem = filesystem_support_name(disk_format)
    if filesystem == "Atari TOS FAT12":
        _format_fat12(image_path, disk_format, volume_label)
    elif filesystem == "AmigaDOS OFS":
        _format_amigados(image_path, volume_label)
    else:
        raise FilesystemFormatError(
            "No safe filesystem initialiser is available for this format."
        )
    return filesystem


def _normalise_label(label: str, maximum: int) -> bytes:
    cleaned = "".join(
        character for character in label.strip().upper()
        if character.isalnum() or character in " _-"
    ) or "BLANK"
    return cleaned.encode("ascii", errors="replace")[:maximum]


def _format_fat12(
    image_path: Path, disk_format: DiskFormat, volume_label: str
) -> None:
    data = bytearray(image_path.read_bytes())
    sector_size = 512
    expected = disk_format.track_count * disk_format.sectors_per_track * sector_size
    if disk_format.sectors_per_track <= 0 or len(data) != expected:
        raise FilesystemFormatError("The Atari image has unexpected geometry.")
    total_sectors = len(data) // sector_size
    sectors_per_cluster = 2 if total_sectors >= 640 else 1
    root_entries = 112
    root_sectors = (root_entries * 32 + sector_size - 1) // sector_size
    sectors_per_fat = 1
    while True:
        data_sectors = total_sectors - 1 - 2 * sectors_per_fat - root_sectors
        clusters = data_sectors // sectors_per_cluster
        required = ((clusters + 2) * 3 + 1) // 2
        calculated = (required + sector_size - 1) // sector_size
        if calculated == sectors_per_fat:
            break
        sectors_per_fat = calculated
    if clusters >= 4085:
        raise FilesystemFormatError("This geometry is too large for FAT12.")

    data[:] = b"\0" * len(data)
    boot = memoryview(data)[:sector_size]
    boot[0:3] = b"\x60\x1c\x00"
    boot[3:11] = b"GWGUI   "
    struct.pack_into("<H", boot, 11, sector_size)
    boot[13] = sectors_per_cluster
    struct.pack_into("<H", boot, 14, 1)
    boot[16] = 2
    struct.pack_into("<H", boot, 17, root_entries)
    struct.pack_into("<H", boot, 19, total_sectors)
    media = 0xF9 if total_sectors == 1440 else 0xF8
    boot[21] = media
    struct.pack_into("<H", boot, 22, sectors_per_fat)
    struct.pack_into("<H", boot, 24, disk_format.sectors_per_track)
    struct.pack_into("<H", boot, 26, disk_format.heads)
    boot[36] = 0
    boot[38] = 0x29
    struct.pack_into("<I", boot, 39, 0x47574755)
    label = _normalise_label(volume_label, 11).ljust(11, b" ")
    boot[43:54] = label
    boot[54:62] = b"FAT12   "
    boot[510:512] = b"\x55\xaa"
    for fat_number in range(2):
        offset = (1 + fat_number * sectors_per_fat) * sector_size
        data[offset : offset + 3] = bytes((media, 0xFF, 0xFF))
    image_path.write_bytes(data)


def _amiga_checksum(block: bytearray, checksum_offset: int) -> None:
    struct.pack_into(">I", block, checksum_offset, 0)
    total = sum(
        struct.unpack_from(">I", block, offset)[0]
        for offset in range(0, len(block), 4)
    ) & 0xFFFFFFFF
    struct.pack_into(">I", block, checksum_offset, (-total) & 0xFFFFFFFF)


def _boot_checksum(boot: bytearray) -> None:
    struct.pack_into(">I", boot, 4, 0)
    total = 0
    for offset in range(0, len(boot), 4):
        value = struct.unpack_from(">I", boot, offset)[0]
        previous = total
        total = (total + value) & 0xFFFFFFFF
        if total < previous:
            total = (total + 1) & 0xFFFFFFFF
    struct.pack_into(">I", boot, 4, (~total) & 0xFFFFFFFF)


def _format_amigados(image_path: Path, volume_label: str) -> None:
    data = bytearray(image_path.read_bytes())
    if len(data) not in {901120, 1802240} or len(data) % 512:
        raise FilesystemFormatError("The Amiga image has unexpected geometry.")
    data[:] = b"\0" * len(data)
    block_count = len(data) // 512
    root_number = block_count // 2
    bitmap_number = root_number + 1

    boot = bytearray(1024)
    boot[:4] = b"DOS\0"
    _boot_checksum(boot)
    data[:1024] = boot

    bitmap = bytearray(512)
    for block_number in range(block_count):
        word_offset = 4 + (block_number // 32) * 4
        bit = 31 - (block_number % 32)
        value = struct.unpack_from(">I", bitmap, word_offset)[0]
        struct.pack_into(">I", bitmap, word_offset, value | (1 << bit))
    for used in (0, 1, root_number, bitmap_number):
        word_offset = 4 + (used // 32) * 4
        bit = 31 - (used % 32)
        value = struct.unpack_from(">I", bitmap, word_offset)[0]
        struct.pack_into(">I", bitmap, word_offset, value & ~(1 << bit))
    _amiga_checksum(bitmap, 0)
    data[bitmap_number * 512 : (bitmap_number + 1) * 512] = bitmap

    root = bytearray(512)
    struct.pack_into(">I", root, 0, 2)
    struct.pack_into(">I", root, 12, 72)
    struct.pack_into(">I", root, 312, 0xFFFFFFFF)
    struct.pack_into(">I", root, 316, bitmap_number)
    label = _normalise_label(volume_label, 30)
    root[432] = len(label)
    root[433 : 433 + len(label)] = label
    struct.pack_into(">I", root, 508, 1)
    _amiga_checksum(root, 20)
    data[root_number * 512 : (root_number + 1) * 512] = root
    image_path.write_bytes(data)
