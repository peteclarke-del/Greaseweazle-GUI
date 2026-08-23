from pathlib import Path
import tempfile
import unittest

from greaseweazle_gui.filesystems import open_image


def dfs_side(title: str, filename: str, payload: bytes) -> bytes:
    image = bytearray(100 * 1024)
    encoded_title = title.encode("latin-1")[:12].ljust(12, b" ")
    image[:8] = encoded_title[:8]
    image[256:260] = encoded_title[8:]
    image[261] = 8
    image[262] = 1
    image[263] = 0x90
    image[8:15] = filename.encode("latin-1")[:7].ljust(7, b" ")
    image[15] = ord("$")
    image[256 + 12] = len(payload) & 0xFF
    image[256 + 13] = len(payload) >> 8
    image[256 + 14] = 2
    image[512 : 512 + len(payload)] = payload
    return bytes(image)


class AcornDfsTests(unittest.TestCase):
    def test_ssd_catalogue_and_lazy_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "disk.ssd"
            image.write_bytes(dfs_side("MY DISK", "HELLO", b"world"))
            contents = open_image(image)
        self.assertEqual(contents.volume_label, "MY DISK")
        self.assertEqual(contents.format_label, "Acorn DFS")
        self.assertEqual(contents.entries[0].name, "HELLO")
        self.assertEqual(contents.entries[0].read_bytes(), b"world")

    def test_dsd_sides_are_deinterleaved_by_track(self) -> None:
        side0 = dfs_side("SIDE ZERO", "ZERO", b"0")
        side1 = dfs_side("SIDE ONE", "ONE", b"1")
        chunks = []
        for offset in range(0, len(side0), 2560):
            chunks.extend((side0[offset : offset + 2560], side1[offset : offset + 2560]))
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "disk.dsd"
            image.write_bytes(b"".join(chunks))
            contents = open_image(image)
        self.assertEqual(contents.entries[0].children[0].read_bytes(), b"0")
        self.assertEqual(contents.entries[1].children[0].read_bytes(), b"1")


if __name__ == "__main__":
    unittest.main()
