import json
import tempfile
import unittest
from pathlib import Path

from greaseweazle_gui.capture_metadata import write_capture_report
from greaseweazle_gui.disk_formats import DISK_FORMATS
from greaseweazle_gui.read_disk import ReadProgress, ReadResult


class CaptureMetadataTests(unittest.TestCase):
    def test_report_contains_hash_geometry_and_track_reads(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "disk.st"
            image.write_bytes(b"capture")
            update = ReadProgress(1, 0, 0, 1, 1, 9, 9, None, "ok")
            report = write_capture_report(
                image,
                DISK_FORMATS[2],
                ReadResult(True, "ok", progress=(update,)),
                profile_name="Archival",
                device_model="Greaseweazle V4",
                device_port="/dev/ttyACM0",
            )
            payload = json.loads(report.read_text())
        self.assertEqual(payload["image"]["filename"], "disk.st")
        self.assertEqual(len(payload["image"]["sha256"]), 64)
        self.assertEqual(payload["capture_profile"], "Archival")
        self.assertEqual(payload["track_reads"][0]["sectors_read"], 9)


if __name__ == "__main__":
    unittest.main()
