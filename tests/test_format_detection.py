from __future__ import annotations

import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from greaseweazle_gui.disk_formats import DISK_FORMATS
from greaseweazle_gui.filesystems import DiskContents
from greaseweazle_gui.format_detection import (
    conversion_score,
    detect_format,
    probe_format,
)


def track_output(cylinders: int, heads: int, recovered: int, total: int) -> str:
    return "\n".join(
        f"T{cylinder}.{head}: IBM MFM ({recovered}/{total} sectors) from Raw Flux"
        for cylinder in range(cylinders)
        for head in range(heads)
    )


class ConversionScoreTests(unittest.TestCase):
    def test_scores_complete_atari_image(self) -> None:
        disk_format = DISK_FORMATS[2]
        output = track_output(80, 2, 9, 9)

        decoded, ratio = conversion_score(output, disk_format)

        self.assertEqual(decoded, 1440)
        self.assertEqual(ratio, 1.0)

    def test_retries_do_not_double_count_sectors(self) -> None:
        disk_format = DISK_FORMATS[0]
        output = "\n".join(
            (
                "T0.0: AmigaDOS (5/11 sectors) from Raw Flux",
                "T0.0: AmigaDOS (11/11 sectors) from Raw Flux (Retry #1.1)",
            )
        )

        decoded, _ratio = conversion_score(output, disk_format)

        self.assertEqual(decoded, 11)


class DetectFormatTests(unittest.TestCase):
    @patch("greaseweazle_gui.format_detection.subprocess.run")
    @patch("greaseweazle_gui.format_detection.shutil.which", return_value="/usr/bin/gw")
    def test_probe_tracks_follow_candidate_geometry(
        self, _which: object, run: object
    ) -> None:
        disk_format = DISK_FORMATS[0]
        short_format = type(disk_format)(
            "Commodore 1541", "", "commodore.1541", ".d64", 35, 1, 21
        )
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "disk.hfe"
            raw.write_bytes(b"container")

            detect_format(raw, root, candidates=(short_format,))

        self.assertIn("c=0,17,34:h=0-0", run.call_args.args[0])

    @patch("greaseweazle_gui.format_detection.open_image")
    @patch("greaseweazle_gui.format_detection.subprocess.run")
    @patch("greaseweazle_gui.format_detection.shutil.which", return_value="/usr/bin/gw")
    def test_prefers_layout_explaining_more_sectors(
        self, _which: object, run: object, open_disk: object
    ) -> None:
        contents = DiskContents("TEST", ())
        open_disk.return_value = contents

        def convert(
            command: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            disk_format_name = command[command.index("--format") + 1]
            destination = Path(command[-1])
            if disk_format_name == "atarist.360":
                destination.write_bytes(b"candidate")
                output = track_output(80, 1, 9, 9)
                return subprocess.CompletedProcess(command, 0, output, "")
            if disk_format_name == "atarist.720":
                destination.write_bytes(b"candidate")
                output = track_output(80, 2, 9, 9)
                return subprocess.CompletedProcess(command, 0, output, "")
            return subprocess.CompletedProcess(command, 0, "", "")

        run.side_effect = convert
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "disk.scp"
            raw.write_bytes(b"raw")

            result = detect_format(raw, root)

        self.assertIsNotNone(result.disk_format)
        assert result.disk_format is not None
        self.assertEqual(result.disk_format.gw_format, "atarist.720")
        self.assertEqual(result.confidence, 1.0)

    @patch("greaseweazle_gui.format_detection.subprocess.run")
    @patch("greaseweazle_gui.format_detection.shutil.which", return_value="/usr/bin/gw")
    def test_cylinder_zero_bpb_identifies_atari_800k_subtype(
        self, _which: object, run: object
    ) -> None:
        disk_format = DISK_FORMATS[3]

        def convert(
            command: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            boot = bytearray(512)
            struct.pack_into("<H", boot, 11, 512)
            boot[13] = 2
            struct.pack_into("<H", boot, 14, 1)
            boot[16] = 2
            struct.pack_into("<H", boot, 17, 112)
            struct.pack_into("<H", boot, 19, 1600)
            struct.pack_into("<H", boot, 22, 3)
            struct.pack_into("<H", boot, 24, 10)
            struct.pack_into("<H", boot, 26, 2)
            Path(command[-1]).write_bytes(boot)
            output = "\n".join(
                f"T0.{head}: IBM MFM (10/10 sectors) from Raw Flux" for head in range(2)
            )
            return subprocess.CompletedProcess(command, 0, output, "")

        run.side_effect = convert
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "probe.scp"
            raw.write_bytes(b"raw")

            result = probe_format(raw, root, candidates=(disk_format,))

        self.assertEqual(result.disk_format, disk_format)
        self.assertEqual(result.confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
