"""GTK application lifecycle."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib  # noqa: E402

from .branding import APPLICATION_ID, APPLICATION_NAME
from .window import MainWindow


class GreaseweazleApplication(Adw.Application):
    """Greaseweazle-GUI desktop application."""

    def __init__(
        self, application_id: str = APPLICATION_ID, *, unique: bool = True
    ) -> None:
        # The interface tests pass their own id and unique=False, so that a
        # copy of the application already running does not take their window.
        flags = Gio.ApplicationFlags.DEFAULT_FLAGS
        if not unique:
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        GLib.set_application_name(APPLICATION_NAME)
        super().__init__(application_id=application_id, flags=flags)
        self.set_accels_for_action("win.help", ["F1"])
        # Set by the window after an update, so main() starts the new version.
        self.restart_requested = False

    def do_activate(self) -> None:
        window = self.get_active_window()
        if window is None:
            window = MainWindow(application=self)
            window.present()
            documentation_state = os.environ.get("GREASEWEAZLE_GUI_DOCUMENTATION_STATE")
            if documentation_state:
                window.show_documentation_state(documentation_state)
            else:
                window.begin_device_detection()
        else:
            window.present()
