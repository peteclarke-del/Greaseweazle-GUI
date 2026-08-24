import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from greaseweazle_gui.disk_formats import DiskFormat
from greaseweazle_gui.read_disk import ReadProgress, ReadResult
from greaseweazle_gui.retry_tracks import retry_damaged_tracks
from greaseweazle_gui.track_health import (
    TrackCondition,
    TrackHealth,
    TrackHealthReport,
)


class RetryTracksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.disk_format = DiskFormat("Test", "", "test.2", ".st", 2, 2, 1)
        self.report = TrackHealthReport(
            (
                TrackHealth(0, 0, TrackCondition.GOOD, 1, 1, 1, "good"),
                TrackHealth(1, 0, TrackCondition.DAMAGED, 0, 1, 2, "Giving up"),
            )
        )

    def test_only_damaged_track_is_atomically_spliced(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "disk.st"
            image.write_bytes(b"A" * 2048)

            def fake_read(_format, destination, **kwargs):
                self.assertEqual(kwargs["tracks"], "c=1:h=0")
                destination.write_bytes(b"B" * 512)
                update = ReadProgress(1, 1, 0, 1, 1, 1, 1, "1", "recovered")
                kwargs["progress"](update)
                return ReadResult(True, "ok", progress=(update,))

            with patch("greaseweazle_gui.retry_tracks.read_disk", fake_read):
                result = retry_damaged_tracks(image, self.disk_format, self.report)

            self.assertTrue(result.succeeded)
            data = image.read_bytes()
            self.assertEqual(data[:1024], b"A" * 1024)
            self.assertEqual(data[1024:1536], b"B" * 512)
            self.assertEqual(data[1536:], b"A" * 512)

    def test_geometry_mismatch_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "disk.st"
            image.write_bytes(b"original")
            result = retry_damaged_tracks(image, self.disk_format, self.report)
            self.assertFalse(result.succeeded)
            self.assertEqual(image.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
