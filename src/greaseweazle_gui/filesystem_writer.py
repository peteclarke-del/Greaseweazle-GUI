"""In-place editing of FAT12 disk images (add, delete and create folders)."""

from __future__ import annotations

import re
import struct
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from .filesystems import FilesystemError

_FAT12_SUFFIXES = {".st", ".img", ".ima"}
_INVALID = re.compile(r'[^A-Z0-9!#$%&\'()\-@^_`{}~]')


class ImageWriter:
    """Common interface for editing a disk image held in memory.

    ``directory`` is the list of folder names from the disk root.
    """

    label = ""

    def __init__(self, data: bytearray) -> None:
        self.data = data

    def add_file(self, directory: Sequence[str], name: str, content: bytes) -> None:
        raise NotImplementedError

    def make_directory(self, directory: Sequence[str], name: str) -> None:
        raise FilesystemError(f"{self.label} disks cannot contain folders.")

    def delete(self, directory: Sequence[str], name: str) -> None:
        raise NotImplementedError

    def free_bytes(self) -> int:
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        return bytes(self.data)


def create_writer(data: bytes, suffix: str) -> ImageWriter:
    """Return an editor for the image, or raise FilesystemError."""
    suffix = suffix.lower()
    factories: list[Callable[[bytearray], ImageWriter]] = []
    if suffix in _FAT12_SUFFIXES:
        factories = [Fat12Writer, Os9Writer, DecbWriter]
    elif suffix == ".adf":
        factories = [AmigaWriter]
    elif suffix in {".ssd", ".dsd"}:
        factories = [lambda d: DfsWriter(d, suffix)]
    elif suffix in {".ads", ".adm", ".adl"}:
        factories = [AdfsWriter]
    elif suffix == ".d64":
        factories = [D64Writer]
    error = FilesystemError("Editing is not supported for this image.")
    for factory in factories:
        try:
            return factory(bytearray(data))
        except FilesystemError as caught:
            error = caught
    raise error


def writable_support(image_path: Path | None) -> str | None:
    """Return the filesystem name if the image can be edited, else None."""
    if image_path is None:
        return None
    try:
        return create_writer(image_path.read_bytes(), image_path.suffix).label
    except (FilesystemError, OSError):
        return None


class Fat12Writer(ImageWriter):
    """Mutates a FAT12 image held in a bytearray."""

    label = "FAT12"

    def __init__(self, data: bytearray) -> None:
        if len(data) < 512:
            raise FilesystemError("The FAT12 image is too small.")
        self.data = data
        self.bps = struct.unpack_from("<H", data, 11)[0]
        self.spc = data[13]
        reserved = struct.unpack_from("<H", data, 14)[0]
        self.fats = data[16]
        self.root_entries = struct.unpack_from("<H", data, 17)[0]
        total = struct.unpack_from("<H", data, 19)[0] or struct.unpack_from("<I", data, 32)[0]
        self.spf = struct.unpack_from("<H", data, 22)[0]
        if (
            self.bps not in {128, 256, 512, 1024, 2048, 4096}
            or not self.spc
            or not reserved
            or not self.fats
            or not self.root_entries
            or not self.spf
            or not total
            or total * self.bps > len(data)
        ):
            raise FilesystemError("The image does not contain a valid FAT12 filesystem.")
        self.fat_offset = reserved * self.bps
        self.root_offset = (reserved + self.fats * self.spf) * self.bps
        self.root_size = self.root_entries * 32
        self.data_offset = self.root_offset + (self.root_size + self.bps - 1) // self.bps * self.bps
        self.cluster_size = self.bps * self.spc
        self.cluster_count = (total * self.bps - self.data_offset) // self.cluster_size

    # -- FAT access ---------------------------------------------------------
    def _get(self, cluster: int) -> int:
        o = self.fat_offset + cluster + cluster // 2
        value = self.data[o] | (self.data[o + 1] << 8)
        return value >> 4 if cluster & 1 else value & 0xFFF

    def _set(self, cluster: int, value: int) -> None:
        for copy in range(self.fats):
            o = self.fat_offset + copy * self.spf * self.bps + cluster + cluster // 2
            current = self.data[o] | (self.data[o + 1] << 8)
            if cluster & 1:
                current = (current & 0x000F) | (value << 4)
            else:
                current = (current & 0xF000) | value
            self.data[o] = current & 0xFF
            self.data[o + 1] = current >> 8

    def _chain(self, first: int) -> list[int]:
        chain: list[int] = []
        cluster = first
        while 2 <= cluster < 0xFF8:
            if cluster in chain or cluster >= self.cluster_count + 2:
                raise FilesystemError("The disk contains an invalid FAT chain.")
            chain.append(cluster)
            cluster = self._get(cluster)
        return chain

    def _free_chain(self, first: int) -> None:
        for cluster in self._chain(first):
            self._set(cluster, 0)

    def _allocate(self, count: int) -> list[int]:
        free = [
            c for c in range(2, self.cluster_count + 2) if self._get(c) == 0
        ][:count]
        if len(free) < count:
            raise FilesystemError("There is not enough free space on the disk.")
        for a, b in zip(free, free[1:]):
            self._set(a, b)
        if free:
            self._set(free[-1], 0xFFF)
        return free

    def free_bytes(self) -> int:
        return sum(
            1 for c in range(2, self.cluster_count + 2) if self._get(c) == 0
        ) * self.cluster_size

    def _cluster_offset(self, cluster: int) -> int:
        return self.data_offset + (cluster - 2) * self.cluster_size

    # -- directories --------------------------------------------------------
    def _dir_slots(self, cluster: int | None) -> list[int]:
        """Offsets of every 32-byte entry in a directory."""
        if cluster is None:
            return [self.root_offset + i * 32 for i in range(self.root_entries)]
        slots: list[int] = []
        for c in self._chain(cluster):
            base = self._cluster_offset(c)
            slots.extend(base + i * 32 for i in range(self.cluster_size // 32))
        return slots

    def _entries(self, cluster: int | None) -> list[tuple[int, int, str]]:
        """(first slot offset incl. LFN, short entry offset, display name)."""
        result: list[tuple[int, int, str]] = []
        lfn: list[str] = []
        lfn_start: int | None = None
        for off in self._dir_slots(cluster):
            entry = self.data[off : off + 32]
            if entry[0] == 0:
                break
            if entry[0] == 0xE5:
                lfn, lfn_start = [], None
                continue
            if entry[11] == 0x0F:
                if lfn_start is None:
                    lfn_start = off
                raw = bytes(entry[1:11] + entry[14:26] + entry[28:32])
                lfn.insert(0, raw.decode("utf-16le", errors="ignore").rstrip("￿\0"))
                continue
            start = lfn_start if lfn_start is not None else off
            name_long = "".join(lfn)
            lfn, lfn_start = [], None
            if entry[11] & 0x08:
                continue
            base = bytes(entry[:8]).decode("cp437", "replace").rstrip()
            ext = bytes(entry[8:11]).decode("cp437", "replace").rstrip()
            short = f"{base}.{ext}" if ext else base
            if short in {".", ".."}:
                continue
            result.append((start, off, name_long or short))
        return result

    def _resolve(self, path: Sequence[str]) -> int | None:
        cluster: int | None = None
        for part in path:
            for _start, off, name in self._entries(cluster):
                if name.casefold() == part.casefold() and self.data[off + 11] & 0x10:
                    cluster = struct.unpack_from("<H", self.data, off + 26)[0]
                    break
            else:
                raise FilesystemError(f"Folder '{part}' was not found on the disk.")
        return cluster

    def _free_slot(self, cluster: int | None) -> int:
        for off in self._dir_slots(cluster):
            if self.data[off] in (0, 0xE5):
                return off
        if cluster is None:
            raise FilesystemError("The root directory is full.")
        last = self._chain(cluster)[-1]
        new = self._allocate(1)[0]
        self._set(last, new)
        start = self._cluster_offset(new)
        self.data[start : start + self.cluster_size] = bytes(self.cluster_size)
        return start

    @staticmethod
    def _short_name(name: str, taken: set[str]) -> bytes:
        stem, dot, ext = name.upper().rpartition(".")
        if not dot:
            stem, ext = ext, ""
        stem = _INVALID.sub("_", stem.replace(" ", ""))[:8] or "FILE"
        ext = _INVALID.sub("_", ext)[:3]
        candidate = stem
        n = 0
        while f"{candidate}.{ext}" in taken:
            n += 1
            tail = f"~{n}"
            candidate = stem[: 8 - len(tail)] + tail
        return candidate.ljust(8).encode("cp437") + ext.ljust(3).encode("cp437")

    @staticmethod
    def _stamp() -> tuple[int, int]:
        t = time.localtime()
        date = max(t.tm_year - 1980, 0) << 9 | t.tm_mon << 5 | t.tm_mday
        clock = t.tm_hour << 11 | t.tm_min << 5 | t.tm_sec // 2
        return date, clock

    def _write_entry(
        self, parent: int | None, name: str, attr: int, first: int, size: int
    ) -> None:
        taken = {
            n.upper() for _s, _o, n in self._entries(parent)
        }
        if name.upper() in taken or any(n.casefold() == name.casefold() for n in taken):
            raise FilesystemError(f"'{name}' already exists in this folder.")
        short = self._short_name(name, taken)
        date, clock = self._stamp()
        slot = self._free_slot(parent)
        entry = bytearray(32)
        entry[:11] = short
        entry[11] = attr
        struct.pack_into("<H", entry, 22, clock)
        struct.pack_into("<H", entry, 24, date)
        struct.pack_into("<H", entry, 26, first)
        struct.pack_into("<I", entry, 28, size)
        self.data[slot : slot + 32] = entry

    # -- public operations --------------------------------------------------
    def add_file(self, directory: Sequence[str], name: str, content: bytes) -> None:
        parent = self._resolve(directory)
        needed = -(-len(content) // self.cluster_size)
        clusters = self._allocate(needed) if needed else []
        try:
            self._write_entry(parent, name, 0x20, clusters[0] if clusters else 0, len(content))
        except FilesystemError:
            for c in clusters:
                self._set(c, 0)
            raise
        for index, cluster in enumerate(clusters):
            chunk = content[index * self.cluster_size : (index + 1) * self.cluster_size]
            o = self._cluster_offset(cluster)
            self.data[o : o + self.cluster_size] = chunk.ljust(self.cluster_size, b"\0")

    def make_directory(self, directory: Sequence[str], name: str) -> None:
        parent = self._resolve(directory)
        cluster = self._allocate(1)[0]
        try:
            self._write_entry(parent, name, 0x10, cluster, 0)
        except FilesystemError:
            self._set(cluster, 0)
            raise
        o = self._cluster_offset(cluster)
        self.data[o : o + self.cluster_size] = bytes(self.cluster_size)
        date, clock = self._stamp()
        for index, (label, target) in enumerate(((b".", cluster), (b"..", parent or 0))):
            e = bytearray(32)
            e[:11] = label.ljust(11)
            e[11] = 0x10
            struct.pack_into("<H", e, 22, clock)
            struct.pack_into("<H", e, 24, date)
            struct.pack_into("<H", e, 26, target)
            self.data[o + index * 32 : o + index * 32 + 32] = e

    def delete(self, directory: Sequence[str], name: str) -> None:
        parent = self._resolve(directory)
        for start, off, display in self._entries(parent):
            if display.casefold() != name.casefold():
                continue
            if self.data[off + 11] & 0x10:
                cluster = struct.unpack_from("<H", self.data, off + 26)[0]
                for _s, _o, child in self._entries(cluster):
                    self.delete([*directory, display], child)
            first = struct.unpack_from("<H", self.data, off + 26)[0]
            if first >= 2:
                self._free_chain(first)
            for slot in range(start, off + 1, 32):
                self.data[slot] = 0xE5
            return
        raise FilesystemError(f"'{name}' was not found on the disk.")


def _fit_name(name: str, limit: int) -> str:
    return "".join(c if 32 < ord(c) < 127 else "_" for c in name)[:limit]


class DfsWriter(ImageWriter):
    """Acorn DFS (.ssd single-sided, .dsd interleaved double-sided)."""

    label = "Acorn DFS"
    SECTOR = 256
    TRACK = 10 * 256

    def __init__(self, data: bytearray, suffix: str) -> None:
        if len(data) < self.TRACK or len(data) % self.TRACK:
            raise FilesystemError("The Acorn DFS image has an invalid size.")
        self.double = suffix == ".dsd"
        if self.double:
            if len(data) % (2 * self.TRACK):
                raise FilesystemError("The double-sided DFS image is truncated.")
            tracks = [data[o : o + self.TRACK] for o in range(0, len(data), self.TRACK)]
            self.sides = [bytearray().join(tracks[0::2]), bytearray().join(tracks[1::2])]
        else:
            self.sides = [bytearray(data)]
        super().__init__(data)
        for side in self.sides:
            if side[261] % 8 or side[261] > 31 * 8:
                raise FilesystemError("The DFS catalogue is invalid.")

    def to_bytes(self) -> bytes:
        if not self.double:
            return bytes(self.sides[0])
        out = bytearray()
        count = len(self.sides[0]) // self.TRACK
        for t in range(count):
            for side in self.sides:
                out += side[t * self.TRACK : (t + 1) * self.TRACK]
        return bytes(out)

    def _side(self, directory: Sequence[str]) -> tuple[bytearray, list[str]]:
        if not self.double:
            if directory:
                raise FilesystemError("DFS disks have no folders.")
            return self.sides[0], []
        if len(directory) != 1 or not directory[0].startswith("Side "):
            raise FilesystemError("Open Side 0 or Side 1 first.")
        index = int(directory[0][5:])
        return self.sides[index], []

    @staticmethod
    def _entries(side: bytearray) -> list[dict]:
        result = []
        for i in range(side[261] // 8):
            o = 8 + i * 8
            n, m = side[o : o + 8], side[256 + o : 256 + o + 8]
            result.append(
                {
                    "name": bytes(n[:7]).decode("latin-1").rstrip(" \0"),
                    "dir": chr(n[7] & 0x7F),
                    "locked": n[7] & 0x80,
                    "load": m[0] | m[1] << 8 | (m[6] >> 2 & 3) << 16,
                    "exec": m[2] | m[3] << 8 | (m[6] >> 6 & 3) << 16,
                    "length": m[4] | m[5] << 8 | (m[6] >> 4 & 3) << 16,
                    "start": m[7] | (m[6] & 3) << 8,
                }
            )
        return result

    @staticmethod
    def _total(side: bytearray) -> int:
        return (side[262] & 3) << 8 | side[263] or len(side) // 256

    def _store(self, side: bytearray, entries: list[dict]) -> None:
        entries = sorted(entries, key=lambda e: -e["start"])
        side[8:256] = bytes(248)
        side[264:512] = bytes(248)
        for i, e in enumerate(entries):
            o = 8 + i * 8
            side[o : o + 7] = e["name"].ljust(7).encode("latin-1")
            side[o + 7] = ord(e["dir"]) | e["locked"]
            side[256 + o : 256 + o + 2] = (e["load"] & 0xFFFF).to_bytes(2, "little")
            side[256 + o + 2 : 256 + o + 4] = (e["exec"] & 0xFFFF).to_bytes(2, "little")
            side[256 + o + 4 : 256 + o + 6] = (e["length"] & 0xFFFF).to_bytes(2, "little")
            side[256 + o + 6] = (
                (e["exec"] >> 16 & 3) << 6
                | (e["length"] >> 16 & 3) << 4
                | (e["load"] >> 16 & 3) << 2
                | e["start"] >> 8 & 3
            )
            side[256 + o + 7] = e["start"] & 0xFF
        side[261] = len(entries) * 8
        side[260] = (side[260] + 1) % 100 if side[260] < 0x99 else 0  # cycle (BCD-ish)

    def _gaps(self, side: bytearray) -> list[tuple[int, int]]:
        spans = sorted(
            (e["start"], e["start"] + -(-e["length"] // 256)) for e in self._entries(side)
        )
        gaps, cursor = [], 2
        for start, end in spans:
            if start > cursor:
                gaps.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < self._total(side):
            gaps.append((cursor, self._total(side)))
        return gaps

    @staticmethod
    def _split(name: str) -> tuple[str, str]:
        if len(name) > 2 and name[1] == ".":
            return name[0], _fit_name(name[2:], 7)
        return "$", _fit_name(name, 7)

    def add_file(self, directory: Sequence[str], name: str, content: bytes) -> None:
        side, _ = self._side(directory)
        entries = self._entries(side)
        folder, leaf = self._split(name)
        if any(e["dir"] == folder and e["name"].casefold() == leaf.casefold() for e in entries):
            raise FilesystemError(f"'{name}' already exists on the disk.")
        if len(entries) >= 31:
            raise FilesystemError("The DFS catalogue is full (31 files).")
        if len(content) >= 1 << 18:
            raise FilesystemError("The file is too large for DFS.")
        sectors = -(-len(content) // 256)
        for begin, end in self._gaps(side):
            if end - begin >= sectors:
                break
        else:
            raise FilesystemError("There is not enough free space on the disk.")
        entries.append(
            {"name": leaf, "dir": folder, "locked": 0, "load": 0, "exec": 0,
             "length": len(content), "start": begin}
        )
        side[begin * 256 : begin * 256 + sectors * 256] = content.ljust(sectors * 256, b"\0")
        self._store(side, entries)

    def delete(self, directory: Sequence[str], name: str) -> None:
        if self.double and not directory:
            raise FilesystemError("Sides cannot be deleted.")
        side, _ = self._side(directory)
        entries = self._entries(side)
        folder, leaf = self._split(name)
        kept = [
            e for e in entries
            if not (e["dir"] == folder and e["name"].casefold() == leaf.casefold())
        ]
        if len(kept) == len(entries):
            raise FilesystemError(f"'{name}' was not found on the disk.")
        self._store(side, kept)

    def free_bytes(self) -> int:
        return sum(sum(e - b for b, e in self._gaps(s)) for s in self.sides) * 256


class D64Writer(ImageWriter):
    """Commodore 1541 .d64 images (35 tracks)."""

    label = "Commodore DOS"
    PER_TRACK = (*(21,) * 17, *(19,) * 7, *(18,) * 6, *(17,) * 5)

    def __init__(self, data: bytearray) -> None:
        expected = sum(self.PER_TRACK) * 256
        if len(data) not in {expected, expected + 683}:
            raise FilesystemError("The Commodore 1541 image has an invalid size.")
        super().__init__(data)
        self.starts = [sum(self.PER_TRACK[:t]) for t in range(35)]

    def _off(self, track: int, sector: int) -> int:
        return (self.starts[track - 1] + sector) * 256

    def _bam(self, track: int) -> int:
        return self._off(18, 0) + 4 * track

    def _is_free(self, track: int, sector: int) -> bool:
        o = self._bam(track)
        return bool(self.data[o + 1 + sector // 8] & (1 << sector % 8))

    def _mark(self, track: int, sector: int, free: bool) -> None:
        o = self._bam(track)
        bit = 1 << sector % 8
        was_free = bool(self.data[o + 1 + sector // 8] & bit)
        if free and not was_free:
            self.data[o + 1 + sector // 8] |= bit
            self.data[o] += 1
        elif not free and was_free:
            self.data[o + 1 + sector // 8] &= ~bit & 0xFF
            self.data[o] -= 1

    def _allocate(self, count: int, near_directory: bool = False) -> list[tuple[int, int]]:
        if near_directory:
            order = [18]
        else:
            order = [t for d in range(1, 18) for t in (18 - d, 18 + d) if 1 <= t <= 35]
        step = 3 if near_directory else 10
        chosen: list[tuple[int, int]] = []
        last = 0
        for _ in range(count):
            for track in order:
                n = self.PER_TRACK[track - 1]
                probe = (last + step) % n if chosen else 0
                for _k in range(n):
                    if (track, probe) not in chosen and self._is_free(track, probe):
                        chosen.append((track, probe))
                        last = probe
                        break
                    probe = (probe + 1) % n
                else:
                    continue
                break
            else:
                raise FilesystemError("There is not enough free space on the disk.")
        return chosen

    @staticmethod
    def _petscii(name: str) -> bytes:
        return _fit_name(name, 16).upper().encode("ascii", "replace")

    def _slots(self) -> list[int]:
        offsets, track, sector, seen = [], 18, 1, set()
        while track:
            if (track, sector) in seen:
                raise FilesystemError("The Commodore directory contains a loop.")
            seen.add((track, sector))
            base = self._off(track, sector)
            offsets += [base + 2 + i * 32 for i in range(8)]
            track, sector = self.data[base], self.data[base + 1]
        return offsets

    def _find(self, name: str) -> int | None:
        wanted = self._petscii(name)
        for o in self._slots():
            if self.data[o] & 7 and bytes(self.data[o + 3 : o + 19]).rstrip(b"\xa0\0 ") == wanted.rstrip():
                return o
        return None

    def add_file(self, directory: Sequence[str], name: str, content: bytes) -> None:
        if directory:
            raise FilesystemError("Commodore disks have no folders.")
        if self._find(name) is not None:
            raise FilesystemError(f"'{name}' already exists on the disk.")
        slot = next((o for o in self._slots() if not self.data[o] & 7), None)
        if slot is None:
            if sum(1 for _ in self._slots()) >= 144:
                raise FilesystemError("The directory is full.")
            tail = 18, 1
            while self.data[self._off(*tail)]:
                tail = self.data[self._off(*tail)], self.data[self._off(*tail) + 1]
            new = self._allocate(1, near_directory=True)[0]
            base = self._off(*new)
            self.data[base : base + 256] = bytes(256)
            self.data[base + 1] = 0xFF
            self.data[self._off(*tail)], self.data[self._off(*tail) + 1] = new
            self._mark(*new, free=False)
            slot = base + 2
        blocks = max(1, -(-len(content) // 254))
        chain = self._allocate(blocks)
        for index, (track, sector) in enumerate(chain):
            base = self._off(track, sector)
            chunk = content[index * 254 : (index + 1) * 254]
            self.data[base : base + 256] = bytes(256)
            if index + 1 < len(chain):
                self.data[base], self.data[base + 1] = chain[index + 1]
            else:
                self.data[base], self.data[base + 1] = 0, len(chunk) + 1
            self.data[base + 2 : base + 2 + len(chunk)] = chunk
            self._mark(track, sector, free=False)
        self.data[slot : slot + 30] = bytes(30)
        self.data[slot] = 0x82
        self.data[slot + 1], self.data[slot + 2] = chain[0]
        self.data[slot + 3 : slot + 19] = self._petscii(name).ljust(16, b"\xa0")
        self.data[slot + 28] = blocks & 0xFF
        self.data[slot + 29] = blocks >> 8

    def delete(self, directory: Sequence[str], name: str) -> None:
        slot = self._find(name)
        if slot is None:
            raise FilesystemError(f"'{name}' was not found on the disk.")
        track, sector, seen = self.data[slot + 1], self.data[slot + 2], set()
        while track and (track, sector) not in seen:
            seen.add((track, sector))
            base = self._off(track, sector)
            self._mark(track, sector, free=True)
            track, sector = self.data[base], self.data[base + 1]
        self.data[slot] = 0

    def free_bytes(self) -> int:
        return sum(self.data[self._bam(t)] for t in range(1, 36) if t != 18) * 254


class Os9Writer(ImageWriter):
    """OS-9 RBF (Tandy Color Computer and Dragon discs)."""

    label = "OS-9 RBF"
    SECTOR = 256

    def __init__(self, data: bytearray) -> None:
        if len(data) < 3 * self.SECTOR or len(data) % self.SECTOR:
            raise FilesystemError("The OS-9 image has an invalid size.")
        super().__init__(data)
        self.total = int.from_bytes(data[0:3], "big")
        self.root = int.from_bytes(data[8:11], "big")
        self.map_bytes = int.from_bytes(data[4:6], "big")
        self.cluster = int.from_bytes(data[6:8], "big") or 1
        if (
            self.total != len(data) // self.SECTOR
            or not data[3]
            or not 2 <= self.root < self.total
            or not 0 < self.map_bytes <= self.SECTOR * 8
        ):
            raise FilesystemError("The OS-9 identification sector is invalid.")
        self.clusters = min(self.map_bytes * 8, self.total // self.cluster)

    # -- allocation bitmap (LSN 1, one bit per cluster, MSB first) -----------
    def _used(self, cluster: int) -> bool:
        return bool(self.data[self.SECTOR + cluster // 8] & (0x80 >> cluster % 8))

    def _set(self, cluster: int, used: bool) -> None:
        mask = 0x80 >> cluster % 8
        o = self.SECTOR + cluster // 8
        self.data[o] = (self.data[o] | mask) if used else (self.data[o] & ~mask & 0xFF)

    def free_bytes(self) -> int:
        return sum(not self._used(c) for c in range(self.clusters)) * self.cluster * self.SECTOR

    def _allocate(self, sectors: int) -> list[tuple[int, int]]:
        """Return (first LSN, sector count) extents covering ``sectors``."""
        need = -(-sectors // self.cluster)
        extents: list[tuple[int, int]] = []
        taken: list[int] = []
        run_start = None
        for c in range(self.clusters + 1):
            free = c < self.clusters and not self._used(c) and c not in taken
            if free and run_start is None:
                run_start = c
            elif not free and run_start is not None:
                length = min(c - run_start, need)
                extents.append((run_start * self.cluster, length * self.cluster))
                taken.extend(range(run_start, run_start + length))
                need -= length
                run_start = None
                if not need:
                    break
        if need or len(extents) > 48:
            raise FilesystemError("There is not enough free space on the disk.")
        for c in taken:
            self._set(c, True)
        return extents

    def _release(self, extents: list[tuple[int, int]]) -> None:
        for lsn, count in extents:
            for c in range(lsn // self.cluster, (lsn + count) // self.cluster):
                self._set(c, False)

    # -- file descriptors ---------------------------------------------------
    def _extents(self, fd: int) -> list[tuple[int, int]]:
        o = fd * self.SECTOR
        result = []
        for off in range(0x10, self.SECTOR, 5):
            lsn = int.from_bytes(self.data[o + off : o + off + 3], "big")
            count = int.from_bytes(self.data[o + off + 3 : o + off + 5], "big")
            if not lsn and not count:
                break
            result.append((lsn, count))
        return result

    def _set_extents(self, fd: int, extents: list[tuple[int, int]]) -> None:
        o = fd * self.SECTOR
        self.data[o + 0x10 : o + self.SECTOR] = bytes(self.SECTOR - 0x10)
        for i, (lsn, count) in enumerate(extents):
            self.data[o + 0x10 + i * 5 : o + 0x13 + i * 5] = lsn.to_bytes(3, "big")
            self.data[o + 0x13 + i * 5 : o + 0x15 + i * 5] = count.to_bytes(2, "big")

    def _size(self, fd: int) -> int:
        o = fd * self.SECTOR
        return int.from_bytes(self.data[o + 9 : o + 13], "big")

    def _read(self, fd: int) -> bytes:
        size = self._size(fd)
        raw = b"".join(
            bytes(self.data[l * self.SECTOR : (l + c) * self.SECTOR])
            for l, c in self._extents(fd)
        )
        return raw[:size]

    def _write_data(self, fd: int, content: bytes) -> None:
        extents = self._extents(fd)
        position = 0
        for lsn, count in extents:
            span = count * self.SECTOR
            chunk = content[position : position + span]
            self.data[lsn * self.SECTOR : lsn * self.SECTOR + span] = chunk.ljust(span, b"\0")
            position += span

    def _new_fd(self, attributes: int, content: bytes) -> int:
        fd = self._allocate(1)[0][0]
        try:
            extents = self._allocate(max(1, -(-len(content) // self.SECTOR)))
        except FilesystemError:
            self._release([(fd, self.cluster)])
            raise
        o = fd * self.SECTOR
        t = time.localtime()
        stamp = bytes([t.tm_year - 1900, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min])
        self.data[o : o + self.SECTOR] = bytes(self.SECTOR)
        self.data[o] = attributes
        self.data[o + 3 : o + 8] = stamp
        self.data[o + 8] = 1
        self.data[o + 9 : o + 13] = len(content).to_bytes(4, "big")
        self.data[o + 13 : o + 16] = stamp[:3]
        self._set_extents(fd, extents)
        self._write_data(fd, content)
        return fd

    def _free_fd(self, fd: int) -> None:
        self._release(self._extents(fd))
        self._release([(fd, self.cluster)])
        o = fd * self.SECTOR
        self.data[o : o + self.SECTOR] = bytes(self.SECTOR)

    # -- directories --------------------------------------------------------
    @staticmethod
    def _decode(raw: bytes) -> str:
        out = bytearray()
        for byte in raw:
            if byte == 0:
                break
            out.append(byte & 0x7F)
            if byte & 0x80:
                break
        return out.decode("latin-1")

    @staticmethod
    def _encode(name: str) -> bytes:
        clean = "".join(c if c.isalnum() or c in "._-$" else "_" for c in name)[:28] or "_"
        raw = bytearray(clean.encode("ascii", "replace"))
        raw[-1] |= 0x80
        return bytes(raw).ljust(29, b"\0")

    def _entries(self, fd: int) -> list[tuple[int, str, int]]:
        listing = self._read(fd)
        return [
            (o, self._decode(listing[o : o + 29]), int.from_bytes(listing[o + 29 : o + 32], "big"))
            for o in range(0, len(listing) - 31, 32)
            if listing[o]
        ]

    def _resolve(self, path: Sequence[str]) -> int:
        fd = self.root
        for part in path:
            for _o, name, child in self._entries(fd):
                if name.casefold() == part.casefold() and self.data[child * self.SECTOR] & 0x80:
                    fd = child
                    break
            else:
                raise FilesystemError(f"Folder '{part}' was not found on the disk.")
        return fd

    def _put_entry(self, directory: int, name: str, child: int) -> None:
        if any(n.casefold() == name.casefold() for _o, n, _c in self._entries(directory)
               if n not in {".", ".."}):
            raise FilesystemError(f"'{name}' already exists in this folder.")
        listing = bytearray(self._read(directory))
        entry = self._encode(name) + child.to_bytes(3, "big")
        slot = next((o for o in range(0, len(listing) - 31, 32) if not listing[o]), None)
        if slot is None:
            listing += entry
        else:
            listing[slot : slot + 32] = entry
        self._rewrite(directory, bytes(listing))

    def _rewrite(self, fd: int, content: bytes) -> None:
        """Replace a file's data, growing its extents when required."""
        extents = self._extents(fd)
        capacity = sum(c for _l, c in extents) * self.SECTOR
        if len(content) > capacity:
            extra = self._allocate(-(-(len(content) - capacity) // self.SECTOR))
            extents = extents + extra
            if len(extents) > 48:
                raise FilesystemError("The directory is too fragmented to grow.")
            self._set_extents(fd, extents)
        o = fd * self.SECTOR
        self.data[o + 9 : o + 13] = len(content).to_bytes(4, "big")
        self._write_data(fd, content)

    def add_file(self, directory: Sequence[str], name: str, content: bytes) -> None:
        parent = self._resolve(directory)
        fd = self._new_fd(0x1B, content)
        try:
            self._put_entry(parent, name, fd)
        except FilesystemError:
            self._free_fd(fd)
            raise

    def make_directory(self, directory: Sequence[str], name: str) -> None:
        parent = self._resolve(directory)
        fd = self._new_fd(0xBF, bytes(64))
        dot = bytes([0xAE]).ljust(29, b"\0")
        dotdot = bytes([0x2E, 0xAE]).ljust(29, b"\0")
        self._rewrite(fd, dotdot + parent.to_bytes(3, "big") + dot + fd.to_bytes(3, "big"))
        try:
            self._put_entry(parent, name, fd)
        except FilesystemError:
            self._free_fd(fd)
            raise

    def delete(self, directory: Sequence[str], name: str) -> None:
        parent = self._resolve(directory)
        for offset, entry_name, fd in self._entries(parent):
            if entry_name.casefold() != name.casefold() or entry_name in {".", ".."}:
                continue
            if self.data[fd * self.SECTOR] & 0x80:
                for _o, child, _fd in self._entries(fd):
                    if child not in {".", ".."}:
                        self.delete([*directory, entry_name], child)
            self._free_fd(fd)
            listing = bytearray(self._read(parent))
            listing[offset : offset + 29] = bytes(29)
            self._rewrite(parent, bytes(listing))
            return
        raise FilesystemError(f"'{name}' was not found on the disk.")


class DecbWriter(ImageWriter):
    """Tandy Color Computer Disk BASIC (35 or 40 tracks, 18 x 256-byte sectors)."""

    label = "Tandy Color Disk BASIC"
    SECTOR = 256
    TRACK = 18 * 256
    GRANULE = 9 * 256

    def __init__(self, data: bytearray) -> None:
        if len(data) not in {35 * self.TRACK, 40 * self.TRACK}:
            raise FilesystemError("The Color Disk BASIC image has an invalid size.")
        super().__init__(data)
        self.gat = 17 * self.TRACK + self.SECTOR
        self.dir = 17 * self.TRACK + 2 * self.SECTOR
        if any(
            m >= 68 and m not in {*range(0xC1, 0xCA), 0xFF}
            for m in data[self.gat : self.gat + 68]
        ):
            raise FilesystemError("The Color Disk BASIC allocation table is invalid.")

    def _granule_offset(self, g: int) -> int:
        track = g // 2 + (1 if g // 2 >= 17 else 0)
        return track * self.TRACK + (g & 1) * self.GRANULE

    def _slots(self) -> list[int]:
        return [self.dir + i * 32 for i in range(72)]

    @staticmethod
    def _split(name: str) -> bytes:
        stem, dot, ext = name.upper().rpartition(".")
        if not dot:
            stem, ext = ext, ""
        return _fit_name(stem, 8).ljust(8).encode("ascii") + _fit_name(ext, 3).ljust(3).encode("ascii")

    def _find(self, name: str) -> int | None:
        wanted = self._split(name)
        for o in self._slots():
            if self.data[o] == 0xFF:
                return None
            if self.data[o] and bytes(self.data[o : o + 11]) == wanted:
                return o
        return None

    def add_file(self, directory: Sequence[str], name: str, content: bytes) -> None:
        if directory:
            raise FilesystemError("Color Disk BASIC disks have no folders.")
        if self._find(name) is not None:
            raise FilesystemError(f"'{name}' already exists on the disk.")
        slot = next((o for o in self._slots() if self.data[o] in (0, 0xFF)), None)
        if slot is None:
            raise FilesystemError("The directory is full.")
        count = max(1, -(-len(content) // self.GRANULE))
        free = sorted(
            (g for g in range(68) if self.data[self.gat + g] == 0xFF),
            key=lambda g: abs(g - 34.5),
        )
        if len(free) < count:
            raise FilesystemError("There is not enough free space on the disk.")
        chain = free[:count]
        remainder = len(content) - (count - 1) * self.GRANULE
        sectors = max(1, -(-remainder // self.SECTOR))
        last_bytes = remainder - (sectors - 1) * self.SECTOR if remainder else 0
        for index, g in enumerate(chain):
            chunk = content[index * self.GRANULE : (index + 1) * self.GRANULE]
            o = self._granule_offset(g)
            self.data[o : o + self.GRANULE] = chunk.ljust(self.GRANULE, b"\0")
            self.data[self.gat + g] = (
                chain[index + 1] if index + 1 < count else 0xC0 + sectors
            )
        ext = self._split(name)[8:].decode().strip()
        kind, flag = (0, 0) if ext == "BAS" else (1, 0xFF) if ext in {"TXT", "DAT"} else (2, 0)
        entry = bytearray(32)
        entry[:11] = self._split(name)
        entry[11], entry[12], entry[13] = kind, flag, chain[0]
        entry[14:16] = last_bytes.to_bytes(2, "big")
        self.data[slot : slot + 32] = entry

    def delete(self, directory: Sequence[str], name: str) -> None:
        slot = self._find(name)
        if slot is None:
            raise FilesystemError(f"'{name}' was not found on the disk.")
        g, seen = self.data[slot + 13], set()
        while g < 68 and g not in seen:
            seen.add(g)
            nxt = self.data[self.gat + g]
            self.data[self.gat + g] = 0xFF
            g = nxt
        self.data[slot] = 0
        slots = self._slots()
        index = slots.index(slot)
        if all(self.data[o] == 0xFF for o in slots[index + 1 :]):
            # Trailing killed entries become "never used" so the directory ends.
            while index >= 0 and self.data[slots[index]] == 0:
                self.data[slots[index]] = 0xFF
                index -= 1

    def free_bytes(self) -> int:
        return sum(1 for g in range(68) if self.data[self.gat + g] == 0xFF) * self.GRANULE


class AmigaWriter(ImageWriter):
    """AmigaDOS OFS/FFS (with or without international mode)."""

    label = "AmigaDOS"
    BS = 512

    def __init__(self, data: bytearray) -> None:
        if len(data) < self.BS * 4 or len(data) % self.BS:
            raise FilesystemError("The Amiga image has an invalid size.")
        super().__init__(data)
        if data[:3] != b"DOS" or data[3] > 7:
            raise FilesystemError("The image is not an AmigaDOS OFS or FFS disk.")
        if data[3] > 3:
            raise FilesystemError(
                "Directory-cache and long-name AmigaDOS variants cannot be edited yet."
            )
        self.ffs = bool(data[3] & 1)
        self.intl = bool(data[3] & 2)
        self.blocks = len(data) // self.BS
        self.root = self.blocks // 2
        root = self._block(self.root)
        if self._l(root, 0, True) != 2 or self._l(root, 508, True) != 1:
            raise FilesystemError("The AmigaDOS root block is missing or damaged.")
        if self._l(root, 416):
            raise FilesystemError("Extended bitmap lists are not supported.")
        self.bitmaps = [
            self._l(root, 316 + 4 * i) for i in range(25) if self._l(root, 316 + 4 * i)
        ]
        if not self.bitmaps:
            raise FilesystemError("The AmigaDOS disk has no valid bitmap.")
        self.dsz = 512 if self.ffs else 488

    # -- low-level helpers --------------------------------------------------
    def _block(self, n: int) -> bytearray:
        if not 0 < n < self.blocks:
            raise FilesystemError("An AmigaDOS block pointer is outside the image.")
        return self.data[n * self.BS : (n + 1) * self.BS]  # a copy

    def _put(self, n: int, block: bytearray) -> None:
        self.data[n * self.BS : (n + 1) * self.BS] = block

    @staticmethod
    def _l(block: bytes | bytearray, o: int, signed: bool = False) -> int:
        return int.from_bytes(block[o : o + 4], "big", signed=signed)

    @staticmethod
    def _w(block: bytearray, o: int, v: int) -> None:
        block[o : o + 4] = (v & 0xFFFFFFFF).to_bytes(4, "big")

    def _sum(self, block: bytearray, o: int = 20) -> None:
        self._w(block, o, 0)
        total = sum(int.from_bytes(block[i : i + 4], "big") for i in range(0, self.BS, 4))
        self._w(block, o, -total)

    def _upper(self, ch: int) -> int:
        if 97 <= ch <= 122:
            return ch - 32
        if self.intl and 0xE0 <= ch <= 0xFE and ch != 0xF7:
            return ch - 32
        return ch

    def _hash(self, name: str, size: int = 72) -> int:
        raw = name.encode("latin-1", "replace")
        h = len(raw)
        for ch in raw:
            h = (h * 13 + self._upper(ch)) & 0x7FF
        return h % size

    def _same(self, a: str, b: str) -> bool:
        ra, rb = a.encode("latin-1", "replace"), b.encode("latin-1", "replace")
        return len(ra) == len(rb) and all(self._upper(x) == self._upper(y) for x, y in zip(ra, rb))

    @staticmethod
    def _name_of(block: bytes | bytearray) -> str:
        n = min(block[432], 30)
        return bytes(block[433 : 433 + n]).decode("latin-1")

    @staticmethod
    def _clean_name(name: str) -> str:
        return "".join("_" if c in "/:" or ord(c) < 32 else c for c in name)[:30] or "_"

    # -- bitmap -------------------------------------------------------------
    def _bit(self, block: int) -> tuple[int, int, int]:
        index = block - 2
        page, bit = divmod(index, 127 * 32)
        if page >= len(self.bitmaps):
            raise FilesystemError("The block lies outside the bitmap.")
        return self.bitmaps[page] * self.BS + 4 + (bit // 32) * 4, 1 << (bit % 32), self.bitmaps[page]

    def _is_free(self, block: int) -> bool:
        o, mask, _p = self._bit(block)
        return bool(int.from_bytes(self.data[o : o + 4], "big") & mask)

    def _mark(self, block: int, free: bool) -> None:
        o, mask, page = self._bit(block)
        v = int.from_bytes(self.data[o : o + 4], "big")
        v = v | mask if free else v & ~mask
        self.data[o : o + 4] = (v & 0xFFFFFFFF).to_bytes(4, "big")
        bm = self._block(page)
        self._sum(bm, 0)
        self._put(page, bm)

    def _allocate(self, count: int) -> list[int]:
        free = sorted(
            (b for b in range(2, self.blocks) if b != self.root and self._is_free(b)),
            key=lambda b: abs(b - self.root),
        )
        if len(free) < count:
            raise FilesystemError("There is not enough free space on the disk.")
        chosen = free[:count]
        for b in chosen:
            self._mark(b, False)
        return chosen

    def free_bytes(self) -> int:
        return sum(
            1 for b in range(2, self.blocks) if b != self.root and self._is_free(b)
        ) * self.dsz

    # -- directories --------------------------------------------------------
    def _chain(self, directory: int) -> list[tuple[int, int]]:
        """(block number, hash-slot) of every child."""
        block = self._block(directory)
        out: list[tuple[int, int]] = []
        for slot in range(72):
            pointer, seen = self._l(block, 24 + slot * 4), set()
            while pointer and pointer not in seen:
                seen.add(pointer)
                out.append((pointer, slot))
                pointer = self._l(self._block(pointer), 496)
        return out

    def _find(self, directory: int, name: str) -> int | None:
        for number, _slot in self._chain(directory):
            if self._same(self._name_of(self._block(number)), name):
                return number
        return None

    def _resolve(self, path: Sequence[str]) -> int:
        number = self.root
        for part in path:
            child = self._find(number, part)
            if child is None or self._l(self._block(child), 508, True) != 2:
                raise FilesystemError(f"Folder '{part}' was not found on the disk.")
            number = child
        return number

    def _link(self, directory: int, name: str, child: int) -> None:
        block = self._block(directory)
        slot = self._hash(name)
        pointer = self._l(block, 24 + slot * 4)
        if not pointer:
            self._w(block, 24 + slot * 4, child)
            self._sum(block)
            self._put(directory, block)
            return
        while True:
            node = self._block(pointer)
            nxt = self._l(node, 496)
            if not nxt:
                self._w(node, 496, child)
                self._sum(node)
                self._put(pointer, node)
                return
            pointer = nxt

    def _unlink(self, directory: int, child: int) -> None:
        block = self._block(directory)
        for slot in range(72):
            pointer, previous = self._l(block, 24 + slot * 4), None
            while pointer:
                node = self._block(pointer)
                if pointer == child:
                    nxt = self._l(node, 496)
                    if previous is None:
                        self._w(block, 24 + slot * 4, nxt)
                        self._sum(block)
                        self._put(directory, block)
                    else:
                        prev = self._block(previous)
                        self._w(prev, 496, nxt)
                        self._sum(prev)
                        self._put(previous, prev)
                    return
                previous, pointer = pointer, self._l(node, 496)

    def _stamp(self, block: bytearray) -> None:
        delta = time.time() - time.mktime((1978, 1, 1, 0, 0, 0, 0, 0, -1))
        days, rest = divmod(int(delta), 86400)
        self._w(block, 420, days)
        self._w(block, 424, rest // 60)
        self._w(block, 428, (rest % 60) * 50)

    def _check_new(self, directory: int, name: str) -> str:
        name = self._clean_name(name)
        if self._find(directory, name) is not None:
            raise FilesystemError(f"'{name}' already exists in this folder.")
        return name

    def make_directory(self, directory: Sequence[str], name: str) -> None:
        parent = self._resolve(directory)
        name = self._check_new(parent, name)
        (number,) = self._allocate(1)
        block = bytearray(self.BS)
        self._w(block, 0, 2)
        self._w(block, 4, number)
        self._stamp(block)
        block[432] = len(name)
        block[433 : 433 + len(name)] = name.encode("latin-1", "replace")
        self._w(block, 500, parent)
        self._w(block, 508, 2)
        self._sum(block)
        self._put(number, block)
        self._link(parent, name, number)

    def add_file(self, directory: Sequence[str], name: str, content: bytes) -> None:
        parent = self._resolve(directory)
        name = self._check_new(parent, name)
        count = -(-len(content) // self.dsz)
        extensions = max(0, -(-count // 72) - 1)
        blocks = self._allocate(1 + count + extensions)
        header, data_blocks, ext_blocks = blocks[0], blocks[1 : 1 + count], blocks[1 + count :]
        for index, number in enumerate(data_blocks):
            chunk = content[index * self.dsz : (index + 1) * self.dsz]
            if self.ffs:
                self._put(number, bytearray(chunk.ljust(self.BS, b"\0")))
                continue
            block = bytearray(self.BS)
            self._w(block, 0, 8)
            self._w(block, 4, header)
            self._w(block, 8, index + 1)
            self._w(block, 12, len(chunk))
            self._w(block, 16, data_blocks[index + 1] if index + 1 < count else 0)
            block[24 : 24 + len(chunk)] = chunk
            self._sum(block)
            self._put(number, block)
        groups = [data_blocks[i : i + 72] for i in range(0, count, 72)] or [[]]
        owners = [header, *ext_blocks]
        for index, group in enumerate(groups):
            block = bytearray(self.BS)
            number = owners[index]
            if index == 0:
                self._w(block, 0, 2)
                self._w(block, 4, number)
                self._w(block, 16, data_blocks[0] if data_blocks else 0)
                self._w(block, 324, len(content))
                self._stamp(block)
                block[432] = len(name)
                block[433 : 433 + len(name)] = name.encode("latin-1", "replace")
                self._w(block, 500, parent)
                self._w(block, 508, -3)
            else:
                self._w(block, 0, 16)
                self._w(block, 4, number)
                self._w(block, 500, header)
                self._w(block, 508, -3)
            self._w(block, 8, len(group))
            for i, ptr in enumerate(group):
                self._w(block, 308 - 4 * i, ptr)
            self._w(block, 504, owners[index + 1] if index + 1 < len(groups) else 0)
            self._sum(block)
            self._put(number, block)
        self._link(parent, name, header)

    def _file_blocks(self, header: int) -> list[int]:
        blocks, number, seen = [header], header, set()
        while number and number not in seen:
            seen.add(number)
            block = self._block(number)
            count = min(self._l(block, 8), 72)
            blocks += [self._l(block, 308 - 4 * i) for i in range(count)]
            number = self._l(block, 504)
            if number:
                blocks.append(number)
        return [b for b in blocks if b]

    def delete(self, directory: Sequence[str], name: str) -> None:
        parent = self._resolve(directory)
        child = self._find(parent, name)
        if child is None:
            raise FilesystemError(f"'{name}' was not found on the disk.")
        block = self._block(child)
        kind = self._l(block, 508, True)
        if kind == 2:
            for sub, _slot in self._chain(child):
                self.delete([*directory, self._name_of(block)], self._name_of(self._block(sub)))
            freed = [child]
        elif kind == -3:
            freed = self._file_blocks(child)
        else:
            raise FilesystemError(f"'{name}' is not a file or folder.")
        self._unlink(parent, child)
        for number in freed:
            self._mark(number, True)


class AdfsWriter(ImageWriter):
    """Acorn ADFS S, M and L (old free-space-map format)."""

    label = "Acorn ADFS"
    SECTOR = 256
    DIR = 5 * 256
    SIZES = {160 * 1024, 320 * 1024, 640 * 1024}

    def __init__(self, data: bytearray) -> None:
        if len(data) not in self.SIZES:
            raise FilesystemError("The ADFS image has an invalid size.")
        super().__init__(data)
        self.total = int.from_bytes(data[0xFC:0xFF], "little")
        if self.total != len(data) // self.SECTOR:
            raise FilesystemError("The ADFS free-space map has an invalid disk size.")
        if data[0x201:0x205] != b"Hugo":
            raise FilesystemError("The ADFS root directory is missing.")
        self._seed = 0xFF
        for seed in (0xFF, 0):
            if self._checksum(data[:256], seed) == data[0xFF]:
                self._seed = seed
                break

    @staticmethod
    def _checksum(sector: bytes | bytearray, seed: int) -> int:
        total, carry = seed, 0
        for index in range(254, -1, -1):
            total += sector[index] + carry
            carry = total >> 8
            total &= 0xFF
        return total

    # -- free space map -----------------------------------------------------
    def _free(self) -> list[tuple[int, int]]:
        count = self.data[0x1FE] // 3
        return [
            (
                int.from_bytes(self.data[i * 3 : i * 3 + 3], "little"),
                int.from_bytes(self.data[0x100 + i * 3 : 0x103 + i * 3], "little"),
            )
            for i in range(count)
        ]

    def _store_free(self, spans: list[tuple[int, int]]) -> None:
        spans = sorted(s for s in spans if s[1] > 0)
        merged: list[tuple[int, int]] = []
        for start, length in spans:
            if merged and merged[-1][0] + merged[-1][1] == start:
                merged[-1] = (merged[-1][0], merged[-1][1] + length)
            else:
                merged.append((start, length))
        if len(merged) > 82:
            raise FilesystemError("The disk free-space map is full.")
        self.data[0:0xF6] = bytes(0xF6)
        self.data[0x100:0x1F6] = bytes(0xF6)
        for i, (start, length) in enumerate(merged):
            self.data[i * 3 : i * 3 + 3] = start.to_bytes(3, "little")
            self.data[0x100 + i * 3 : 0x103 + i * 3] = length.to_bytes(3, "little")
        self.data[0x1FE] = len(merged) * 3
        for base in (0, 0x100):
            self.data[base + 0xFF] = self._checksum(self.data[base : base + 256], self._seed)

    def _allocate(self, sectors: int) -> int:
        spans = self._free()
        for index, (start, length) in enumerate(spans):
            if length >= sectors:
                spans[index] = (start + sectors, length - sectors)
                self._store_free(spans)
                return start
        raise FilesystemError("There is not enough free space on the disk.")

    def _release(self, start: int, sectors: int) -> None:
        self._store_free([*self._free(), (start, sectors)])

    def free_bytes(self) -> int:
        return sum(length for _s, length in self._free()) * self.SECTOR

    # -- directories --------------------------------------------------------
    @staticmethod
    def _clean(raw: bytes) -> str:
        return bytes(b & 0x7F for b in raw).split(b"\r", 1)[0].decode("latin-1").rstrip("\0 ")

    def _entries(self, sector: int) -> list[bytearray]:
        base = sector * self.SECTOR
        if self.data[base + 1 : base + 5] != b"Hugo":
            raise FilesystemError("The ADFS directory signature is invalid.")
        result = []
        for i in range(47):
            o = base + 5 + i * 26
            if not self.data[o]:
                break
            result.append(bytearray(self.data[o : o + 26]))
        return result

    def _save_entries(self, sector: int, entries: list[bytearray]) -> None:
        if len(entries) > 47:
            raise FilesystemError("The ADFS directory is full (47 entries).")
        base = sector * self.SECTOR
        entries = sorted(entries, key=lambda e: self._clean(e[:10]).casefold())
        self.data[base + 5 : base + 5 + 47 * 26] = bytes(47 * 26)
        for i, entry in enumerate(entries):
            self.data[base + 5 + i * 26 : base + 5 + (i + 1) * 26] = entry
        seq = self.data[base]
        seq = ((seq >> 4) * 10 + (seq & 15) + 1) % 100
        seq = (seq // 10) << 4 | seq % 10
        self.data[base] = self.data[base + 0x4FA] = seq

    def _resolve(self, path: Sequence[str]) -> int:
        sector = 2
        for part in path:
            for entry in self._entries(sector):
                if entry[3] & 0x80 and self._clean(entry[:10]).casefold() == part.casefold():
                    sector = int.from_bytes(entry[22:25], "little")
                    break
            else:
                raise FilesystemError(f"Folder '{part}' was not found on the disk.")
        return sector

    @staticmethod
    def _entry(name: str, is_dir: bool, length: int, start: int) -> bytearray:
        entry = bytearray(26)
        raw = _fit_name(name, 10).encode("ascii").ljust(10, b"\r")
        entry[:10] = raw
        entry[0] |= 0x80  # R
        entry[1] |= 0x80  # W
        if is_dir:
            entry[3] |= 0x80
        entry[18:22] = length.to_bytes(4, "little")
        entry[22:25] = start.to_bytes(3, "little")
        return entry

    def _add_entry(self, directory: Sequence[str], name: str, is_dir: bool, length: int, start: int) -> None:
        parent = self._resolve(directory)
        entries = self._entries(parent)
        leaf = _fit_name(name, 10)
        if any(self._clean(e[:10]).casefold() == leaf.casefold() for e in entries):
            raise FilesystemError(f"'{name}' already exists in this folder.")
        entries.append(self._entry(name, is_dir, length, start))
        self._save_entries(parent, entries)

    def add_file(self, directory: Sequence[str], name: str, content: bytes) -> None:
        parent = self._resolve(directory)
        leaf = _fit_name(name, 10)
        entries = self._entries(parent)
        if any(self._clean(e[:10]).casefold() == leaf.casefold() for e in entries):
            raise FilesystemError(f"'{name}' already exists in this folder.")
        if len(entries) >= 47:
            raise FilesystemError("The ADFS directory is full (47 entries).")
        sectors = max(1, -(-len(content) // self.SECTOR))
        start = self._allocate(sectors)
        self.data[start * self.SECTOR : (start + sectors) * self.SECTOR] = content.ljust(
            sectors * self.SECTOR, b"\0"
        )
        entries.append(self._entry(name, False, len(content), start))
        self._save_entries(parent, entries)

    def make_directory(self, directory: Sequence[str], name: str) -> None:
        parent = self._resolve(directory)
        entries = self._entries(parent)
        leaf = _fit_name(name, 10)
        if any(self._clean(e[:10]).casefold() == leaf.casefold() for e in entries):
            raise FilesystemError(f"'{name}' already exists in this folder.")
        if len(entries) >= 47:
            raise FilesystemError("The ADFS directory is full (47 entries).")
        start = self._allocate(5)
        base = start * self.SECTOR
        block = bytearray(self.DIR)
        block[1:5] = block[0x4FB:0x4FF] = b"Hugo"
        block[0x4CC : 0x4CC + 10] = leaf.encode("ascii").ljust(10, b"\r")
        block[0x4D6:0x4D9] = parent.to_bytes(3, "little")
        block[0x4D9 : 0x4D9 + 19] = leaf.encode("ascii").ljust(19, b"\r")
        self.data[base : base + self.DIR] = block
        entries.append(self._entry(name, True, self.DIR, start))
        self._save_entries(parent, entries)

    def delete(self, directory: Sequence[str], name: str) -> None:
        parent = self._resolve(directory)
        entries = self._entries(parent)
        for entry in entries:
            if self._clean(entry[:10]).casefold() != name.casefold():
                continue
            if entry[2] & 0x80:
                raise FilesystemError(f"'{name}' is locked.")
            start = int.from_bytes(entry[22:25], "little")
            if entry[3] & 0x80:
                for child in self._entries(start):
                    self.delete([*directory, self._clean(entry[:10])], self._clean(child[:10]))
                self._release(start, 5)
            else:
                length = int.from_bytes(entry[18:22], "little")
                self._release(start, max(1, -(-length // self.SECTOR)))
            entries.remove(entry)
            self._save_entries(parent, entries)
            return
        raise FilesystemError(f"'{name}' was not found on the disk.")
