from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from greaseweazle_gui.disk_formats import DISK_FORMATS
from greaseweazle_gui.filesystem_formatters import initialise_filesystem
from greaseweazle_gui.image_inspector import inspect_image


class ImageInspectorTests(unittest.TestCase):
    def test_reports_filesystem_volume_and_hash(self) -> None:
        disk_format = next(item for item in DISK_FORMATS if item.gw_format == "atarist.720")
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "blank.st"
            image.write_bytes(b"\0" * 737280)
            initialise_filesystem(image, disk_format, "Archive")
            with patch(
                "greaseweazle_gui.image_detection.supported_formats",
                return_value=DISK_FORMATS,
            ):
                inspection = inspect_image(image)
        self.assertEqual(inspection.volume_label, "ARCHIVE")
        self.assertEqual(inspection.filesystem, "Atari ST FAT12")
        self.assertEqual(len(inspection.sha256), 64)


if __name__ == "__main__":
    unittest.main()
