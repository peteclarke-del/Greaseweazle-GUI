from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from greaseweazle_gui.disk_formats import DISK_FORMATS, RAW_FLUX_FORMAT
from greaseweazle_gui.write_disk import parse_write_progress, write_disk


def fake_process(lines: list[str], return_code: int = 0) -> Mock:
    process = Mock()
    process.stdout = lines
    process.wait.return_value = return_code
    process.poll.return_value = return_code
    return process


class WriteDiskTests(unittest.TestCase):
    @patch("greaseweazle_gui.write_disk.subprocess.Popen")
    @patch("greaseweazle_gui.write_disk.shutil.which", return_value="/usr/bin/gw")
    def test_sector_image_uses_confirmed_format(
        self, _which: object, popen: Mock
    ) -> None:
        popen.return_value = fake_process(
            ["T79.1: Writing Track\n", "All tracks verified\n"]
        )

        result = write_disk(Path("disk.adf"), DISK_FORMATS[0])

        self.assertTrue(result.succeeded)
        self.assertTrue(result.verified)
        self.assertEqual(
            popen.call_args.args[0],
            ["/usr/bin/gw", "write", "--format", "amiga.amigados", "disk.adf"],
        )

    @patch("greaseweazle_gui.write_disk.subprocess.Popen")
    @patch("greaseweazle_gui.write_disk.shutil.which", return_value="/usr/bin/gw")
    def test_raw_flux_image_is_written_without_format_conversion(
        self, _which: object, popen: Mock
    ) -> None:
        popen.return_value = fake_process(["T79.1: Writing Track\n"])

        result = write_disk(Path("protected.scp"), RAW_FLUX_FORMAT)

        self.assertTrue(result.succeeded)
        self.assertFalse(result.verified)
        self.assertIn("unavailable", result.summary)
        self.assertEqual(
            popen.call_args.args[0],
            ["/usr/bin/gw", "write", "protected.scp"],
        )

    @patch("greaseweazle_gui.write_disk.subprocess.Popen")
    @patch("greaseweazle_gui.write_disk.shutil.which", return_value="/usr/bin/gw")
    def test_failed_verification_is_reported(self, _which: object, popen: Mock) -> None:
        popen.return_value = fake_process(
            ["T2.0: Verify Failure: Retry #3\n", "Verification failed\n"],
            return_code=1,
        )

        result = write_disk(Path("disk.st"), DISK_FORMATS[2])

        self.assertFalse(result.succeeded)
        self.assertIn("Verification failed", result.diagnostic)


class WriteProgressTests(unittest.TestCase):
    def test_final_track_reaches_complete_and_reports_retry(self) -> None:
        update = parse_write_progress(
            "T79.1: Writing Track (Verify Failure: Retry #2)", DISK_FORMATS[0]
        )

        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update.fraction, 1.0)
        self.assertEqual(update.retry, "2")
        self.assertEqual(update.track_number, 160)


if __name__ == "__main__":
    unittest.main()
