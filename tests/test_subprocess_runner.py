from __future__ import annotations

import unittest
from unittest.mock import Mock

from greaseweazle_gui.subprocess_runner import run_streaming_process


def fake_process(lines: list[str], return_code: int = 0) -> Mock:
    process = Mock()
    process.stdout = lines
    process.wait.return_value = return_code
    process.poll.return_value = return_code
    return process


class StreamingProcessTests(unittest.TestCase):
    def test_streams_output_and_unregisters_process(self) -> None:
        process = fake_process(["first\n", "second\r\n"])
        factory = Mock(return_value=process)
        controller = Mock(cancelled=False)
        lines: list[str] = []

        result = run_streaming_process(
            ["gw", "info"],
            timeout=10,
            on_line=lines.append,
            controller=controller,
            process_factory=factory,
        )

        self.assertEqual(lines, ["first", "second"])
        self.assertEqual(result.output, "first\nsecond")
        self.assertEqual(result.return_code, 0)
        self.assertFalse(result.timed_out)
        self.assertFalse(result.cancelled)
        controller.register.assert_called_once_with(process)
        controller.unregister.assert_called_once_with(process)

    def test_callback_failure_kills_running_process_and_unregisters_it(self) -> None:
        process = fake_process(["line\n"])
        process.poll.return_value = None
        controller = Mock(cancelled=False)

        with self.assertRaisesRegex(RuntimeError, "callback failed"):
            run_streaming_process(
                ["gw", "read"],
                timeout=10,
                on_line=lambda _line: (_ for _ in ()).throw(
                    RuntimeError("callback failed")
                ),
                controller=controller,
                process_factory=Mock(return_value=process),
            )

        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with()
        controller.unregister.assert_called_once_with(process)


if __name__ == "__main__":
    unittest.main()
