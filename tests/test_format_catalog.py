from __future__ import annotations

import unittest

from greaseweazle_gui.format_catalog import (
    _image_suffix,
    format_menu_label,
    manufacturer_name,
    parse_format_names,
)


class FormatCatalogTests(unittest.TestCase):
    def test_non_contiguous_epson_layout_uses_flux_container(self) -> None:
        self.assertEqual(_image_suffix("epson.qx10.logo"), ".scp")

    def test_parses_and_sorts_greaseweazle_help_formats(self) -> None:
        help_text = """
FORMAT options:
commodore.1541  acorn.dfs.ss  atarist.800
atari.90        amiga.amigados

Supported file suffixes:
.adf .st .img
"""

        self.assertEqual(
            parse_format_names(help_text),
            (
                "acorn.dfs.ss",
                "amiga.amigados",
                "atari.90",
                "atarist.800",
                "commodore.1541",
            ),
        )

    def test_groups_atari_families_under_one_manufacturer(self) -> None:
        self.assertEqual(manufacturer_name("atari.90"), "Atari")
        self.assertEqual(manufacturer_name("atarist.800"), "Atari")
        self.assertEqual(format_menu_label("atari.90"), "8-bit — 90")
        self.assertEqual(format_menu_label("atarist.800"), "ST — 800")

    def test_groups_apple_ii_and_macintosh_under_apple(self) -> None:
        self.assertEqual(manufacturer_name("apple2.prodos.140"), "Apple")
        self.assertEqual(manufacturer_name("mac.800"), "Apple")
        self.assertEqual(
            format_menu_label("apple2.prodos.140"), "Apple II — prodos.140"
        )
        self.assertEqual(format_menu_label("mac.800"), "Macintosh — 800")


if __name__ == "__main__":
    unittest.main()
