from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from greaseweazle_gui.browse_image import (
    browsable_image_suffixes,
    open_browsable_image,
)
from greaseweazle_gui.convert_image import ConvertImageResult
from greaseweazle_gui.disk_formats import DiskFormat
from greaseweazle_gui.filesystems import DiskContents, FilesystemError
from greaseweazle_gui.image_detection import ImageFormatGuess


class BrowseImageTests(unittest.TestCase):
    def test_browser_offers_native_and_track_container_suffixes(self) -> None:
        self.assertEqual(
            browsable_image_suffixes(),
            frozenset(
                {
                    ".adf",
                    ".st",
                    ".img",
                    ".ima",
                    ".ssd",
                    ".dsd",
                    ".d64",
                    ".hfe",
                    ".scp",
                    ".a2r",
                }
            ),
        )

    @patch("greaseweazle_gui.browse_image.detect_image_format")
    @patch("greaseweazle_gui.browse_image.open_image")
    def test_native_sector_image_opens_without_conversion(
        self, open_native: object, detect: object
    ) -> None:
        disk_format = DiskFormat("Atari ST", "", "atarist.720", ".st", 80, 2, 9)
        open_native.return_value = DiskContents("WORK", ())
        detect.return_value = ImageFormatGuess(disk_format, "content", "FAT12")

        opened = open_browsable_image(Path("work.st"), Path("/tmp"))

        self.assertEqual(opened.image_path, Path("work.st"))
        self.assertEqual(opened.contents.format_label, "Atari ST")

    @patch("greaseweazle_gui.browse_image.open_image")
    @patch("greaseweazle_gui.browse_image.convert_image")
    @patch("greaseweazle_gui.browse_image.detect_image_format")
    @patch("greaseweazle_gui.browse_image.supported_formats")
    def test_hfe_decodes_through_every_browseable_filesystem_format(
        self,
        formats: object,
        detect: object,
        convert: object,
        open_decoded: object,
    ) -> None:
        candidates = (
            DiskFormat("Amiga", "", "amiga.amigados", ".adf", 80, 2, 11),
            DiskFormat("Atari", "", "atarist.720", ".st", 80, 2, 9),
            DiskFormat("Acorn", "", "acorn.dfs.ds80", ".dsd", 80, 2, 10),
            DiskFormat("Commodore", "", "commodore.1541", ".d64", 35, 1, 21),
            DiskFormat("Unsupported", "", "apple2.prodos.140", ".po", 35, 1, 16),
        )
        formats.return_value = candidates
        container = DiskFormat("HxC HFE v1", "", "", ".hfe", 80, 2, 0, True)
        detect.return_value = ImageFormatGuess(container, "content", "HFE")
        convert.side_effect = (
            ConvertImageResult(
                True, "probed", "T0.0: AmigaDOS (11/11 sectors) from Bitcells"
            ),
            ConvertImageResult(True, "decoded"),
        )
        open_decoded.return_value = DiskContents("GAMES", (), "Amiga")

        opened = open_browsable_image(Path("games.hfe"), Path("/tmp"))

        self.assertEqual(
            opened.disk_format.gw_format,
            "amiga.amigados",
        )
        convert.assert_any_call(
            Path("games.hfe"),
            Path("/tmp/browse-probe-1.adf"),
            candidates[0],
            controller=None,
            timeout=30,
            tracks="c=0:h=0-1",
        )
        self.assertEqual(convert.call_count, 2)

    @patch("greaseweazle_gui.browse_image.open_image")
    @patch("greaseweazle_gui.browse_image.convert_image")
    @patch("greaseweazle_gui.browse_image.detect_image_format")
    @patch("greaseweazle_gui.browse_image.supported_formats")
    def test_hfe_continues_until_a_filesystem_validates(
        self,
        formats: object,
        detect: object,
        convert: object,
        open_decoded: object,
    ) -> None:
        amiga = DiskFormat("Amiga", "", "amiga.amigados", ".adf", 80, 2, 11)
        atari = DiskFormat("Atari", "", "atarist.720", ".st", 80, 2, 9)
        formats.return_value = (amiga, atari)
        container = DiskFormat("HxC HFE v1", "", "", ".hfe", 80, 2, 0, True)
        detect.return_value = ImageFormatGuess(container, "content", "HFE")
        probe = ConvertImageResult(
            True, "probed", "T0.0: IBM MFM (9/9 sectors) from Bitcells"
        )
        convert.side_effect = (
            probe,
            ConvertImageResult(True, "decoded"),
            probe,
            ConvertImageResult(True, "decoded"),
        )
        open_decoded.side_effect = (
            FilesystemError("not AmigaDOS"),
            DiskContents("WORK", (), "Atari ST FAT12"),
        )

        opened = open_browsable_image(Path("work.hfe"), Path("/tmp"))

        self.assertEqual(opened.disk_format, atari)
        self.assertEqual(convert.call_count, 4)

    @patch("greaseweazle_gui.browse_image.detect_image_format")
    def test_invalid_hfe_fails_before_decoder_is_run(self, detect: object) -> None:
        detect.return_value = ImageFormatGuess(None, "unknown", "Invalid HFE header")

        with self.assertRaisesRegex(FilesystemError, "could not be decoded safely"):
            open_browsable_image(Path("broken.hfe"), Path("/tmp"))


if __name__ == "__main__":
    unittest.main()
