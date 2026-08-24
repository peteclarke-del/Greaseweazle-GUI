import tempfile
import unittest
from pathlib import Path

from greaseweazle_gui.filesystems import open_image


def sector_offset(track: int, sector: int) -> int:
    zones = [21] * 17 + [19] * 7 + [18] * 6 + [17] * 5
    return (sum(zones[: track - 1]) + sector) * 256


class CommodoreD64Tests(unittest.TestCase):
    def test_catalogue_and_file_chain(self) -> None:
        image_data = bytearray(174848)
        bam = sector_offset(18, 0)
        image_data[bam + 0x90 : bam + 0xA0] = b"GAMES".ljust(16, b"\xa0")
        directory = sector_offset(18, 1)
        entry = directory + 2
        image_data[entry] = 0x82
        image_data[entry + 1] = 1
        image_data[entry + 2] = 0
        image_data[entry + 3 : entry + 19] = b"HELLO".ljust(16, b"\xa0")
        image_data[entry + 30] = 1
        first_sector = sector_offset(1, 0)
        image_data[first_sector] = 0
        image_data[first_sector + 1] = 6
        image_data[first_sector + 2 : first_sector + 7] = b"world"
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "disk.d64"
            image.write_bytes(image_data)
            contents = open_image(image)
        self.assertEqual(contents.volume_label, "GAMES")
        self.assertEqual(contents.entries[0].name, "HELLO")
        self.assertEqual(contents.entries[0].size, 5)
        self.assertEqual(contents.entries[0].read_bytes(), b"world")


if __name__ == "__main__":
    unittest.main()
