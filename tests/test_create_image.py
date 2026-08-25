from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from greaseweazle_gui.create_image import (
    create_blank_image,
    parse_create_progress,
)
from greaseweazle_gui.disk_formats import DISK_FORMATS


def fake_process(lines: list[str], return_code: int = 0) -> Mock:
    process = Mock()
    process.stdout = lines
    process.wait.return_value = return_code
    process.poll.return_value = return_code
    return process


class CreateImageTests(unittest.TestCase):
    @patch("greaseweazle_gui.create_image.subprocess.Popen")
    @patch("greaseweazle_gui.create_image.shutil.which", return_value="/usr/bin/gw")
    def test_rejects_read_time_scanner_format(
        self, _which: object, popen: Mock
    ) -> None:
        scanner = DISK_FORMATS[0].__class__(
            "IBM scanner", "Read-time detector", "ibm.scan", ".img", 80, 2, 0
        )

        result = create_blank_image(Path("scanner.img"), scanner)

        self.assertFalse(result.succeeded)
        popen.assert_not_called()

    @patch("greaseweazle_gui.create_image.subprocess.Popen")
    @patch("greaseweazle_gui.create_image.shutil.which", return_value="/usr/bin/gw")
    def test_creates_with_selected_format_and_atomic_output(
        self, _which: object, popen: Mock
    ) -> None:
        def start(command: list[str], **_kwargs: object) -> Mock:
            Path(command[-1]).write_bytes(b"blank image")
            return fake_process(["T0.0: IBM MFM (9/9 sectors)\n"])

        popen.side_effect = start
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "blank.st"

            result = create_blank_image(destination, DISK_FORMATS[2])

            self.assertTrue(result.succeeded)
            self.assertEqual(destination.read_bytes(), b"blank image")
        command = popen.call_args.args[0]
        self.assertEqual(
            command[0:4], ["/usr/bin/gw", "convert", "--format", "atarist.720"]
        )
        self.assertEqual(Path(command[4]).name, "empty.img")
        self.assertEqual(Path(command[5]).suffix, ".st")

    @patch("greaseweazle_gui.create_image.subprocess.Popen")
    @patch("greaseweazle_gui.create_image.shutil.which", return_value="/usr/bin/gw")
    def test_failure_does_not_replace_existing_image(
        self, _which: object, popen: Mock
    ) -> None:
        popen.return_value = fake_process(["Conversion failed\n"], return_code=1)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "blank.adf"
            destination.write_bytes(b"keep me")

            result = create_blank_image(destination, DISK_FORMATS[0])

            self.assertFalse(result.succeeded)
            self.assertEqual(destination.read_bytes(), b"keep me")
            self.assertIn("Conversion failed", result.diagnostic)

    @patch(
        "greaseweazle_gui.create_image.initialise_filesystem",
        return_value="Atari TOS FAT12",
    )
    @patch("greaseweazle_gui.create_image.subprocess.Popen")
    @patch("greaseweazle_gui.create_image.shutil.which", return_value="/usr/bin/gw")
    def test_initialises_native_image_before_encoding_hfe(
        self, _which: object, popen: Mock, initialise: Mock
    ) -> None:
        def start(command: list[str], **_kwargs: object) -> Mock:
            Path(command[-1]).write_bytes(b"image")
            return fake_process(["T79.1: IBM MFM (9/9 sectors)\n"])

        popen.side_effect = start
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "blank.hfe"

            result = create_blank_image(
                destination,
                DISK_FORMATS[2],
                initialise=True,
                volume_label="HXC",
            )

            self.assertTrue(result.succeeded)
            self.assertEqual(destination.read_bytes(), b"image")
        self.assertEqual(popen.call_count, 2)
        first, second = (call.args[0] for call in popen.call_args_list)
        self.assertEqual(Path(first[-1]).suffix, ".st")
        self.assertEqual(Path(second[-1]).suffix, ".hfe")
        initialise.assert_called_once()


class CreateProgressTests(unittest.TestCase):
    def test_final_track_reaches_complete(self) -> None:
        update = parse_create_progress(
            "T79.1: AmigaDOS (11/11 sectors)", DISK_FORMATS[0]
        )

        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update.fraction, 1.0)
        self.assertEqual(update.track_number, 160)


if __name__ == "__main__":
    unittest.main()
