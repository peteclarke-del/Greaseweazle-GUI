import tempfile
import unittest
from pathlib import Path

from greaseweazle_gui.disk_formats import DISK_FORMATS
from greaseweazle_gui.filesystem_formatters import initialise_filesystem
from greaseweazle_gui.filesystem_writer import Fat12Writer, writable_support
from greaseweazle_gui.filesystems import open_image


def names(entries):
    return {e.name: e for e in entries}


class Fat12WriterTests(unittest.TestCase):
    def test_add_mkdir_delete_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "blank.st"
            fmt = next(f for f in DISK_FORMATS if f.gw_format == "atarist.720")
            image.write_bytes(bytes(fmt.cylinders * fmt.heads * fmt.sectors_per_track * 512))
            initialise_filesystem(image, fmt)
            self.assertEqual(writable_support(image), "FAT12")
            w = Fat12Writer(bytearray(image.read_bytes()))
            big = bytes(range(256)) * 20
            w.add_file([], "hello.txt", b"hi there")
            w.make_directory([], "sub")
            w.add_file(["sub"], "Big File.bin", big)
            image.write_bytes(w.data)
            top = names(open_image(image).entries)
            self.assertEqual(top["HELLO.TXT"].read_bytes(), b"hi there")
            inner = names(top["SUB"].children)
            self.assertEqual(next(iter(inner.values())).read_bytes(), big)
            with self.assertRaises(Exception):
                w.add_file([], "hello.txt", b"dup")
            free = w.free_bytes()
            w.delete([], "SUB")
            w.delete([], "HELLO.TXT")
            self.assertGreater(w.free_bytes(), free)
            image.write_bytes(w.data)
            self.assertEqual(open_image(image).entries, ())


if __name__ == "__main__":
    unittest.main()


from greaseweazle_gui.filesystem_writer import D64Writer, create_writer  # noqa: E402


def blank_dfs(tracks=40, double=False):
    side = bytearray(tracks * 2560)
    sectors = tracks * 10
    side[256 + 6] = sectors >> 8
    side[256 + 7] = sectors & 0xFF
    side[256 + 5] = 0
    if not double:
        return bytes(side)
    out = bytearray()
    for t in range(tracks):
        out += side[t * 2560 : (t + 1) * 2560] * 1 + side[t * 2560 : (t + 1) * 2560]
    return bytes(out)


def blank_d64():
    per = (*(21,) * 17, *(19,) * 7, *(18,) * 6, *(17,) * 5)
    img = bytearray(sum(per) * 256)
    starts = [sum(per[:t]) for t in range(35)]
    bam = starts[17] * 256
    img[bam], img[bam + 1] = 18, 1
    img[bam + 2] = 0x41
    for t in range(1, 36):
        n = per[t - 1]
        o = bam + 4 * t
        img[o] = n
        bits = (1 << n) - 1
        img[o + 1 : o + 4] = bits.to_bytes(3, "little")
    for sector in (0, 1):
        o = bam + 4 * 18
        img[o + 1 + sector // 8] &= ~(1 << sector) & 0xFF
        img[o] -= 1
    img[starts[17] * 256 + 256 + 1] = 0xFF
    return bytes(img)


class OtherWriterTests(unittest.TestCase):
    def check(self, data, suffix, prefix=()):
        w = create_writer(data, suffix)
        start = w.free_bytes()
        small, big = b"hello", bytes(range(256)) * 9
        w.add_file(list(prefix), "ONE", small)
        w.add_file(list(prefix), "TWO", big)
        with self.assertRaises(Exception):
            w.add_file(list(prefix), "ONE", b"x")
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / f"x{suffix}"
            image.write_bytes(w.to_bytes())
            entries = open_image(image).entries
            if prefix:
                entries = entries[int(prefix[0][5:])].children
            found = names(entries)
            self.assertEqual(found["ONE"].read_bytes(), small)
            self.assertEqual(found["TWO"].read_bytes(), big)
            w.delete(list(prefix), "ONE")
            w.delete(list(prefix), "TWO")
            self.assertEqual(w.free_bytes(), start)
            image.write_bytes(w.to_bytes())
            entries = open_image(image).entries
            if prefix:
                entries = entries[int(prefix[0][5:])].children
            self.assertEqual(entries, ())

    def test_dfs_single(self):
        self.check(blank_dfs(), ".ssd")

    def test_dfs_double(self):
        self.check(blank_dfs(double=True), ".dsd", ("Side 1",))

    def test_d64(self):
        self.check(blank_d64(), ".d64")


def blank_decb(tracks=35):
    img = bytearray(tracks * 18 * 256)
    gat = 17 * 18 * 256 + 256
    img[gat : gat + 68] = b"\xff" * 68
    img[gat + 256 : gat + 256 + 0] = b""
    d = 17 * 18 * 256 + 512
    img[d : d + 9 * 256] = b"\xff" * (9 * 256)
    return bytes(img)


class DecbTests(OtherWriterTests):
    def test_decb(self):
        self.check(blank_decb(), ".img")


def blank_adfs():
    image = bytearray(320 * 1024)
    image[0xFC:0xFF] = (1280).to_bytes(3, "little")
    image[0:3] = (7).to_bytes(3, "little")
    image[0x100:0x103] = (1273).to_bytes(3, "little")
    image[0x1FE] = 3
    root = 512
    image[root + 1 : root + 5] = image[root + 0x4FB : root + 0x4FF] = b"Hugo"
    return bytes(image)


class AdfsTests(unittest.TestCase):
    def test_files_and_folders(self):
        w = create_writer(blank_adfs(), ".adm")
        start = w.free_bytes()
        w.add_file([], "ONE", b"hello")
        w.make_directory([], "Dir")
        w.add_file(["Dir"], "TWO", bytes(range(256)) * 9)
        with self.assertRaises(Exception):
            w.add_file([], "one", b"x")
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "x.adm"
            image.write_bytes(w.to_bytes())
            top = names(open_image(image).entries)
            self.assertEqual(top["ONE"].read_bytes(), b"hello")
            self.assertEqual(names(top["Dir"].children)["TWO"].read_bytes(), bytes(range(256)) * 9)
            w.delete([], "Dir")
            w.delete([], "ONE")
            self.assertEqual(w.free_bytes(), start)
            image.write_bytes(w.to_bytes())
            self.assertEqual(open_image(image).entries, ())


def blank_os9():
    img = bytearray(40 * 18 * 256)
    img[0:3] = (720).to_bytes(3, "big")
    img[3] = 18
    img[4:6] = (90).to_bytes(2, "big")
    img[6:8] = (1).to_bytes(2, "big")
    img[8:11] = (2).to_bytes(3, "big")
    img[256] = 0xF0  # LSN 0-3 used
    fd = 512
    img[fd] = 0xBF
    img[fd + 9 : fd + 13] = (64).to_bytes(4, "big")
    img[fd + 0x10 : fd + 0x13] = (3).to_bytes(3, "big")
    img[fd + 0x13 : fd + 0x15] = (1).to_bytes(2, "big")
    d = 3 * 256
    img[d : d + 2] = b"\x2e\xae"
    img[d + 29 : d + 32] = (2).to_bytes(3, "big")
    img[d + 32] = 0xAE
    img[d + 61 : d + 64] = (2).to_bytes(3, "big")
    return bytes(img)


class Os9Tests(unittest.TestCase):
    def test_files_and_folders(self):
        w = create_writer(blank_os9(), ".img")
        self.assertEqual(w.label, "OS-9 RBF")
        start = w.free_bytes()
        w.add_file([], "one", b"hello")
        w.make_directory([], "dir")
        w.add_file(["dir"], "two", bytes(range(256)) * 9)
        for i in range(3):
            w.add_file([], f"f{i}", b"x" * 700)
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "x.img"
            image.write_bytes(w.to_bytes())
            top = names(open_image(image).entries)
            self.assertEqual(top["one"].read_bytes(), b"hello")
            self.assertEqual(names(top["dir"].children)["two"].read_bytes(), bytes(range(256)) * 9)
            self.assertEqual(top["f2"].read_bytes(), b"x" * 700)
            for n in ("one", "dir", "f0", "f1", "f2"):
                w.delete([], n)
            self.assertEqual(w.free_bytes(), start)
            image.write_bytes(w.to_bytes())
            self.assertEqual(open_image(image).entries, ())


class AmigaTests(unittest.TestCase):
    def run_variant(self, flag):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "x.adf"
            fmt = next(f for f in DISK_FORMATS if f.gw_format == "amiga.amigados")
            image.write_bytes(bytes(901120))
            initialise_filesystem(image, fmt, "TEST")
            data = bytearray(image.read_bytes())
            data[3] = flag
            image.write_bytes(data)
            w = create_writer(bytes(data), ".adf")
            start = w.free_bytes()
            big = bytes(range(256)) * 400  # > 72 data blocks, needs an extension block
            w.add_file([], "one", b"hello")
            w.make_directory([], "Dir")
            w.add_file(["Dir"], "Big File", big)
            w.add_file([], "empty", b"")
            with self.assertRaises(Exception):
                w.add_file([], "ONE", b"x")
            image.write_bytes(w.to_bytes())
            top = names(open_image(image).entries)
            self.assertEqual(top["one"].read_bytes(), b"hello")
            self.assertEqual(names(top["Dir"].children)["Big File"].read_bytes(), big)
            self.assertEqual(top["empty"].read_bytes(), b"")
            for n in ("one", "Dir", "empty"):
                w.delete([], n)
            self.assertEqual(w.free_bytes(), start)
            image.write_bytes(w.to_bytes())
            self.assertEqual(open_image(image).entries, ())

    def test_ofs(self):
        self.run_variant(0)

    def test_ffs(self):
        self.run_variant(1)
