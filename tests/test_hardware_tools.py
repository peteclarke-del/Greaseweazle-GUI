import unittest
from unittest.mock import Mock, patch

from greaseweazle_gui.hardware_tools import run_hardware_tool


class HardwareToolsTests(unittest.TestCase):
    @patch("greaseweazle_gui.hardware_tools.subprocess.Popen")
    @patch("greaseweazle_gui.hardware_tools.shutil.which", return_value="/usr/bin/gw")
    def test_rpm_uses_selected_drive_and_five_samples(
        self, _which: object, popen: Mock
    ) -> None:
        process = popen.return_value
        process.communicate.return_value = ("300.1 RPM\n", None)
        process.returncode = 0
        process.poll.return_value = 0
        result = run_hardware_tool("rpm", drive="B")
        self.assertTrue(result.succeeded)
        self.assertEqual(
            popen.call_args.args[0],
            ["/usr/bin/gw", "rpm", "--drive", "B", "--nr", "5"],
        )

    def test_rejects_unknown_tool(self) -> None:
        result = run_hardware_tool("erase")
        self.assertFalse(result.succeeded)


if __name__ == "__main__":
    unittest.main()
