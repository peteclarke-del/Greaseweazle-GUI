from pathlib import Path
import tempfile
import unittest

from greaseweazle_gui.disk_formats import DISK_FORMATS, DiskFormat
from greaseweazle_gui.filesystem_formatters import (
    filesystem_support_name,
    initialise_filesystem,
)
from greaseweazle_gui.filesystems import open_image


class FilesystemFormatterTests(unittest.TestCase):
    def test_atari_image_is_immediately_browseable(self) -> None:
        disk_format = next(item for item in DISK_FORMATS if item.gw_format == "atarist.800")
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "blank.st"
            image.write_bytes(b"\0" * (80 * 2 * 10 * 512))
            filesystem = initialise_filesystem(image, disk_format, "Work Disk")
            contents = open_image(image)
        self.assertEqual(filesystem, "Atari TOS FAT12")
        self.assertEqual(contents.volume_label, "WORK DISK")
        self.assertEqual(contents.entries, ())

    def test_amiga_image_is_immediately_browseable(self) -> None:
        disk_format = next(
            item for item in DISK_FORMATS if item.gw_format == "amiga.amigados"
        )
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "blank.adf"
            image.write_bytes(b"\0" * 901120)
            filesystem = initialise_filesystem(image, disk_format, "Games")
            contents = open_image(image)
        self.assertEqual(filesystem, "AmigaDOS OFS")
        self.assertEqual(contents.volume_label, "GAMES")
        self.assertEqual(contents.entries, ())

    def test_unknown_format_remains_media_only(self) -> None:
        disk_format = DiskFormat("Other", "", "other.disk", ".img", 80, 2, 9)
        self.assertIsNone(filesystem_support_name(disk_format))


if __name__ == "__main__":
    unittest.main()
