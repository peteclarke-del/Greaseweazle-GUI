from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from greaseweazle_gui.disk_formats import DISK_FORMATS
from greaseweazle_gui.image_detection import detect_image_format


class ImageDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = patch(
            "greaseweazle_gui.image_detection.supported_formats",
            return_value=DISK_FORMATS,
        )
        self.catalog.start()
        self.addCleanup(self.catalog.stop)

    def test_atari_boot_sector_content_overrides_unknown_extension(self) -> None:
        header = bytearray(512)
        header[11:13] = (512).to_bytes(2, "little")
        header[13] = 2
        header[19:21] = (1600).to_bytes(2, "little")
        header[24:26] = (10).to_bytes(2, "little")
        header[26:28] = (2).to_bytes(2, "little")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mystery.bin"
            path.write_bytes(header)

            guess = detect_image_format(path)

        self.assertEqual(guess.method, "content")
        self.assertIsNotNone(guess.disk_format)
        assert guess.disk_format is not None
        self.assertEqual(guess.disk_format.gw_format, "atarist.800")

    def test_st_extension_and_size_are_used_when_content_is_inconclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "disk.st"
            with path.open("wb") as image:
                image.truncate(80 * 2 * 9 * 512)

            guess = detect_image_format(path)

        self.assertEqual(guess.method, "extension")
        self.assertIsNotNone(guess.disk_format)
        assert guess.disk_format is not None
        self.assertEqual(guess.disk_format.gw_format, "atarist.720")

    def test_scp_track_table_selects_lossless_raw_write_and_geometry(self) -> None:
        header = bytearray(0x2B0)
        header[:3] = b"SCP"
        struct.pack_into("<I", header, 0x10, 0x2B0)
        struct.pack_into("<I", header, 0x10 + 159 * 4, 0x400)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "protected.scp"
            path.write_bytes(header)

            guess = detect_image_format(path)

        self.assertEqual(guess.method, "content")
        self.assertIsNotNone(guess.disk_format)
        assert guess.disk_format is not None
        self.assertEqual(guess.disk_format.gw_format, "")
        self.assertEqual(guess.disk_format.cylinders, 80)
        self.assertEqual(guess.disk_format.heads, 2)

    def test_unknown_image_requires_manual_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mystery.bin"
            path.write_bytes(b"not a recognised image")

            guess = detect_image_format(path)

        self.assertEqual(guess.method, "unknown")
        self.assertIsNone(guess.disk_format)


if __name__ == "__main__":
    unittest.main()
