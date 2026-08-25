"""Read-only, lazy access to filesystems in supported disk images."""

from __future__ import annotations

import struct
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path


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


@dataclass(frozen=True, slots=True)
class FilesystemReader:
    """A bounded image reader registered by filename suffix."""

    name: str
    suffixes: tuple[str, ...]
    opener: Callable[[bytes, str], DiskContents]


def filesystem_readers() -> tuple[FilesystemReader, ...]:
    """Return the installed read-only filesystem plugins."""
    return (
        FilesystemReader(
            "FAT12",
            (".st", ".img", ".ima"),
            lambda data, suffix: _Fat12Image(
                data,
                "Atari ST FAT12" if suffix == ".st" else "FAT12",
                "Atari ST disk" if suffix == ".st" else "FAT12 disk",
            ).open(),
        ),
        FilesystemReader(
            "AmigaDOS", (".adf",), lambda data, _suffix: _AmigaImage(data).open()
        ),
        FilesystemReader(
            "Acorn DFS",
            (".ssd", ".dsd"),
            lambda data, suffix: _AcornDfsImage(data, suffix).open(),
        ),
        FilesystemReader(
            "Acorn ADFS",
            (".adm", ".ads", ".adl"),
            lambda data, suffix: _AcornAdfsOldMapImage(data, suffix).open(),
        ),
        FilesystemReader(
            "Tandy Color Disk BASIC",
            (".img",),
            lambda data, _suffix: _TandyDecbImage(data).open(),
        ),
        FilesystemReader(
            "OS-9 RBF",
            (".img",),
            lambda data, _suffix: _Os9RbfImage(data).open(),
        ),
        FilesystemReader(
            "Commodore DOS",
            (".d64",),
            lambda data, _suffix: _CommodoreD64Image(data).open(),
        ),
    )


def browsable_suffixes() -> frozenset[str]:
    """Return image suffixes with an installed filesystem reader."""
    return frozenset(
        suffix for reader in filesystem_readers() for suffix in reader.suffixes
    )


def open_image(image_path: Path) -> DiskContents:
    """Read directory metadata without extracting file contents."""
    data = image_path.read_bytes()
    suffix = image_path.suffix.lower()
    errors: list[str] = []
    for reader in filesystem_readers():
        if suffix in reader.suffixes:
            try:
                return reader.opener(data, suffix)
            except FilesystemError as error:
                errors.append(f"{reader.name}: {error}")
    if errors:
        raise FilesystemError("\n".join(errors))
    raise FilesystemError(
        f"Browsing {suffix or 'this image format'} is not supported yet."
    )


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


class _AcornDfsImage:
    SECTOR_SIZE = 256
    TRACK_SIZE = 10 * SECTOR_SIZE

    def __init__(self, data: bytes, suffix: str) -> None:
        if len(data) < self.TRACK_SIZE or len(data) % self.TRACK_SIZE:
            raise FilesystemError("The Acorn DFS image has an invalid size.")
        if suffix == ".dsd":
            if len(data) % (self.TRACK_SIZE * 2):
                raise FilesystemError("The double-sided DFS image is truncated.")
            chunks = [
                data[offset : offset + self.TRACK_SIZE]
                for offset in range(0, len(data), self.TRACK_SIZE)
            ]
            self.sides = (b"".join(chunks[0::2]), b"".join(chunks[1::2]))
        else:
            self.sides = (data,)

    def open(self) -> DiskContents:
        opened = tuple(
            self._open_side(data, side) for side, data in enumerate(self.sides)
        )
        if len(opened) == 1:
            return opened[0]
        entries = tuple(
            ImageEntry(f"Side {side}", True, children=contents.entries)
            for side, contents in enumerate(opened)
        )
        labels = " / ".join(contents.volume_label for contents in opened)
        return DiskContents(labels, entries, "Acorn DFS (double-sided)")

    def _open_side(self, data: bytes, side: int) -> DiskContents:
        catalogue_names = data[:256]
        catalogue_meta = data[256:512]
        file_bytes = catalogue_meta[5]
        if file_bytes % 8 or file_bytes > 31 * 8:
            raise FilesystemError(f"DFS side {side} has an invalid catalogue length.")
        file_count = file_bytes // 8
        declared_sectors = ((catalogue_meta[6] & 0x03) << 8) | catalogue_meta[7]
        if not declared_sectors:
            declared_sectors = len(data) // self.SECTOR_SIZE
        if declared_sectors * self.SECTOR_SIZE > len(data):
            raise FilesystemError(
                f"DFS side {side} declares sectors outside the image."
            )
        title = (catalogue_names[:8] + catalogue_meta[:4]).decode(
            "latin-1", errors="replace"
        ).rstrip(" \0") or f"Acorn DFS side {side}"
        result: list[ImageEntry] = []
        used_names: set[str] = set()
        used_ranges: list[tuple[int, int]] = []
        for index in range(file_count):
            offset = 8 + index * 8
            raw_name = catalogue_names[offset : offset + 7]
            directory = chr(catalogue_names[offset + 7] & 0x7F)
            leaf = raw_name.decode("latin-1", errors="replace").rstrip(" \0")
            if not leaf:
                raise FilesystemError("The DFS catalogue contains an empty filename.")
            name = leaf if directory == "$" else f"{directory}.{leaf}"
            name = _unique_name(name, used_names)
            meta = catalogue_meta[offset : offset + 8]
            length = meta[4] | (meta[5] << 8) | ((meta[7] & 0x30) << 12)
            start_sector = meta[6] | ((meta[7] & 0x03) << 8)
            start = start_sector * self.SECTOR_SIZE
            end = start + length
            if start_sector < 2 or end > declared_sectors * self.SECTOR_SIZE:
                raise FilesystemError(f"{name} points outside the DFS image.")
            for previous_start, previous_end in used_ranges:
                if length and max(start, previous_start) < min(end, previous_end):
                    raise FilesystemError("DFS catalogue files overlap on disk.")
            used_ranges.append((start, end))
            result.append(
                ImageEntry(
                    name,
                    False,
                    size=length,
                    _reader=lambda begin=start, finish=end, source=data: source[
                        begin:finish
                    ],
                )
            )
        return DiskContents(title, tuple(result), "Acorn DFS")


class _AcornAdfsOldMapImage:
    """Reader for the Acorn ADFS S, M, and L old-map filesystems."""

    SECTOR_SIZE = 256
    DIRECTORY_SIZE = 5 * SECTOR_SIZE
    IMAGE_SIZES = {".adm": 160 * 1024, ".ads": 320 * 1024, ".adl": 640 * 1024}

    def __init__(self, data: bytes, suffix: str) -> None:
        expected = self.IMAGE_SIZES[suffix]
        if len(data) != expected:
            raise FilesystemError("The ADFS image has an invalid size.")
        self.data = data
        declared_sectors = int.from_bytes(data[0xFC:0xFF], "little")
        if declared_sectors != expected // self.SECTOR_SIZE:
            raise FilesystemError("The ADFS free-space map has an invalid disk size.")

    @staticmethod
    def _name(raw: bytes) -> str:
        name = bytes(byte & 0x7F for byte in raw).split(b"\r", 1)[0]
        return _safe_name(name.decode("latin-1", errors="replace"))

    def open(self) -> DiskContents:
        root = self._directory(2)
        label = self._name(root[0x4D9:0x4EC])
        entries = self._read_directory(2, {2}, 0)
        return DiskContents(label or "Acorn ADFS disk", entries, "Acorn ADFS")

    def _directory(self, sector: int) -> bytes:
        start = sector * self.SECTOR_SIZE
        end = start + self.DIRECTORY_SIZE
        if sector < 2 or end > len(self.data):
            raise FilesystemError("An ADFS directory points outside the image.")
        directory = self.data[start:end]
        if directory[1:5] != b"Hugo" or directory[0x4FB:0x4FF] != b"Hugo":
            raise FilesystemError("The ADFS directory signature is invalid.")
        return directory

    def _read_directory(
        self, sector: int, visited: set[int], depth: int
    ) -> tuple[ImageEntry, ...]:
        if depth > 64:
            raise FilesystemError("The ADFS directory tree is too deeply nested.")
        directory = self._directory(sector)
        entries: list[ImageEntry] = []
        used_names: set[str] = set()
        for index in range(47):
            entry = directory[5 + index * 26 : 5 + (index + 1) * 26]
            if not entry[0]:
                continue
            name = _unique_name(self._name(entry[:10]), used_names)
            length = int.from_bytes(entry[18:22], "little")
            start_sector = int.from_bytes(entry[22:25], "little")
            is_directory = bool(entry[3] & 0x80)
            start = start_sector * self.SECTOR_SIZE
            end = start + length
            if start_sector < 2 or end > len(self.data):
                raise FilesystemError(f"{name} points outside the ADFS image.")
            if is_directory:
                if length != self.DIRECTORY_SIZE:
                    raise FilesystemError(f"{name} has an invalid directory size.")
                if start_sector in visited:
                    raise FilesystemError("The ADFS image contains a directory loop.")
                visited.add(start_sector)
                children = self._read_directory(start_sector, visited, depth + 1)
                entries.append(ImageEntry(name, True, children=children))
            else:
                entries.append(
                    ImageEntry(
                        name,
                        False,
                        size=length,
                        _reader=lambda begin=start, finish=end: self.data[begin:finish],
                    )
                )
        return tuple(entries)


class _TandyDecbImage:
    """Reader for Tandy Color Computer Disk Extended Color BASIC images."""

    SECTOR_SIZE = 256
    SECTORS_PER_TRACK = 18
    GRANULE_SIZE = 9 * SECTOR_SIZE

    def __init__(self, data: bytes) -> None:
        track_size = self.SECTORS_PER_TRACK * self.SECTOR_SIZE
        if len(data) not in {35 * track_size, 40 * track_size}:
            raise FilesystemError("The Color Disk BASIC image has an invalid size.")
        self.data = data
        directory_track = 17 * track_size
        self.gat = data[
            directory_track + self.SECTOR_SIZE : directory_track + 2 * self.SECTOR_SIZE
        ]
        self.directory = data[
            directory_track + 2 * self.SECTOR_SIZE : directory_track
            + 11 * self.SECTOR_SIZE
        ]
        if any(
            marker >= 68 and marker not in {*range(0xC1, 0xCA), 0xFF}
            for marker in self.gat[:68]
        ):
            raise FilesystemError("The Color Disk BASIC allocation table is invalid.")

    def open(self) -> DiskContents:
        entries: list[ImageEntry] = []
        used_names: set[str] = set()
        for offset in range(0, len(self.directory), 32):
            entry = self.directory[offset : offset + 32]
            if entry[0] == 0xFF:
                break
            if entry[0] in {0, 0xFF}:
                continue
            base = entry[:8].decode("ascii", errors="replace").rstrip(" \0")
            extension = entry[8:11].decode("ascii", errors="replace").rstrip(" \0")
            name = _unique_name(
                f"{base}.{extension}" if extension else base, used_names
            )
            first = entry[13]
            last_bytes = int.from_bytes(entry[14:16], "big")
            content = self._read_chain(first, last_bytes, name)
            entries.append(
                ImageEntry(
                    name,
                    False,
                    size=len(content),
                    _reader=lambda value=content: value,
                )
            )
        if not entries and self.directory[:1] != b"\xff":
            raise FilesystemError("The Color Disk BASIC directory is invalid.")
        return DiskContents(
            "Tandy Color Disk BASIC disk", tuple(entries), "Tandy Color Disk BASIC"
        )

    def _granule(self, number: int) -> bytes:
        if number >= 68:
            raise FilesystemError("A Color Disk BASIC file uses an invalid granule.")
        track = number // 2
        if track >= 17:
            track += 1
        sector = (number & 1) * 9
        start = (track * self.SECTORS_PER_TRACK + sector) * self.SECTOR_SIZE
        return self.data[start : start + self.GRANULE_SIZE]

    def _read_chain(self, first: int, last_bytes: int, name: str) -> bytes:
        chunks: list[bytes] = []
        visited: set[int] = set()
        granule = first
        while granule < 0xC0:
            if granule >= 68 or granule in visited:
                raise FilesystemError(f"{name} has an invalid granule chain.")
            visited.add(granule)
            block = self._granule(granule)
            marker = self.gat[granule]
            if marker >= 0xC0:
                sectors = marker & 0x0F
                if not 1 <= sectors <= 9 or not 0 <= last_bytes <= self.SECTOR_SIZE:
                    raise FilesystemError(f"{name} has an invalid final granule.")
                used = (sectors - 1) * self.SECTOR_SIZE + (
                    last_bytes or self.SECTOR_SIZE
                )
                chunks.append(block[:used])
                break
            chunks.append(block)
            granule = marker
        else:
            raise FilesystemError(f"{name} has an invalid first granule.")
        return b"".join(chunks)


class _Os9RbfImage:
    """Reader for the OS-9 RBF filesystem used by Tandy and Dragon systems."""

    SECTOR_SIZE = 256

    def __init__(self, data: bytes) -> None:
        if len(data) < 3 * self.SECTOR_SIZE or len(data) % self.SECTOR_SIZE:
            raise FilesystemError("The OS-9 image has an invalid size.")
        self.data = data
        identification = data[: self.SECTOR_SIZE]
        self.total_sectors = int.from_bytes(identification[0:3], "big")
        self.root_descriptor = int.from_bytes(identification[8:11], "big")
        sectors_per_track = identification[3]
        if (
            self.total_sectors != len(data) // self.SECTOR_SIZE
            or not sectors_per_track
            or not 2 <= self.root_descriptor < self.total_sectors
        ):
            raise FilesystemError("The OS-9 identification sector is invalid.")
        self.label = self._terminated_name(identification[0x1F:0x3F])

    @staticmethod
    def _terminated_name(raw: bytes) -> str:
        result = bytearray()
        for byte in raw:
            if byte == 0:
                break
            result.append(byte & 0x7F)
            if byte & 0x80:
                break
        return _safe_name(result.decode("latin-1", errors="replace"))

    def _descriptor(self, sector: int) -> tuple[bytes, int, bool]:
        start = sector * self.SECTOR_SIZE
        if sector < 2 or start + self.SECTOR_SIZE > len(self.data):
            raise FilesystemError("An OS-9 file descriptor points outside the image.")
        descriptor = self.data[start : start + self.SECTOR_SIZE]
        size = int.from_bytes(descriptor[9:13], "big")
        return descriptor, size, bool(descriptor[0] & 0x80)

    def _read_file(self, descriptor: bytes, size: int) -> bytes:
        chunks: list[bytes] = []
        covered = 0
        ranges: list[tuple[int, int]] = []
        for offset in range(0x10, self.SECTOR_SIZE, 5):
            first = int.from_bytes(descriptor[offset : offset + 3], "big")
            count = int.from_bytes(descriptor[offset + 3 : offset + 5], "big")
            if first == 0 and count == 0:
                break
            end_sector = first + count
            if not count or first < 2 or end_sector > self.total_sectors:
                raise FilesystemError("An OS-9 extent points outside the image.")
            for previous_first, previous_end in ranges:
                if max(first, previous_first) < min(end_sector, previous_end):
                    raise FilesystemError("An OS-9 file contains overlapping extents.")
            ranges.append((first, end_sector))
            chunks.append(
                self.data[first * self.SECTOR_SIZE : end_sector * self.SECTOR_SIZE]
            )
            covered += count * self.SECTOR_SIZE
        if size > covered:
            raise FilesystemError("An OS-9 file is larger than its allocated extents.")
        return b"".join(chunks)[:size]

    def open(self) -> DiskContents:
        descriptor, _size, is_directory = self._descriptor(self.root_descriptor)
        if not is_directory:
            raise FilesystemError("The OS-9 root descriptor is not a directory.")
        entries = self._read_directory(self.root_descriptor, {self.root_descriptor}, 0)
        return DiskContents(self.label or "OS-9 disk", entries, "OS-9 RBF")

    def _read_directory(
        self, descriptor_sector: int, visited: set[int], depth: int
    ) -> tuple[ImageEntry, ...]:
        if depth > 64:
            raise FilesystemError("The OS-9 directory tree is too deeply nested.")
        descriptor, size, is_directory = self._descriptor(descriptor_sector)
        if not is_directory:
            raise FilesystemError("An OS-9 directory entry points to a file.")
        directory = self._read_file(descriptor, size)
        entries: list[ImageEntry] = []
        used_names: set[str] = set()
        for offset in range(0, len(directory) - 31, 32):
            entry = directory[offset : offset + 32]
            if not entry[0]:
                continue
            name = self._terminated_name(entry[:29])
            if name in {".", ".."}:
                continue
            name = _unique_name(name, used_names)
            child_sector = int.from_bytes(entry[29:32], "big")
            child_descriptor, child_size, child_is_directory = self._descriptor(
                child_sector
            )
            if child_is_directory:
                if child_sector in visited:
                    raise FilesystemError("The OS-9 image contains a directory loop.")
                visited.add(child_sector)
                children = self._read_directory(child_sector, visited, depth + 1)
                entries.append(ImageEntry(name, True, children=children))
            else:
                entries.append(
                    ImageEntry(
                        name,
                        False,
                        size=child_size,
                        _reader=lambda block=child_descriptor, length=child_size: (
                            self._read_file(block, length)
                        ),
                    )
                )
        return tuple(entries)


class _CommodoreD64Image:
    SECTORS_PER_TRACK = (
        *(21 for _track in range(1, 18)),
        *(19 for _track in range(18, 25)),
        *(18 for _track in range(25, 31)),
        *(17 for _track in range(31, 36)),
    )

    def __init__(self, data: bytes) -> None:
        expected = sum(self.SECTORS_PER_TRACK) * 256
        if len(data) not in {expected, expected + 683}:
            raise FilesystemError("The Commodore 1541 image has an invalid size.")
        self.data = data[:expected]

    def _sector(self, track: int, sector: int) -> bytes:
        if track < 1 or track > len(self.SECTORS_PER_TRACK):
            raise FilesystemError("A Commodore file chain points to an invalid track.")
        count = self.SECTORS_PER_TRACK[track - 1]
        if sector < 0 or sector >= count:
            raise FilesystemError("A Commodore file chain points to an invalid sector.")
        offset = (sum(self.SECTORS_PER_TRACK[: track - 1]) + sector) * 256
        return self.data[offset : offset + 256]

    @staticmethod
    def _petscii_name(raw: bytes) -> str:
        raw = raw.rstrip(b"\xa0\0 ")
        text = "".join(chr(byte) if 32 <= byte < 127 else "_" for byte in raw)
        return _safe_name(text)

    def open(self) -> DiskContents:
        bam = self._sector(18, 0)
        label = self._petscii_name(bam[0x90:0xA0]) or "Commodore disk"
        entries: list[ImageEntry] = []
        used_names: set[str] = set()
        visited_directory: set[tuple[int, int]] = set()
        track, sector = 18, 1
        entry_count = 0
        while track:
            pointer = (track, sector)
            if pointer in visited_directory:
                raise FilesystemError("The Commodore directory contains a sector loop.")
            visited_directory.add(pointer)
            directory = self._sector(track, sector)
            track, sector = directory[0], directory[1]
            for slot in range(8):
                offset = 2 + slot * 32
                file_type = directory[offset] & 0x07
                if file_type == 0:
                    continue
                first_track, first_sector = directory[offset + 1], directory[offset + 2]
                name = _unique_name(
                    self._petscii_name(directory[offset + 3 : offset + 19]),
                    used_names,
                )
                size_blocks = directory[offset + 30] | (directory[offset + 31] << 8)
                if size_blocks > sum(self.SECTORS_PER_TRACK):
                    raise FilesystemError(f"{name} has an impossible block count.")

                def read_file(
                    start_track: int = first_track,
                    start_sector: int = first_sector,
                    filename: str = name,
                ) -> bytes:
                    chunks: list[bytes] = []
                    seen: set[tuple[int, int]] = set()
                    current_track, current_sector = start_track, start_sector
                    while current_track:
                        current = (current_track, current_sector)
                        if current in seen:
                            raise FilesystemError(
                                f"{filename} contains a sector-chain loop."
                            )
                        seen.add(current)
                        block = self._sector(current_track, current_sector)
                        next_track, next_sector = block[0], block[1]
                        if next_track:
                            chunks.append(block[2:])
                        else:
                            used = max(0, min(next_sector - 1, 254))
                            chunks.append(block[2 : 2 + used])
                        current_track, current_sector = next_track, next_sector
                    return b"".join(chunks)

                exact_size = self._chain_length(first_track, first_sector, name)
                entries.append(
                    ImageEntry(name, False, size=exact_size, _reader=read_file)
                )
                entry_count += 1
                if entry_count > 144:
                    raise FilesystemError(
                        "The Commodore directory is unreasonably large."
                    )
        return DiskContents(label, tuple(entries), "Commodore 1541 DOS")

    def _chain_length(self, track: int, sector: int, filename: str) -> int:
        total = 0
        seen: set[tuple[int, int]] = set()
        while track:
            current = (track, sector)
            if current in seen:
                raise FilesystemError(f"{filename} contains a sector-chain loop.")
            seen.add(current)
            block = self._sector(track, sector)
            track, sector = block[0], block[1]
            total += 254 if track else max(0, min(sector - 1, 254))
        return total


class _Fat12Image:
    def __init__(
        self,
        data: bytes,
        format_label: str = "Atari ST FAT12",
        default_label: str = "Atari ST disk",
    ) -> None:
        self.data = data
        self.format_label = format_label
        self.default_label = default_label
        if len(data) < 512:
            raise FilesystemError(
                "The FAT12 image is too small to contain a filesystem."
            )
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
            raise FilesystemError(
                "The image does not contain a valid FAT12 boot sector."
            )
        declared_size = self.total_sectors * self.bytes_per_sector
        if not self.total_sectors or declared_size > len(data):
            raise FilesystemError(
                "The FAT12 image is truncated or has invalid geometry."
            )

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
            raise FilesystemError(
                "The FAT12 filesystem structures are outside the image."
            )
        self.fat = data[self.fat_offset : fat_end]

    def open(self) -> DiskContents:
        label = self.default_label
        boot_label = self.data[43:54].decode("latin-1", errors="replace").strip(" \0")
        if boot_label:
            label = boot_label
        root = self.data[self.root_offset : self.root_offset + self.root_size]
        entries = self._read_directory(root, set(), depth=0, current_cluster=None)
        return DiskContents(label, entries, self.format_label)

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
                raise FilesystemError(
                    "The disk contains a looping or invalid FAT chain."
                )
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
                raise FilesystemError(
                    "A file extends beyond the end of the disk image."
                )
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
                    raise FilesystemError(
                        "The disk contains a recursive directory chain."
                    )
                visited.add(cluster)
                children = self._read_directory(
                    self._read_chain(cluster), visited, depth + 1, cluster
                )
                result.append(ImageEntry(name, True, children=children))
            else:

                def read_file(
                    first: int = cluster, length: int = size, filename: str = name
                ) -> bytes:
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
        if (
            self._long(root, 0, signed=True) != 2
            or self._long(root, 508, signed=True) != 1
        ):
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
                    raise FilesystemError(
                        "The AmigaDOS directory contains a hash-chain loop."
                    )
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
                    raise FilesystemError(
                        "The AmigaDOS disk contains a recursive directory."
                    )
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
                for pointer in reversed(
                    pointers[-pointer_count:] if pointer_count else []
                ):
                    if pointer:
                        chunks.append(self._block(pointer))
                extension = self._long(list_block, 504)
                if not extension:
                    break
                if extension in seen_extensions:
                    raise FilesystemError(
                        "An AmigaDOS FFS extension block contains a loop."
                    )
                seen_extensions.add(extension)
                list_block = self._block(extension)
            content = b"".join(chunks)
        if len(content) < size:
            raise FilesystemError("An AmigaDOS file is shorter than its recorded size.")
        return content[:size]
