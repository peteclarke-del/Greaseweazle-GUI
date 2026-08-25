from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from greaseweazle_gui.convert_image import convert_image
from greaseweazle_gui.disk_formats import DISK_FORMATS
from greaseweazle_gui.subprocess_runner import StreamingProcessResult


class ConvertImageTests(unittest.TestCase):
    @patch("greaseweazle_gui.convert_image.run_streaming_process")
    @patch("greaseweazle_gui.convert_image.shutil.which", return_value="/usr/bin/gw")
    def test_track_probe_preserves_sector_diagnostic(
        self, _which: object, run: object
    ) -> None:
        output = "T0.0: IBM MFM (9/9 sectors) from Bitcells"

        def convert(command: list[str], **_kwargs: object) -> StreamingProcessResult:
            Path(command[-1]).write_bytes(b"probe")
            return StreamingProcessResult(0, output, False, False)

        run.side_effect = convert
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "disk.hfe"
            destination = root / "probe.st"
            source.write_bytes(b"container")

            result = convert_image(
                source,
                destination,
                DISK_FORMATS[2],
                tracks="c=0:h=0-1",
            )

        self.assertTrue(result.succeeded)
        self.assertEqual(result.diagnostic, output)
        command = run.call_args.args[0]
        self.assertEqual(
            command[:6],
            [
                "/usr/bin/gw",
                "convert",
                "--tracks",
                "c=0:h=0-1",
                "--format",
                "atarist.720",
            ],
        )


if __name__ == "__main__":
    unittest.main()
