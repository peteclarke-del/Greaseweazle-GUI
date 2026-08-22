from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest

from greaseweazle_gui.filesystems import (
    FilesystemError,
    ImageEntry,
    extract_image,
    materialize_entries,
    open_image,
)


def make_fat12_image() -> bytes:
    image = bytearray(8 * 512)
    image[:3] = b"\xeb\x3c\x90"
    image[3:11] = b"GREASEWZ"
    struct.pack_into("<H", image, 11, 512)
    image[13] = 1
    struct.pack_into("<H", image, 14, 1)
    image[16] = 1
    struct.pack_into("<H", image, 17, 16)
    struct.pack_into("<H", image, 19, 8)
    image[21] = 0xF9
    struct.pack_into("<H", image, 22, 1)
    image[43:54] = b"TEST DISK  "

    image[512:515] = b"\xf9\xff\xff"
    image[515:517] = b"\xff\x0f"  # Cluster 2: end of chain.

    root = 2 * 512
    image[root : root + 11] = b"HELLO   TXT"
    image[root + 11] = 0x20
    struct.pack_into("<H", image, root + 26, 2)
    struct.pack_into("<I", image, root + 28, 5)
    image[3 * 512 : 3 * 512 + 5] = b"hello"
    return bytes(image)


def make_atari_space_dot_directory_image() -> bytes:
    image = bytearray(make_fat12_image())
    root = 2 * 512
    image[root : root + 11] = b"AUTO       "
    image[root + 11] = 0x10
    struct.pack_into("<H", image, root + 26, 2)
    image[root + 32] = 0

    directory = 3 * 512
    image[directory : directory + 11] = b"           "
    image[directory + 11] = 0x10
    struct.pack_into("<H", image, directory + 26, 2)
    image[directory + 32 : directory + 43] = b"INNER   TXT"
    image[directory + 32 + 11] = 0x20
    struct.pack_into("<I", image, directory + 32 + 28, 0)
    return bytes(image)


def make_ffs_image() -> bytes:
    block_size = 512
    image = bytearray(1760 * block_size)
    image[:4] = b"DOS\x01"

    root_number = 880
    root = root_number * block_size
    struct.pack_into(">i", image, root, 2)
    struct.pack_into(">I", image, root + 12, 72)
    struct.pack_into(">I", image, root + 24, 20)
    image[root + 432] = 9
    image[root + 433 : root + 442] = b"WORKBENCH"
    struct.pack_into(">i", image, root + 508, 1)

    directory = 20 * block_size
    struct.pack_into(">i", image, directory, 2)
    struct.pack_into(">I", image, directory + 24, 10)
    image[directory + 432] = 4
    image[directory + 433 : directory + 437] = b"Docs"
    struct.pack_into(">i", image, directory + 508, 2)

    header = 10 * block_size
    struct.pack_into(">i", image, header, 2)
    struct.pack_into(">I", image, header + 8, 1)
    struct.pack_into(">I", image, header + 24 + 71 * 4, 11)
    struct.pack_into(">I", image, header + 324, 5)
    image[header + 432] = 9
    image[header + 433 : header + 442] = b"readme.md"
    struct.pack_into(">i", image, header + 508, -3)

    data = 11 * block_size
    image[data : data + 5] = b"hello"
    return bytes(image)


class FilesystemTests(unittest.TestCase):
    def test_opening_image_reads_directory_without_extracting_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "disk.st"
            image.write_bytes(make_fat12_image())

            contents = open_image(image)

            self.assertEqual(contents.volume_label, "TEST DISK")
            self.assertEqual([entry.name for entry in contents.entries], ["HELLO.TXT"])
            self.assertEqual(contents.entries[0].size, 5)
            self.assertEqual(list(root.iterdir()), [image])
            self.assertEqual(contents.entries[0].read_bytes(), b"hello")

    def test_materializes_only_selected_entries(self) -> None:
        reads: list[str] = []
        first = ImageEntry(
            "first.txt",
            False,
            size=5,
            _reader=lambda: reads.append("first") or b"first",
        )
        second = ImageEntry(
            "second.txt",
            False,
            size=6,
            _reader=lambda: reads.append("second") or b"second",
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "export"

            materialize_entries([second], output)

            self.assertEqual(reads, ["second"])
            self.assertFalse((output / "first.txt").exists())
            self.assertEqual((output / "second.txt").read_bytes(), b"second")

    def test_extracts_atari_fat12_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "disk.st"
            output = root / "files"
            image.write_bytes(make_fat12_image())

            label = extract_image(image, output)

            self.assertEqual(label, "TEST DISK")
            self.assertEqual((output / "HELLO.TXT").read_bytes(), b"hello")

    def test_ignores_atari_space_encoded_current_directory_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "disk.st"
            image.write_bytes(make_atari_space_dot_directory_image())

            contents = open_image(image)

            self.assertEqual(contents.entries[0].name, "AUTO")
            self.assertEqual(
                [entry.name for entry in contents.entries[0].children],
                ["INNER.TXT"],
            )

    def test_extracts_amiga_ffs_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "disk.adf"
            output = root / "files"
            image.write_bytes(make_ffs_image())

            label = extract_image(image, output)

            self.assertEqual(label, "WORKBENCH")
            self.assertEqual((output / "Docs" / "readme.md").read_bytes(), b"hello")

    def test_rejects_unknown_image_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "disk.img"
            image.write_bytes(b"not an image")

            with self.assertRaises(FilesystemError):
                extract_image(image, root / "files")


if __name__ == "__main__":
    unittest.main()
