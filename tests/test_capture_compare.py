import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from greaseweazle_gui.capture_compare import compare_captures
from greaseweazle_gui.disk_formats import DISK_FORMATS


class CaptureComparisonTests(unittest.TestCase):
    def test_identical_images(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "first.st"
            second = Path(folder) / "second.st"
            first.write_bytes(b"same")
            second.write_bytes(b"same")
            result = compare_captures(first, second)
        self.assertTrue(result.identical)

    def test_reports_changed_track_side(self) -> None:
        disk_format = next(
            item for item in DISK_FORMATS if item.gw_format == "atarist.720"
        )
        size = disk_format.track_count * disk_format.sectors_per_track * 512
        first_data = bytearray(size)
        second_data = bytearray(size)
        track_size = disk_format.sectors_per_track * 512
        second_data[(3 * 2 + 1) * track_size] = 1
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "first.st"
            second = Path(folder) / "second.st"
            first.write_bytes(first_data)
            second.write_bytes(second_data)
            with patch(
                "greaseweazle_gui.capture_compare.detect_image_format"
            ) as detect:
                detect.return_value.disk_format = disk_format
                result = compare_captures(first, second)
        self.assertFalse(result.identical)
        self.assertTrue(result.comparable_tracks)
        self.assertEqual(result.changed_tracks, ((3, 1),))


if __name__ == "__main__":
    unittest.main()
