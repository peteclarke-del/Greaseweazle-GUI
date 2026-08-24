from __future__ import annotations

import signal
import unittest
from unittest.mock import Mock

from greaseweazle_gui.operation import OperationController


class OperationControllerTests(unittest.TestCase):
    def test_interrupts_running_process(self) -> None:
        process = Mock()
        process.poll.return_value = None
        controller = OperationController()
        controller.register(process)

        controller.cancel()

        self.assertTrue(controller.cancelled)
        process.send_signal.assert_called_once_with(signal.SIGINT)

    def test_cancel_before_start_interrupts_on_register(self) -> None:
        process = Mock()
        process.poll.return_value = None
        controller = OperationController()
        controller.cancel()

        controller.register(process)

        process.send_signal.assert_called_once_with(signal.SIGINT)


if __name__ == "__main__":
    unittest.main()
