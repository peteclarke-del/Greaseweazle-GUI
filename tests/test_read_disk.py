from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from greaseweazle_gui.disk_formats import (
    AUTO_DETECT_FORMAT,
    DISK_FORMATS,
    PRESERVATION_FORMAT,
)
from greaseweazle_gui.read_disk import parse_progress_line, read_disk


def fake_process(lines: list[str], return_code: int = 0) -> Mock:
    process = Mock()
    process.stdout = lines
    process.wait.return_value = return_code
    return process


class ReadDiskTests(unittest.TestCase):
    @patch("greaseweazle_gui.read_disk.subprocess.Popen")
    @patch("greaseweazle_gui.read_disk.shutil.which", return_value="/usr/bin/gw")
    def test_preservation_profile_options_reach_gw(
        self, _which: object, popen: Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "disk.adf"
            destination.write_bytes(b"image")
            popen.return_value = fake_process([])

            result = read_disk(
                DISK_FORMATS[0],
                destination,
                revolutions=3,
                retries=8,
                seek_retries=2,
            )

        self.assertTrue(result.succeeded)
        command = popen.call_args.args[0]
        self.assertEqual(
            command[command.index("--revs") + 1], "3"
        )
        self.assertEqual(command[command.index("--retries") + 1], "8")
        self.assertEqual(command[command.index("--seek-retries") + 1], "2")

    @patch("greaseweazle_gui.read_disk.subprocess.Popen")
    @patch("greaseweazle_gui.read_disk.shutil.which", return_value="/usr/bin/gw")
    def test_probe_can_limit_the_physical_tracks(
        self, _which: object, popen: object
    ) -> None:
        process = popen.return_value
        process.stdout = []
        process.wait.return_value = 0
        process.poll.return_value = 0
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "probe.scp"
            destination.write_bytes(b"probe")

            result = read_disk(
                AUTO_DETECT_FORMAT, destination, tracks="c=0:h=0-1"
            )

        self.assertTrue(result.succeeded)
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--tracks") + 1], "c=0:h=0-1")

    @patch("greaseweazle_gui.read_disk.subprocess.Popen")
    @patch("greaseweazle_gui.read_disk.shutil.which", return_value="/usr/bin/gw")
    def test_uses_selected_format_and_destination(self, _which: object, popen: Mock) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "disk.adf"
            destination.write_bytes(b"image")
            popen.return_value = fake_process(
                ["T0.0: AmigaDOS (11/11 sectors) from Raw Flux\n"]
            )
            result = read_disk(DISK_FORMATS[0], destination)

        self.assertTrue(result.succeeded)
        command = popen.call_args.args[0]
        self.assertEqual(
            command,
            ["/usr/bin/gw", "read", "--format", "amiga.amigados", str(destination)],
        )

    @patch("greaseweazle_gui.read_disk.subprocess.Popen")
    @patch("greaseweazle_gui.read_disk.shutil.which", return_value="/usr/bin/gw")
    def test_reports_gw_failure(self, _which: object, popen: Mock) -> None:
        popen.return_value = fake_process(["No flux\n"], return_code=1)

        result = read_disk(DISK_FORMATS[0], Path("disk.adf"))

        self.assertFalse(result.succeeded)
        self.assertEqual(result.diagnostic, "No flux")

    @patch("greaseweazle_gui.read_disk.subprocess.Popen")
    @patch("greaseweazle_gui.read_disk.shutil.which", return_value="/usr/bin/gw")
    def test_reports_live_progress(self, _which: object, popen: Mock) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "disk.adf"
            destination.write_bytes(b"image")
            popen.return_value = fake_process(
                [
                    "T0.0: AmigaDOS (7/11 sectors) from Raw Flux\n",
                    "T0.0: AmigaDOS (11/11 sectors) from Raw Flux (Retry #1.1)\n",
                ]
            )
            updates = []

            result = read_disk(DISK_FORMATS[0], destination, progress=updates.append)

        self.assertTrue(result.succeeded)
        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[0].sectors_read, 7)
        self.assertEqual(updates[1].retry, "1.1")

    @patch("greaseweazle_gui.read_disk.subprocess.Popen")
    @patch("greaseweazle_gui.read_disk.shutil.which", return_value="/usr/bin/gw")
    def test_raw_detection_capture_has_no_forced_decoder(
        self, _which: object, popen: Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "disk.scp"
            destination.write_bytes(b"raw")
            popen.return_value = fake_process(["T0.0: Raw Flux\n"])

            result = read_disk(AUTO_DETECT_FORMAT, destination)

        self.assertTrue(result.succeeded)
        command = popen.call_args.args[0]
        self.assertEqual(
            command,
            [
                "/usr/bin/gw",
                "read",
                "--tracks",
                "c=0-79:h=0-1",
                str(destination),
            ],
        )


class ProgressParserTests(unittest.TestCase):
    def test_preservation_capture_includes_track_82_on_both_heads(self) -> None:
        update = parse_progress_line(
            "T82.1: Raw Flux", PRESERVATION_FORMAT
        )

        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update.track_number, 166)
        self.assertEqual(update.track_count, 166)
        self.assertEqual(update.fraction, 1.0)

    def test_calculates_track_and_sector_fraction(self) -> None:
        update = parse_progress_line(
            "T10.1: AmigaDOS (5/11 sectors) from Raw Flux", DISK_FORMATS[0]
        )

        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update.track_number, 22)
        self.assertEqual(update.cylinder, 10)
        self.assertEqual(update.head, 1)
        self.assertAlmostEqual(update.fraction, (21 + 5 / 11) / 160)

    def test_final_track_reaches_one_hundred_percent(self) -> None:
        update = parse_progress_line(
            "T79.1: AmigaDOS (11/11 sectors) from Raw Flux", DISK_FORMATS[0]
        )

        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update.fraction, 1.0)

    def test_single_sided_atari_geometry_finishes_on_head_zero(self) -> None:
        update = parse_progress_line(
            "T79.0: IBM MFM (9/9 sectors) from Raw Flux", DISK_FORMATS[5]
        )

        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update.track_count, 80)
        self.assertEqual(update.fraction, 1.0)


if __name__ == "__main__":
    unittest.main()
