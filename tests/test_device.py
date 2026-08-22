from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from greaseweazle_gui.device import detect_device, parse_info_output


CONNECTED_OUTPUT = """\
Host Tools: 1.23
Device:
  Port:     /dev/ttyACM0
  Model:    Greaseweazle V4
  MCU:      AT32F403A, 216MHz, 224kB SRAM
  Firmware: 1.6
"""


class ParseInfoOutputTests(unittest.TestCase):
    def test_detects_connected_device_and_fields(self) -> None:
        result = parse_info_output(CONNECTED_OUTPUT)

        self.assertTrue(result.connected)
        self.assertEqual(result.model, "Greaseweazle V4")
        self.assertEqual(result.port, "/dev/ttyACM0")
        self.assertEqual(result.details["Firmware"], "1.6")

    def test_not_found_is_not_success(self) -> None:
        result = parse_info_output("Host Tools: 1.23\nDevice:\n  Not found\n")

        self.assertFalse(result.connected)
        self.assertIn("No connected", result.summary)

    def test_missing_device_section_is_not_success(self) -> None:
        result = parse_info_output("Host Tools: 1.23\n")

        self.assertFalse(result.connected)


class DetectDeviceTests(unittest.TestCase):
    @patch("greaseweazle_gui.device.shutil.which", return_value=None)
    def test_reports_missing_host_tool(self, _which: object) -> None:
        result = detect_device()

        self.assertFalse(result.connected)
        self.assertIn("not installed", result.summary)

    @patch("greaseweazle_gui.device.subprocess.run")
    @patch("greaseweazle_gui.device.shutil.which", return_value="/usr/bin/gw")
    def test_runs_gw_info(self, _which: object, run: object) -> None:
        run.return_value = subprocess.CompletedProcess(
            ["/usr/bin/gw", "info"], 0, CONNECTED_OUTPUT, ""
        )

        result = detect_device()

        self.assertTrue(result.connected)
        run.assert_called_once_with(
            ["/usr/bin/gw", "info"],
            capture_output=True,
            check=False,
            text=True,
            timeout=8.0,
        )

    @patch("greaseweazle_gui.device.subprocess.run")
    @patch("greaseweazle_gui.device.shutil.which", return_value="/usr/bin/gw")
    def test_reports_command_failure(self, _which: object, run: object) -> None:
        run.return_value = subprocess.CompletedProcess(
            ["/usr/bin/gw", "info"], 1, "", "Permission denied"
        )

        result = detect_device()

        self.assertFalse(result.connected)
        self.assertIn("communicate", result.summary)
        self.assertEqual(result.diagnostic, "Permission denied")


if __name__ == "__main__":
    unittest.main()

