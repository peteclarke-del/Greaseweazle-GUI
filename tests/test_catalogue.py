import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from greaseweazle_gui.catalogue import scan_catalogue
from greaseweazle_gui.image_detection import ImageFormatGuess
from greaseweazle_gui.image_inspector import ImageInspection


class CatalogueTests(unittest.TestCase):
    def test_duplicate_hashes_are_counted_and_other_files_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            folder = Path(folder_name)
            first = folder / "one.st"
            second = folder / "two.st"
            first.write_bytes(b"same")
            second.write_bytes(b"same")
            (folder / "notes.txt").write_text("ignore")

            def inspect(path: Path) -> ImageInspection:
                return ImageInspection(
                    path,
                    4,
                    "a" * 64,
                    ImageFormatGuess(None, "unknown", "unknown"),
                    None,
                    None,
                    "readable",
                )

            with patch("greaseweazle_gui.catalogue.inspect_image", inspect):
                entries = scan_catalogue(folder)
        self.assertEqual(len(entries), 2)
        self.assertEqual({entry.duplicate_count for entry in entries}, {2})

    def test_hfe_images_are_included(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            image = Path(folder_name) / "disk.hfe"
            image.write_bytes(b"hfe")
            inspection = ImageInspection(
                image,
                3,
                "b" * 64,
                ImageFormatGuess(None, "unknown", "unknown"),
                None,
                None,
                "readable",
            )
            with patch(
                "greaseweazle_gui.catalogue.inspect_image", return_value=inspection
            ):
                entries = scan_catalogue(Path(folder_name))

        self.assertEqual(tuple(entry.path.name for entry in entries), ("disk.hfe",))


if __name__ == "__main__":
    unittest.main()
