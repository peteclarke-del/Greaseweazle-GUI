"""Read-only, lazy access to filesystems in supported disk images."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
import struct


class FilesystemError(ValueError):
    """Raised when an image is unsupported, damaged, or unsafe to extract."""


@dataclass(slots=True)
class ImageEntry:
    """A directory entry backed by data in the disk image."""

    name: str
    is_directory: bool
    size: int = 0
    children: tuple[ImageEntry, ...] = ()
    _reader: Callable[[], bytes] | None = field(default=None, repr=False)

    def read_bytes(self) -> bytes:
        if self.is_directory or self._reader is None:
            raise FilesystemError(f"{self.name} is not a file.")
        return self._reader()


@dataclass(frozen=True, slots=True)
class DiskContents:
    volume_label: str
    entries: tuple[ImageEntry, ...]
    format_label: str = ""


def open_image(image_path: Path) -> DiskContents:
    """Read directory metadata without extracting file contents."""
    data = image_path.read_bytes()
    suffix = image_path.suffix.lower()
    if suffix == ".st":
        return _Fat12Image(data).open()
    if suffix == ".adf":
        return _AmigaImage(data).open()
    raise FilesystemError(f"Browsing {suffix or 'this image format'} is not supported yet.")


def materialize_entries(entries: Iterable[ImageEntry], destination: Path) -> None:
    """Write selected image entries to real paths for external file transfer."""
    destination.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        target = destination / entry.name
        if entry.is_directory:
            materialize_entries(entry.children, target)
        elif not target.exists():
            target.write_bytes(entry.read_bytes())


def extract_image(image_path: Path, destination: Path) -> str:
    """Compatibility helper that explicitly extracts the entire image."""
    contents = open_image(image_path)
    materialize_entries(contents.entries, destination)
    return contents.volume_label


def _safe_name(name: str, fallback: str = "unnamed") -> str:
    cleaned = name.replace("/", "_").replace("\\", "_").replace("\0", "").strip()
    if cleaned in {"", ".", ".."}:
        return fallback
    return cleaned


def _unique_name(name: str, used: set[str]) -> str:
    candidate = _safe_name(name)
    if candidate.casefold() not in used:
        used.add(candidate.casefold())
        return candidate
    path = Path(candidate)
    stem, suffix = path.stem, path.suffix
    counter = 2
    while True:
        alternative = f"{stem} ({counter}){suffix}"
        if alternative.casefold() not in used:
            used.add(alternative.casefold())
            return alternative
        counter += 1


class _Fat12Image:
    def __init__(self, data: bytes) -> None:
        self.data = data
        if len(data) < 512:
            raise FilesystemError("The Atari ST image is too small to contain a filesystem.")
        self.bytes_per_sector = struct.unpack_from("<H", data, 11)[0]
        self.sectors_per_cluster = data[13]
        self.reserved_sectors = struct.unpack_from("<H", data, 14)[0]
        self.fat_count = data[16]
        self.root_entries = struct.unpack_from("<H", data, 17)[0]
        total16 = struct.unpack_from("<H", data, 19)[0]
        self.total_sectors = total16 or struct.unpack_from("<I", data, 32)[0]
        self.sectors_per_fat = struct.unpack_from("<H", data, 22)[0]
        if (
            self.bytes_per_sector not in {128, 256, 512, 1024, 2048, 4096}
            or not self.sectors_per_cluster
            or not self.reserved_sectors
            or not self.fat_count
            or not self.root_entries
            or not self.sectors_per_fat
        ):
            raise FilesystemError("The Atari ST image does not contain a valid FAT12 boot sector.")
        declared_size = self.total_sectors * self.bytes_per_sector
        if not self.total_sectors or declared_size > len(data):
            raise FilesystemError("The Atari ST image is truncated or has invalid geometry.")

        self.fat_offset = self.reserved_sectors * self.bytes_per_sector
        root_sectors = (
            self.root_entries * 32 + self.bytes_per_sector - 1
        ) // self.bytes_per_sector
        self.root_offset = (
            self.reserved_sectors + self.fat_count * self.sectors_per_fat
        ) * self.bytes_per_sector
        self.root_size = self.root_entries * 32
        self.data_offset = self.root_offset + root_sectors * self.bytes_per_sector
        fat_end = self.fat_offset + self.sectors_per_fat * self.bytes_per_sector
        if fat_end > len(data) or self.root_offset + self.root_size > len(data):
            raise FilesystemError("The Atari ST filesystem structures are outside the image.")
        self.fat = data[self.fat_offset:fat_end]

    def open(self) -> DiskContents:
        label = "Atari ST disk"
        boot_label = self.data[43:54].decode("latin-1", errors="replace").strip(" \0")
        if boot_label:
            label = boot_label
        root = self.data[self.root_offset : self.root_offset + self.root_size]
        entries = self._read_directory(root, set(), depth=0, current_cluster=None)
        return DiskContents(label, entries, "Atari ST FAT12")

    def _next_cluster(self, cluster: int) -> int:
        offset = cluster + cluster // 2
        if offset + 2 > len(self.fat):
            raise FilesystemError("A FAT chain points beyond the allocation table.")
        value = int.from_bytes(self.fat[offset : offset + 2], "little")
        return (value >> 4) & 0xFFF if cluster & 1 else value & 0xFFF

    def _cluster_chain(self, first: int) -> list[int]:
        if first < 2:
            return []
        chain: list[int] = []
        seen: set[int] = set()
        cluster = first
        maximum = (len(self.data) - self.data_offset) // (
            self.bytes_per_sector * self.sectors_per_cluster
        ) + 1
        while 2 <= cluster < 0xFF8:
            if cluster in seen or cluster > maximum + 1:
                raise FilesystemError("The disk contains a looping or invalid FAT chain.")
            seen.add(cluster)
            chain.append(cluster)
            cluster = self._next_cluster(cluster)
            if cluster == 0xFF7:
                raise FilesystemError("A file uses a bad disk cluster.")
        return chain

    def _read_chain(self, first: int) -> bytes:
        cluster_size = self.bytes_per_sector * self.sectors_per_cluster
        chunks = []
        for cluster in self._cluster_chain(first):
            offset = self.data_offset + (cluster - 2) * cluster_size
            end = offset + cluster_size
            if end > len(self.data):
                raise FilesystemError("A file extends beyond the end of the disk image.")
            chunks.append(self.data[offset:end])
        return b"".join(chunks)

    @staticmethod
    def _short_name(entry: bytes) -> str:
        base = entry[:8].decode("cp437", errors="replace").rstrip()
        extension = entry[8:11].decode("cp437", errors="replace").rstrip()
        return f"{base}.{extension}" if extension else base

    def _read_directory(
        self,
        entries: bytes,
        visited: set[int],
        depth: int,
        current_cluster: int | None,
    ) -> tuple[ImageEntry, ...]:
        if depth > 64:
            raise FilesystemError("The disk directory tree is too deeply nested.")
        long_name_parts: list[str] = []
        result: list[ImageEntry] = []
        used_names: set[str] = set()
        for offset in range(0, len(entries) - 31, 32):
            entry = entries[offset : offset + 32]
            if entry[0] == 0:
                break
            if entry[0] == 0xE5:
                long_name_parts.clear()
                continue
            attributes = entry[11]
            if attributes == 0x0F:
                raw_name = entry[1:11] + entry[14:26] + entry[28:32]
                part = raw_name.decode("utf-16le", errors="ignore").rstrip("\uffff\0")
                long_name_parts.insert(0, part)
                continue
            if attributes & 0x08:
                long_name_parts.clear()
                continue
            name = "".join(long_name_parts) or self._short_name(entry)
            long_name_parts.clear()
            if name in {".", ".."}:
                continue
            name = _unique_name(name, used_names)
            cluster = struct.unpack_from("<H", entry, 26)[0]
            size = struct.unpack_from("<I", entry, 28)[0]
            if attributes & 0x10:
                # Some Atari formatters encode '.' as an all-space 8.3 name.
                # The cluster pointer is the reliable way to recognise it.
                if cluster == 0 or cluster == current_cluster:
                    continue
                if cluster in visited:
                    raise FilesystemError("The disk contains a recursive directory chain.")
                visited.add(cluster)
                children = self._read_directory(
                    self._read_chain(cluster), visited, depth + 1, cluster
                )
                result.append(ImageEntry(name, True, children=children))
            else:
                def read_file(first: int = cluster, length: int = size, filename: str = name) -> bytes:
                    content = self._read_chain(first)
                    if length > len(content):
                        raise FilesystemError(
                            f"{filename} is longer than its cluster chain."
                        )
                    return content[:length]

                result.append(ImageEntry(name, False, size=size, _reader=read_file))
        return tuple(result)


class _AmigaImage:
    BLOCK_SIZE = 512

    def __init__(self, data: bytes) -> None:
        self.data = data
        if len(data) < self.BLOCK_SIZE * 4 or len(data) % self.BLOCK_SIZE:
            raise FilesystemError("The Amiga image has an invalid size.")
        if data[:3] != b"DOS" or data[3] > 7:
            raise FilesystemError("The image is not an AmigaDOS OFS or FFS disk.")
        self.ffs = bool(data[3] & 1)
        self.long_names = data[3] >= 6
        self.block_count = len(data) // self.BLOCK_SIZE
        self.root_block = self.block_count // 2
        root = self._block(self.root_block)
        if self._long(root, 0, signed=True) != 2 or self._long(root, 508, signed=True) != 1:
            raise FilesystemError("The AmigaDOS root block is missing or damaged.")

    @staticmethod
    def _long(block: bytes, offset: int, signed: bool = False) -> int:
        return int.from_bytes(block[offset : offset + 4], "big", signed=signed)

    def _block(self, number: int) -> bytes:
        if number <= 0 or number >= self.block_count:
            raise FilesystemError("An AmigaDOS block pointer is outside the image.")
        offset = number * self.BLOCK_SIZE
        return self.data[offset : offset + self.BLOCK_SIZE]

    def _name(self, block: bytes, *, root: bool = False) -> str:
        offset = 432 if root or not self.long_names else 328
        maximum = 30 if root or not self.long_names else 107
        length = min(block[offset], maximum)
        return block[offset + 1 : offset + 1 + length].decode(
            "latin-1", errors="replace"
        )

    def open(self) -> DiskContents:
        root = self._block(self.root_block)
        label = self._name(root, root=True) or "Amiga disk"
        entries = self._read_directory(root, {self.root_block}, depth=0)
        filesystem = "AmigaDOS FFS" if self.ffs else "AmigaDOS OFS"
        return DiskContents(label, entries, filesystem)

    def _children(self, directory: bytes) -> list[tuple[int, bytes]]:
        secondary_type = self._long(directory, 508, signed=True)
        table_size = min(self._long(directory, 12), 72) if secondary_type == 1 else 72
        children: list[tuple[int, bytes]] = []
        seen: set[int] = set()
        for index in range(table_size):
            pointer = self._long(directory, 24 + index * 4)
            while pointer:
                if pointer in seen:
                    raise FilesystemError("The AmigaDOS directory contains a hash-chain loop.")
                seen.add(pointer)
                block = self._block(pointer)
                children.append((pointer, block))
                pointer = self._long(block, 496)
        return children

    def _read_directory(
        self, directory: bytes, visited: set[int], depth: int
    ) -> tuple[ImageEntry, ...]:
        if depth > 64:
            raise FilesystemError("The disk directory tree is too deeply nested.")
        result: list[ImageEntry] = []
        used_names: set[str] = set()
        for number, block in self._children(directory):
            secondary_type = self._long(block, 508, signed=True)
            name = _unique_name(
                _safe_name(self._name(block), f"block-{number}"), used_names
            )
            if secondary_type == 2:
                if number in visited:
                    raise FilesystemError("The AmigaDOS disk contains a recursive directory.")
                visited.add(number)
                children = self._read_directory(block, visited, depth + 1)
                result.append(ImageEntry(name, True, children=children))
            elif secondary_type == -3:
                size = self._long(block, 324)
                result.append(
                    ImageEntry(
                        name,
                        False,
                        size=size,
                        _reader=lambda file_block=block: self._file_content(file_block),
                    )
                )
        return tuple(result)

    def _file_content(self, header: bytes) -> bytes:
        size = self._long(header, 324)
        if size > len(self.data):
            raise FilesystemError("An AmigaDOS file has an impossible size.")
        if not self.ffs:
            chunks: list[bytes] = []
            pointer = self._long(header, 16)
            seen: set[int] = set()
            while pointer and sum(map(len, chunks)) < size:
                if pointer in seen:
                    raise FilesystemError("An AmigaDOS OFS file contains a block loop.")
                seen.add(pointer)
                block = self._block(pointer)
                if self._long(block, 0, signed=True) != 8:
                    raise FilesystemError("An AmigaDOS OFS data block is invalid.")
                data_size = min(self._long(block, 12), self.BLOCK_SIZE - 24)
                chunks.append(block[24 : 24 + data_size])
                pointer = self._long(block, 16)
            content = b"".join(chunks)
        else:
            chunks = []
            list_block = header
            seen_extensions: set[int] = set()
            while True:
                pointer_count = min(self._long(list_block, 8), 72)
                pointers = [
                    self._long(list_block, 24 + index * 4) for index in range(72)
                ]
                for pointer in reversed(pointers[-pointer_count:] if pointer_count else []):
                    if pointer:
                        chunks.append(self._block(pointer))
                extension = self._long(list_block, 504)
                if not extension:
                    break
                if extension in seen_extensions:
                    raise FilesystemError("An AmigaDOS FFS extension block contains a loop.")
                seen_extensions.add(extension)
                list_block = self._block(extension)
            content = b"".join(chunks)
        if len(content) < size:
            raise FilesystemError("An AmigaDOS file is shorter than its recorded size.")
        return content[:size]
