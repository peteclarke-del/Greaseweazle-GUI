"""Main application window."""

from __future__ import annotations

import threading
import tempfile
import shutil
from datetime import datetime
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .browser import DiskBrowser
from .branding import APPLICATION_NAME, APPLICATION_SUBTITLE
from .capture_profiles import CAPTURE_PROFILES
from .capture_metadata import write_capture_report
from .capture_compare import CaptureComparison, compare_captures
from .catalogue import CatalogueEntry, scan_catalogue
from .create_image import (
    NON_CREATABLE_FORMATS,
    CreateImageProgress,
    CreateImageResult,
    create_blank_image,
)
from .convert_image import ConvertImageResult, convert_image
from .device import DeviceProbeResult, detect_device
from .disk_formats import (
    AUTO_DETECT_FORMAT,
    DISK_FORMATS,
    PRESERVATION_FORMAT,
    PROBE_FORMAT,
    RAW_FLUX_FORMAT,
    DiskFormat,
)
from .filesystems import DiskContents, FilesystemError, ImageEntry, open_image
from .filesystem_formatters import filesystem_support_name
from .format_catalog import (
    format_menu_label,
    grouped_formats,
    manufacturer_name,
    supported_formats,
)
from .format_detection import (
    DetectionProgress,
    DetectionResult,
    detect_format,
    probe_format,
)
from .image_detection import ImageFormatGuess, detect_image_format
from .image_inspector import ImageInspection, inspect_image
from .hardware_tools import HardwareToolResult, run_hardware_tool
from .help_view import HelpView
from .operation import OperationController
from .read_disk import ReadProgress, ReadResult, read_disk
from .retry_tracks import RetryTracksResult, retry_damaged_tracks
from .track_health import (
    TrackCondition,
    TrackHealth,
    TrackHealthReport,
    build_track_health,
    build_write_health,
)
from .write_disk import WriteProgress, WriteResult, write_disk


class MainWindow(Adw.ApplicationWindow):
    """Initial application window and startup-device gate."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.set_title(APPLICATION_NAME)
        self.set_default_size(720, 560)
        self.set_size_request(460, 400)
        self._temporary_directories: list[tempfile.TemporaryDirectory[str]] = []
        self._file_chooser: Gtk.FileChooserNative | None = None
        self._active_operation: OperationController | None = None
        self._host_tools_available = False
        self._diagnostic_log: list[str] = []
        self._save_capture_report = True
        self._device_model = "Unknown Greaseweazle"
        self._device_port = "Unknown port"
        self._device_connected = False
        self._device_detection_active = False
        self._initial_detection_complete = False
        self._drive = "A"
        self._capture_profile = CAPTURE_PROFILES[0]

        self._create_window_actions()
        toolbar_view = Adw.ToolbarView()
        self._header_bar = Adw.HeaderBar()
        self._back_button = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self._back_button.set_tooltip_text("Back to start")
        self._back_button.set_visible(False)
        self._back_button.connect("clicked", self._go_back)
        self._header_bar.pack_start(self._back_button)
        self._window_title = Adw.WindowTitle(
            title=APPLICATION_NAME, subtitle=APPLICATION_SUBTITLE
        )
        self._header_bar.set_title_widget(self._window_title)
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_button.set_tooltip_text("Main menu")
        menu_button.set_menu_model(self._build_main_menu())
        self._header_bar.pack_end(menu_button)
        toolbar_view.add_top_bar(self._header_bar)
        self.set_content(toolbar_view)

        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        toolbar_view.set_content(self._stack)
        self._stack.add_named(self._build_checking_page(), "checking")
        self._stack.add_named(self._build_dashboard(), "dashboard")
        self._stack.add_named(self._build_reading_page(), "reading")
        self._stack.connect("notify::visible-child-name", self._visible_page_changed)
        self._stack.set_visible_child_name("checking")
        GLib.timeout_add_seconds(5, self._poll_device)

    def _go_back(self, _button: Gtk.Button) -> None:
        if self._stack.get_visible_child_name() == "browser":
            self._leave_browser()
        else:
            self._show_dashboard()

    def _visible_page_changed(
        self, _stack: Gtk.Stack, _property: object
    ) -> None:
        name = self._stack.get_visible_child_name()
        self._window_title.set_title(APPLICATION_NAME)
        self._window_title.set_subtitle(APPLICATION_SUBTITLE)
        if name == "dashboard":
            self._back_button.set_visible(False)
        elif name == "checking":
            self._back_button.set_visible(False)
        elif name == "reading":
            self._back_button.set_visible(False)
        elif name == "browser":
            self._back_button.set_visible(True)

    def _create_window_actions(self) -> None:
        callbacks: dict[str, Callable[[], None]] = {
            "open-image": lambda: self._choose_existing_image(None),
            "inspect-image": lambda: self._choose_inspection_image(None),
            "image-library": lambda: self._choose_catalogue_folder(None),
            "create-image": lambda: self._choose_blank_format(None),
            "read-disk": lambda: self._ask_read_format(None, save_image=False),
            "extract-image": lambda: self._ask_read_format(None, save_image=True),
            "write-disk": lambda: self._choose_write_image(None),
            "retry-device": self.begin_device_detection,
            "rpm": lambda: self._start_hardware_tool("rpm"),
            "bandwidth": lambda: self._start_hardware_tool("bandwidth"),
            "clean": lambda: self._confirm_drive_clean(None),
            "help": self._show_help,
            "diagnostics": lambda: self._show_diagnostic_log(None),
            "quit": self.close,
        }
        self._window_actions: dict[str, Gio.SimpleAction] = {}
        for name, callback in callbacks.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _action, _parameter, fn=callback: fn())
            self.add_action(action)
            self._window_actions[name] = action
        for name in ("read-disk", "extract-image", "write-disk", "rpm", "bandwidth", "clean"):
            self._window_actions[name].set_enabled(False)
        self._window_actions["create-image"].set_enabled(False)

        drive = Gio.SimpleAction.new_stateful(
            "drive", GLib.VariantType.new("s"), GLib.Variant("s", "A")
        )

        def select_drive(action: Gio.SimpleAction, value: GLib.Variant) -> None:
            self._drive = value.get_string()
            action.set_state(value)
            self._refresh_welcome_status()

        drive.connect("activate", select_drive)
        self.add_action(drive)
        self._window_actions["drive"] = drive

    def _build_main_menu(self) -> Gio.MenuModel:
        root = Gio.Menu()
        file_menu = Gio.Menu()
        file_menu.append("Open Disk Image…", "win.open-image")
        file_menu.append("Inspect or Convert Image…", "win.inspect-image")
        file_menu.append("Image Library…", "win.image-library")
        file_menu.append("Create Blank Image…", "win.create-image")
        file_menu.append("Quit", "win.quit")
        root.append_submenu("File", file_menu)

        disk_menu = Gio.Menu()
        disk_menu.append("Read and Browse Disk…", "win.read-disk")
        disk_menu.append("Extract Disk to Image…", "win.extract-image")
        disk_menu.append("Write Image to Disk…", "win.write-disk")
        root.append_submenu("Disk", disk_menu)

        drive_menu = Gio.Menu()
        drive_choice = Gio.Menu()
        for drive_name in ("A", "B"):
            item = Gio.MenuItem.new(f"Drive {drive_name}", None)
            item.set_action_and_target_value(
                "win.drive", GLib.Variant("s", drive_name)
            )
            drive_choice.append_item(item)
        drive_menu.append_section(None, drive_choice)
        drive_menu.append("Measure Spindle Speed", "win.rpm")
        drive_menu.append("Test USB Bandwidth", "win.bandwidth")
        drive_menu.append("Clean Drive Heads…", "win.clean")
        drive_menu.append("Reconnect Device", "win.retry-device")
        root.append_submenu("Drive", drive_menu)

        help_menu = Gio.Menu()
        help_menu.append("User Guide", "win.help")
        help_menu.append("Diagnostic Log", "win.diagnostics")
        root.append_submenu("Help", help_menu)
        return root

    def _show_help(self) -> None:
        self.set_default_size(1080, 760)
        self._show_workspace(
            "User Guide",
            "Operations, preservation guidance, and technical reference",
            HelpView(),
        )

    def _build_checking_page(self) -> Gtk.Widget:
        page = Adw.StatusPage()
        page.set_icon_name("drive-removable-media-symbolic")
        page.set_title("Looking for Greaseweazle…")
        page.set_description("Checking the USB connection")
        spinner = Gtk.Spinner(spinning=True)
        spinner.set_size_request(32, 32)
        page.set_child(spinner)
        return page

    def _build_reading_page(self) -> Gtk.Widget:
        self._reading_page = Adw.StatusPage()
        self._reading_page.set_icon_name("media-floppy-symbolic")
        self._reading_page.set_title("Reading disk…")
        self._reading_page.set_description(
            "Keep the drive connected and do not remove the disk."
        )
        progress_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=12,
            width_request=380,
        )
        self._read_progress = Gtk.ProgressBar(show_text=True)
        self._read_progress.set_fraction(0)
        self._read_progress.set_text("0%")
        progress_box.append(self._read_progress)
        self._progress_track = Gtk.Label(xalign=0, label="Preparing drive…")
        self._progress_track.add_css_class("heading")
        progress_box.append(self._progress_track)
        self._progress_sectors = Gtk.Label(xalign=0)
        self._progress_sectors.add_css_class("dim-label")
        progress_box.append(self._progress_sectors)
        self._progress_message = Gtk.Label(xalign=0, ellipsize=3)
        self._progress_message.add_css_class("dim-label")
        progress_box.append(self._progress_message)
        self._cancel_operation_button = Gtk.Button(
            label="Cancel operation", halign=Gtk.Align.CENTER, visible=False
        )
        self._cancel_operation_button.connect(
            "clicked", self._cancel_current_operation
        )
        progress_box.append(self._cancel_operation_button)
        self._reading_page.set_child(progress_box)
        return self._reading_page

    def _begin_cancellable_operation(self) -> OperationController:
        controller = OperationController()
        self._active_operation = controller
        self._cancel_operation_button.set_visible(True)
        self._cancel_operation_button.set_sensitive(True)
        return controller

    def _cancel_current_operation(self, _button: Gtk.Button) -> None:
        if self._active_operation is None:
            return
        self._active_operation.cancel()
        self._cancel_operation_button.set_sensitive(False)
        self._progress_message.set_text("Cancelling safely…")

    def _end_cancellable_operation(self) -> None:
        self._active_operation = None
        self._cancel_operation_button.set_visible(False)

    def _build_dashboard(self) -> Gtk.Widget:
        self._welcome_page = Adw.StatusPage(
            icon_name="media-floppy-symbolic",
            title="Floppy disk workspace",
            description="Checking the Greaseweazle connection…",
        )
        quick_actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            halign=Gtk.Align.CENTER,
        )
        open_image = Gtk.Button(label="Open Image…")
        open_image.add_css_class("suggested-action")
        open_image.set_action_name("win.open-image")
        quick_actions.append(open_image)
        self._browse_disk_button = Gtk.Button(label="Read Disk…", sensitive=False)
        self._browse_disk_button.set_action_name("win.read-disk")
        quick_actions.append(self._browse_disk_button)
        self._welcome_page.set_child(quick_actions)
        return self._welcome_page

    def _refresh_welcome_status(self) -> None:
        if not hasattr(self, "_welcome_page"):
            return
        if self._device_connected:
            self._welcome_page.set_description(
                f"{self._device_model} on {self._device_port} • Drive {self._drive}"
            )
        elif self._host_tools_available:
            self._welcome_page.set_description(
                "No Greaseweazle connected • Image tools remain available"
            )
        else:
            self._welcome_page.set_description(
                "Greaseweazle host tools unavailable • Browse supported images offline"
            )

    def _show_dashboard(self) -> None:
        self.set_default_size(720, 560)
        self._window_title.set_title(APPLICATION_NAME)
        self._window_title.set_subtitle(APPLICATION_SUBTITLE)
        self._back_button.set_visible(False)
        self._stack.set_visible_child_name("dashboard")

    def _show_workspace(
        self,
        title: str,
        subtitle: str,
        content: Gtk.Widget,
        actions: tuple[Gtk.Widget, ...] = (),
    ) -> None:
        page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=18,
            margin_bottom=18,
            margin_start=18,
            margin_end=18,
        )
        if actions:
            action_bar = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=8,
                halign=Gtk.Align.END,
            )
            for action in actions:
                action_bar.append(action)
            page.append(action_bar)
        content.set_vexpand(True)
        page.append(content)
        existing = self._stack.get_child_by_name("workspace")
        if existing is not None:
            self._stack.remove(existing)
        self._stack.add_named(page, "workspace")
        self._window_title.set_title(APPLICATION_NAME)
        self._window_title.set_subtitle(APPLICATION_SUBTITLE)
        self._back_button.set_visible(True)
        self._stack.set_visible_child_name("workspace")

    def _show_result(
        self,
        title: str,
        subtitle: str,
        body: str,
        actions: tuple[Gtk.Widget, ...] = (),
    ) -> None:
        page = Adw.StatusPage(
            icon_name="emblem-ok-symbolic",
            title=title,
            description=body,
        )
        self._show_workspace(title, subtitle, page, actions)

    def _choose_catalogue_folder(self, _button: Gtk.Button | None) -> None:
        chooser = Gtk.FileChooserNative.new(
            "Choose image library folder",
            self,
            Gtk.FileChooserAction.SELECT_FOLDER,
            "Catalogue",
            "Cancel",
        )
        chooser.connect("response", self._on_catalogue_folder)
        self._file_chooser = chooser
        chooser.show()

    def _on_catalogue_folder(
        self, chooser: Gtk.FileChooserNative, response: int
    ) -> None:
        self._file_chooser = None
        if response != Gtk.ResponseType.ACCEPT:
            return
        selected = chooser.get_file()
        selected_path = selected.get_path() if selected is not None else None
        if selected_path is None:
            return
        folder = Path(selected_path)
        self._reading_page.set_title("Building image catalogue…")
        self._reading_page.set_description("Images are inspected read-only; no database is uploaded.")
        self._read_progress.set_text("")
        self._progress_track.set_text(str(folder))
        self._progress_sectors.set_text("Hashing and detecting image formats…")
        self._progress_message.set_text("")
        self._stack.set_visible_child_name("reading")

        def worker() -> None:
            try:
                entries = scan_catalogue(folder)
            except OSError as error:
                GLib.idle_add(self._finish_catalogue_error, str(error))
                return
            GLib.idle_add(self._finish_catalogue, folder, entries)

        threading.Thread(target=worker, name="image-catalogue", daemon=True).start()

    def _finish_catalogue_error(self, diagnostic: str) -> bool:
        self._stack.set_visible_child_name("dashboard")
        self._show_error("Unable to build catalogue", "The folder could not be scanned.", diagnostic)
        return GLib.SOURCE_REMOVE

    def _finish_catalogue(
        self, folder: Path, entries: tuple[CatalogueEntry, ...]
    ) -> bool:
        duplicates = sum(entry.duplicate_count > 1 for entry in entries)
        listing = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        for entry in entries:
            row = Adw.ActionRow(
                title=entry.path.name,
                subtitle=(
                    f"{entry.format_label} • {entry.volume_label or entry.filesystem or 'unrecognised filesystem'}"
                ),
            )
            if entry.duplicate_count > 1:
                badge = Gtk.Label(label=f"{entry.duplicate_count} copies", css_classes=["warning"])
                row.add_suffix(badge)
            row.set_tooltip_text(f"{entry.path}\nSHA-256 {entry.sha256}")
            listing.append(row)
        scroller = Gtk.ScrolledWindow(min_content_height=360, max_content_height=520)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(listing)
        rescan = Gtk.Button(label="Choose Another Folder…")
        rescan.connect("clicked", self._choose_catalogue_folder)
        self._show_workspace(
            "Image Library",
            f"{len(entries)} image(s) in {folder.name} • {duplicates} duplicate file(s)",
            scroller,
            (rescan,),
        )
        return GLib.SOURCE_REMOVE

    def _confirm_drive_clean(self, _button: Gtk.Button | None) -> None:
        dialog = Adw.MessageDialog.new(
            self,
            "Insert a cleaning disk",
            "Do not run this operation with a data disk. Greaseweazle will move the heads across the selected drive three times.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clean", "Start cleaning")
        dialog.set_response_appearance("clean", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect(
            "response",
            lambda _dialog, response: self._start_hardware_tool("clean")
            if response == "clean"
            else None,
        )
        dialog.present()

    def _start_hardware_tool(self, action: str) -> None:
        labels = {
            "rpm": ("Measuring drive speed…", "Keep a disk inserted while RPM is measured."),
            "bandwidth": ("Testing USB bandwidth…", "No disk access is performed."),
            "clean": ("Cleaning drive heads…", "Keep the cleaning disk inserted."),
        }
        title, description = labels[action]
        self._reading_page.set_title(title)
        self._reading_page.set_description(description)
        self._read_progress.set_text("")
        self._read_progress.pulse()
        self._progress_track.set_text(f"Drive {self._drive}")
        self._progress_sectors.set_text("Greaseweazle hardware utility")
        self._progress_message.set_text("")
        self._stack.set_visible_child_name("reading")
        controller = self._begin_cancellable_operation()

        def worker() -> None:
            try:
                result = run_hardware_tool(
                    action, drive=self._drive, controller=controller
                )
            except Exception as error:
                result = HardwareToolResult(
                    False,
                    "The hardware utility stopped unexpectedly.",
                    f"{type(error).__name__}: {error}",
                )
            GLib.idle_add(self._finish_hardware_tool, result)

        threading.Thread(target=worker, name=f"gw-{action}", daemon=True).start()

    def _finish_hardware_tool(self, result: HardwareToolResult) -> bool:
        self._end_cancellable_operation()
        if not result.succeeded:
            self._show_dashboard()
            self._show_error("Hardware operation failed", result.summary, result.output)
            return GLib.SOURCE_REMOVE
        view = Gtk.TextView(
            editable=False,
            cursor_visible=False,
            monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
        )
        view.get_buffer().set_text(result.output or "Complete")
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(view)
        self._show_workspace(result.summary, f"Drive {self._drive}", scroller)
        return GLib.SOURCE_REMOVE

    def _choose_inspection_image(self, _button: Gtk.Button | None) -> None:
        chooser = Gtk.FileChooserNative.new(
            "Inspect disk image",
            self,
            Gtk.FileChooserAction.OPEN,
            "Inspect",
            "Cancel",
        )
        image_filter = Gtk.FileFilter()
        image_filter.set_name("Disk images")
        for pattern in (
            "*.adf", "*.st", "*.scp", "*.a2r", "*.img", "*.ima",
            "*.ssd", "*.dsd", "*.adm", "*.ads", "*.adl", "*.do",
            "*.po", "*.d64", "*.d71", "*.d81", "*.d1m", "*.d2m",
            "*.d4m", "*.sf7",
        ):
            image_filter.add_pattern(pattern)
        chooser.add_filter(image_filter)
        chooser.connect("response", self._on_inspection_image_selected)
        self._file_chooser = chooser
        chooser.show()

    def _on_inspection_image_selected(
        self, chooser: Gtk.FileChooserNative, response: int
    ) -> None:
        self._file_chooser = None
        if response != Gtk.ResponseType.ACCEPT:
            return
        selected = chooser.get_file()
        selected_path = selected.get_path() if selected is not None else None
        if selected_path is None:
            self._show_error("Choose a local image", "Inspection requires a local file.")
            return
        image_path = Path(selected_path)
        self._reading_page.set_title("Inspecting disk image…")
        self._reading_page.set_description("Reading metadata and calculating SHA-256.")
        self._read_progress.set_fraction(0)
        self._read_progress.set_text("")
        self._progress_track.set_text(image_path.name)
        self._progress_sectors.set_text("Validating image and filesystem…")
        self._progress_message.set_text("")
        self._stack.set_visible_child_name("reading")

        def worker() -> None:
            try:
                inspection = inspect_image(image_path)
            except OSError as error:
                GLib.idle_add(
                    self._finish_inspection_error, image_path, str(error)
                )
                return
            GLib.idle_add(self._finish_inspection, inspection)

        threading.Thread(target=worker, name="image-inspector", daemon=True).start()

    def _finish_inspection_error(self, image_path: Path, diagnostic: str) -> bool:
        self._stack.set_visible_child_name("dashboard")
        self._show_error(
            "Unable to inspect image", f"{image_path.name} could not be read.", diagnostic
        )
        return GLib.SOURCE_REMOVE

    def _finish_inspection(self, inspection: ImageInspection) -> bool:
        disk_format = inspection.guess.disk_format
        geometry = (
            f"{disk_format.cylinders} cylinders × {disk_format.heads} heads"
            if disk_format is not None
            else "Unknown"
        )
        rows = (
            ("Format", disk_format.label if disk_format is not None else "Unknown"),
            ("Detection", inspection.guess.explanation),
            ("Geometry", geometry),
            ("Size", f"{inspection.size:,} bytes"),
            ("Filesystem", inspection.filesystem or "Not browseable"),
            ("Volume", inspection.volume_label or "—"),
            ("Integrity", inspection.integrity),
            ("SHA-256", inspection.sha256),
        )
        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin_top=8)
        for row, (label, value) in enumerate(rows):
            grid.attach(Gtk.Label(label=label, xalign=1, css_classes=["heading"]), 0, row, 1, 1)
            value_label = Gtk.Label(label=value, xalign=0, selectable=True, wrap=True)
            value_label.set_max_width_chars(60)
            grid.attach(value_label, 1, row, 1, 1)
        compare_button = Gtk.Button(label="Compare…")
        compare_button.connect(
            "clicked", lambda _button: self._choose_comparison_image(inspection.path)
        )
        actions: list[Gtk.Widget] = [compare_button]
        if self._host_tools_available:
            convert_button = Gtk.Button(label="Convert…")
            convert_button.add_css_class("suggested-action")
            convert_button.connect(
                "clicked", lambda _button: self._choose_conversion_format(inspection)
            )
            actions.append(convert_button)
        clamp = Adw.Clamp(maximum_size=760)
        clamp.set_child(grid)
        self._show_workspace(
            inspection.path.name,
            "Disk image details",
            clamp,
            tuple(actions),
        )
        return GLib.SOURCE_REMOVE

    def _choose_comparison_image(self, first: Path) -> None:
        chooser = Gtk.FileChooserNative.new(
            "Compare with disk image",
            self,
            Gtk.FileChooserAction.OPEN,
            "Compare",
            "Cancel",
        )
        chooser.connect("response", self._on_comparison_image, first)
        self._file_chooser = chooser
        chooser.show()

    def _on_comparison_image(
        self, chooser: Gtk.FileChooserNative, response: int, first: Path
    ) -> None:
        self._file_chooser = None
        if response != Gtk.ResponseType.ACCEPT:
            return
        selected = chooser.get_file()
        selected_path = selected.get_path() if selected is not None else None
        if selected_path is None:
            return
        second = Path(selected_path)
        self._reading_page.set_title("Comparing captures…")
        self._reading_page.set_description("Hashing both images and comparing track sides.")
        self._progress_track.set_text(f"{first.name} ↔ {second.name}")
        self._progress_sectors.set_text("The images are read-only")
        self._progress_message.set_text("")
        self._read_progress.set_text("")
        self._stack.set_visible_child_name("reading")

        def worker() -> None:
            try:
                comparison = compare_captures(first, second)
            except OSError as error:
                GLib.idle_add(self._finish_comparison_error, str(error))
                return
            GLib.idle_add(self._finish_comparison, comparison)

        threading.Thread(target=worker, name="capture-comparer", daemon=True).start()

    def _finish_comparison_error(self, diagnostic: str) -> bool:
        self._stack.set_visible_child_name("dashboard")
        self._show_error("Unable to compare captures", "An image could not be read.", diagnostic)
        return GLib.SOURCE_REMOVE

    def _finish_comparison(self, comparison: CaptureComparison) -> bool:
        body = comparison.summary
        if comparison.changed_tracks:
            tracks = ", ".join(
                f"{cylinder}.{head}" for cylinder, head in comparison.changed_tracks[:40]
            )
            if len(comparison.changed_tracks) > 40:
                tracks += f", … and {len(comparison.changed_tracks) - 40} more"
            body += f"\n\nChanged cylinder.head: {tracks}"
        body += (
            f"\n\nFirst SHA-256: {comparison.first_sha256}"
            f"\nSecond SHA-256: {comparison.second_sha256}"
        )
        label = Gtk.Label(
            label=body,
            xalign=0,
            yalign=0,
            selectable=True,
            wrap=True,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        clamp = Adw.Clamp(maximum_size=760)
        clamp.set_child(label)
        self._show_workspace("Capture Comparison", comparison.summary, clamp)
        return GLib.SOURCE_REMOVE

    def _choose_conversion_format(self, inspection: ImageInspection) -> None:
        dialog = Adw.MessageDialog.new(
            self,
            "Choose destination format",
            (
                "The source image is never modified. Converting raw flux to a sector "
                "image can discard protection, weak bits, and timing information."
                if inspection.path.suffix.lower() in {".scp", ".a2r"}
                else "The source image is never modified. Choose a compatible destination format."
            ),
        )
        selected: list[str | None] = [None]
        dialog.set_extra_child(
            self._build_format_selector(
                dialog,
                selected,
                response_id="continue",
                excluded_formats=NON_CREATABLE_FORMATS,
            )
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("continue", "Choose location")
        dialog.set_response_enabled("continue", False)
        dialog.set_response_appearance("continue", Adw.ResponseAppearance.SUGGESTED)

        def respond(_dialog: Adw.MessageDialog, response: str) -> None:
            if response != "continue" or selected[0] is None:
                return
            target = next(
                item for item in supported_formats()
                if item.gw_format == selected[0]
            )
            self._choose_conversion_location(inspection.path, target)

        dialog.connect("response", respond)
        dialog.present()

    def _choose_conversion_location(
        self, source: Path, target_format: DiskFormat
    ) -> None:
        chooser = Gtk.FileChooserNative.new(
            "Save converted image",
            self,
            Gtk.FileChooserAction.SAVE,
            "Convert",
            "Cancel",
        )
        chooser.set_current_name(f"{source.stem}{target_format.suffix}")
        chooser.connect("response", self._on_conversion_location, source, target_format)
        self._file_chooser = chooser
        chooser.show()

    def _on_conversion_location(
        self,
        chooser: Gtk.FileChooserNative,
        response: int,
        source: Path,
        target_format: DiskFormat,
    ) -> None:
        self._file_chooser = None
        if response != Gtk.ResponseType.ACCEPT:
            return
        selected = chooser.get_file()
        selected_path = selected.get_path() if selected is not None else None
        if selected_path is None:
            self._show_error("Choose a local folder", "Conversion requires a local path.")
            return
        destination = Path(selected_path)
        if destination.suffix.lower() != target_format.suffix:
            destination = destination.with_suffix(target_format.suffix)
        self._start_conversion(source, destination, target_format)

    def _start_conversion(
        self, source: Path, destination: Path, target_format: DiskFormat
    ) -> None:
        self._reading_page.set_title(f"Converting to {target_format.label}…")
        self._reading_page.set_description(f"Saving {destination.name}; the source is unchanged.")
        self._read_progress.set_fraction(0)
        self._read_progress.set_text("0%")
        self._progress_track.set_text(f"Preparing {target_format.track_count} track sides…")
        self._progress_sectors.set_text("Converting image")
        self._progress_message.set_text("")
        self._stack.set_visible_child_name("reading")
        controller = self._begin_cancellable_operation()

        def worker() -> None:
            def progress(update: CreateImageProgress) -> None:
                GLib.idle_add(self._update_blank_progress, update)

            try:
                result = convert_image(
                    source,
                    destination,
                    target_format,
                    progress=progress,
                    controller=controller,
                )
            except Exception as error:
                result = ConvertImageResult(
                    False, "Image conversion stopped unexpectedly.",
                    f"{type(error).__name__}: {error}",
                )
            GLib.idle_add(self._finish_conversion, result, destination)

        threading.Thread(target=worker, name="image-converter", daemon=True).start()

    def _finish_conversion(
        self, result: ConvertImageResult, destination: Path
    ) -> bool:
        self._end_cancellable_operation()
        if not result.succeeded:
            self._show_dashboard()
            self._show_error("Unable to convert image", result.summary, result.diagnostic)
            return GLib.SOURCE_REMOVE
        self._show_result(
            "Conversion Complete",
            destination.name,
            f"The converted image was saved as {destination}.",
        )
        return GLib.SOURCE_REMOVE

    def _choose_existing_image(self, _button: Gtk.Button | None) -> None:
        chooser = Gtk.FileChooserNative.new(
            "Open disk image",
            self,
            Gtk.FileChooserAction.OPEN,
            "Open image",
            "Cancel",
        )
        image_filter = Gtk.FileFilter()
        image_filter.set_name("Browseable disk images")
        image_filter.add_pattern("*.adf")
        image_filter.add_pattern("*.st")
        image_filter.add_pattern("*.ssd")
        image_filter.add_pattern("*.dsd")
        image_filter.add_pattern("*.d64")
        chooser.add_filter(image_filter)
        all_files = Gtk.FileFilter()
        all_files.set_name("All files")
        all_files.add_pattern("*")
        chooser.add_filter(all_files)
        chooser.connect("response", self._on_existing_image_selected)
        self._file_chooser = chooser
        chooser.show()

    def _on_existing_image_selected(
        self, chooser: Gtk.FileChooserNative, response: int
    ) -> None:
        self._file_chooser = None
        if response != Gtk.ResponseType.ACCEPT:
            return
        selected = chooser.get_file()
        selected_path = selected.get_path() if selected is not None else None
        if selected_path is None:
            self._show_error(
                "Choose a local image",
                "The image browser needs a file on the local filesystem.",
            )
            return
        image_path = Path(selected_path)
        self._reading_page.set_title("Opening disk image…")
        self._reading_page.set_description(
            "Reading the directory without extracting file contents."
        )
        self._read_progress.set_fraction(0)
        self._read_progress.set_text("")
        self._progress_track.set_text(image_path.name)
        self._progress_sectors.set_text("Examining image and filesystem…")
        self._progress_message.set_text("")
        self._stack.set_visible_child_name("reading")
        temporary = tempfile.TemporaryDirectory(prefix="greaseweazle-open-image-")

        def worker() -> None:
            guess = detect_image_format(image_path)
            try:
                contents = open_image(image_path)
            except (FilesystemError, OSError) as error:
                GLib.idle_add(
                    self._finish_existing_image_error,
                    image_path,
                    temporary,
                    str(error),
                    guess.explanation,
                )
                return
            if guess.disk_format is not None:
                contents = DiskContents(
                    contents.volume_label,
                    contents.entries,
                    guess.disk_format.label,
                )
            result = ReadResult(True, "Image opened successfully.")
            disk_format = guess.disk_format or DISK_FORMATS[0]
            GLib.idle_add(
                self._finish_read,
                result,
                temporary,
                (
                    contents,
                    Path(temporary.name) / "files",
                    image_path,
                    disk_format,
                    (),
                ),
            )

        threading.Thread(
            target=worker, name="existing-image-opener", daemon=True
        ).start()

    def _finish_existing_image_error(
        self,
        image_path: Path,
        temporary: tempfile.TemporaryDirectory[str],
        filesystem_error: str,
        detection: str,
    ) -> bool:
        temporary.cleanup()
        self._stack.set_visible_child_name("dashboard")
        self._show_error(
            "Unable to browse disk image",
            f"{image_path.name} could not be opened as a supported filesystem.",
            f"{filesystem_error}\n\nFormat detection: {detection}",
        )
        return GLib.SOURCE_REMOVE

    def _ask_read_format(
        self, button: Gtk.Button | None, *, save_image: bool
    ) -> None:
        dialog = Adw.MessageDialog.new(
            self,
            "Do you know the disk format?",
            (
                "If you know the exact disk type, choose it to begin reading "
                "immediately. Otherwise Greaseweazle can detect it automatically."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("choose", "Choose format")
        dialog.add_response("detect", "Detect automatically")
        dialog.set_response_appearance("detect", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("detect")
        dialog.set_close_response("cancel")
        profile_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=8
        )
        profile_box.append(Gtk.Label(label="Capture profile", xalign=0))
        profile_names = Gtk.StringList.new(
            [profile.name for profile in CAPTURE_PROFILES]
        )
        profile_choice = Gtk.DropDown(model=profile_names, selected=0)
        profile_box.append(profile_choice)
        profile_description = Gtk.Label(
            label=CAPTURE_PROFILES[0].description,
            xalign=0,
            wrap=True,
            css_classes=["dim-label"],
        )
        profile_box.append(profile_description)
        capture_report = Gtk.CheckButton(
            label="Save capture report (JSON) beside the image",
            active=self._save_capture_report,
            sensitive=save_image,
        )
        profile_box.append(capture_report)

        def profile_changed(_choice: Gtk.DropDown, _property: object) -> None:
            profile_description.set_text(
                CAPTURE_PROFILES[profile_choice.get_selected()].description
            )

        profile_choice.connect("notify::selected", profile_changed)
        dialog.set_extra_child(profile_box)

        def respond(_dialog: Adw.MessageDialog, response: str) -> None:
            self._capture_profile = CAPTURE_PROFILES[
                profile_choice.get_selected()
            ]
            self._save_capture_report = capture_report.get_active()
            if response == "choose":
                self._choose_disk_format(button, save_image=save_image)
            elif response == "detect":
                if self._capture_profile.preserve_raw:
                    if save_image:
                        self._choose_image_location(PRESERVATION_FORMAT)
                    else:
                        self._show_error(
                            "Raw capture cannot be browsed directly",
                            "Use “Extract disk to image” with the Protected software profile.",
                        )
                else:
                    self._start_auto_read(button, save_image=save_image)

        dialog.connect("response", respond)
        dialog.present()

    def _choose_write_image(self, _button: Gtk.Button | None) -> None:
        chooser = Gtk.FileChooserNative.new(
            "Choose disk image",
            self,
            Gtk.FileChooserAction.OPEN,
            "Open image",
            "Cancel",
        )
        image_filter = Gtk.FileFilter()
        image_filter.set_name("Floppy disk images")
        for pattern in (
            "*.adf", "*.st", "*.scp", "*.a2r", "*.img", "*.ima",
            "*.ssd", "*.dsd", "*.adm", "*.ads", "*.adl", "*.do",
            "*.po", "*.d64", "*.d71", "*.d81", "*.d1m", "*.d2m",
            "*.d4m", "*.sf7",
        ):
            image_filter.add_pattern(pattern)
        chooser.add_filter(image_filter)
        all_files = Gtk.FileFilter()
        all_files.set_name("All files")
        all_files.add_pattern("*")
        chooser.add_filter(all_files)
        chooser.connect("response", self._on_write_image_selected)
        self._file_chooser = chooser
        chooser.show()

    def _choose_blank_format(self, _button: Gtk.Button | None) -> None:
        dialog = Adw.MessageDialog.new(
            self,
            "Create blank disk image",
            (
                "Choose any format supported by the installed Greaseweazle. "
                "The image will contain blank formatted sectors or bitcells, but "
                "no filesystem; initialise it on the target computer before use."
            ),
        )
        selected: list[str | None] = [None]
        options = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        initialise = Gtk.CheckButton(label="Create a ready-to-use filesystem")
        initialise.set_active(True)
        initialise.set_sensitive(False)
        filesystem_note = Gtk.Label(
            label="Choose a format to see whether filesystem creation is available.",
            xalign=0,
            wrap=True,
            css_classes=["dim-label"],
        )
        volume_label = Gtk.Entry(
            placeholder_text="Volume label",
            text="BLANK",
            sensitive=False,
        )

        def format_selected(format_name: str) -> None:
            disk_format = next(
                item for item in supported_formats()
                if item.gw_format == format_name
            )
            filesystem = filesystem_support_name(disk_format)
            initialise.set_sensitive(filesystem is not None)
            initialise.set_active(filesystem is not None)
            volume_label.set_sensitive(filesystem is not None)
            filesystem_note.set_text(
                f"Creates {filesystem}; files can be added immediately."
                if filesystem
                else "Media layout only; initialise this format on its target system."
            )

        options.append(
            self._build_format_selector(
                dialog,
                selected,
                response_id="choose",
                excluded_formats=NON_CREATABLE_FORMATS,
                on_selected=format_selected,
            )
        )
        options.append(initialise)
        options.append(volume_label)
        options.append(filesystem_note)
        dialog.set_extra_child(options)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("choose", "Choose location")
        dialog.set_response_enabled("choose", False)
        dialog.set_response_appearance("choose", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("choose")
        dialog.set_close_response("cancel")

        def respond(_dialog: Adw.MessageDialog, response: str) -> None:
            if response != "choose" or selected[0] is None:
                return
            disk_format = next(
                (
                    item
                    for item in supported_formats()
                    if item.gw_format == selected[0]
                ),
                None,
            )
            if disk_format is not None:
                self._choose_blank_location(
                    disk_format,
                    initialise.get_active(),
                    volume_label.get_text(),
                )

        dialog.connect("response", respond)
        dialog.present()

    def _choose_blank_location(
        self, disk_format: DiskFormat, initialise: bool, volume_label: str
    ) -> None:
        chooser = Gtk.FileChooserNative.new(
            "Save blank disk image",
            self,
            Gtk.FileChooserAction.SAVE,
            "Create image",
            "Cancel",
        )
        chooser.set_current_name(f"blank{disk_format.suffix}")
        image_filter = Gtk.FileFilter()
        image_filter.set_name(
            f"{disk_format.label} image (*{disk_format.suffix})"
        )
        image_filter.add_pattern(f"*{disk_format.suffix}")
        chooser.add_filter(image_filter)
        chooser.connect(
            "response",
            self._on_blank_location,
            disk_format,
            initialise,
            volume_label,
        )
        self._file_chooser = chooser
        chooser.show()

    def _on_blank_location(
        self,
        chooser: Gtk.FileChooserNative,
        response: int,
        disk_format: DiskFormat,
        initialise: bool,
        volume_label: str,
    ) -> None:
        self._file_chooser = None
        if response != Gtk.ResponseType.ACCEPT:
            return
        selected = chooser.get_file()
        selected_path = selected.get_path() if selected is not None else None
        if selected_path is None:
            self._show_error(
                "Choose a local folder",
                "Blank images must be created on the local filesystem.",
            )
            return
        destination = Path(selected_path)
        if destination.suffix.lower() != disk_format.suffix:
            destination = destination.with_suffix(disk_format.suffix)
        self._start_blank_creation(
            destination, disk_format, initialise, volume_label
        )

    def _start_blank_creation(
        self,
        destination: Path,
        disk_format: DiskFormat,
        initialise: bool,
        volume_label: str,
    ) -> None:
        self._reading_page.set_title(f"Creating {disk_format.label}…")
        self._reading_page.set_description(
            f"Building blank media as {destination.name}."
        )
        self._read_progress.set_fraction(0)
        self._read_progress.set_text("0%")
        self._progress_track.set_text(
            f"Preparing {disk_format.track_count} track sides…"
        )
        self._progress_sectors.set_text(
            f"{disk_format.cylinders} cylinders • {disk_format.heads} "
            f"{'head' if disk_format.heads == 1 else 'heads'}"
        )
        self._progress_message.set_text("Starting Greaseweazle…")
        self._stack.set_visible_child_name("reading")
        controller = self._begin_cancellable_operation()

        def worker() -> None:
            def report(update: CreateImageProgress) -> None:
                GLib.idle_add(self._update_blank_progress, update)

            try:
                result = create_blank_image(
                    destination,
                    disk_format,
                    progress=report,
                    controller=controller,
                    initialise=initialise,
                    volume_label=volume_label,
                )
            except Exception as error:
                result = CreateImageResult(
                    False,
                    "Creating the image stopped because of an unexpected error.",
                    f"{type(error).__name__}: {error}",
                )
            GLib.idle_add(
                self._finish_blank_creation, result, destination, disk_format
            )

        threading.Thread(
            target=worker, name="blank-image-creator", daemon=True
        ).start()

    def _update_blank_progress(self, update: CreateImageProgress) -> bool:
        self._read_progress.set_fraction(update.fraction)
        self._read_progress.set_text(f"{update.fraction * 100:.1f}%")
        self._progress_track.set_text(
            f"Track {update.track_number} of {update.track_count}  •  "
            f"Cylinder {update.cylinder}  •  Head {update.head}"
        )
        self._progress_sectors.set_text("Creating blank track layout")
        self._progress_message.set_text(update.message)
        return GLib.SOURCE_REMOVE

    def _finish_blank_creation(
        self,
        result: CreateImageResult,
        destination: Path,
        disk_format: DiskFormat,
    ) -> bool:
        self._end_cancellable_operation()
        if not result.succeeded:
            self._show_dashboard()
            self._show_error(
                "Unable to create blank image", result.summary, result.diagnostic
            )
            return GLib.SOURCE_REMOVE
        body = f"Created {destination} as {disk_format.label}.\n\n" + (
            f"It contains a ready-to-use {result.filesystem} filesystem."
            if result.filesystem
            else "This is blank media without a filesystem. Initialise or format "
            "it on the target system before adding files."
        )
        self._show_result("Image Created", disk_format.label, body)
        return GLib.SOURCE_REMOVE

    def _on_write_image_selected(
        self, chooser: Gtk.FileChooserNative, response: int
    ) -> None:
        self._file_chooser = None
        if response != Gtk.ResponseType.ACCEPT:
            return
        selected = chooser.get_file()
        selected_path = selected.get_path() if selected is not None else None
        if selected_path is None:
            self._show_error(
                "Choose a local image",
                "Greaseweazle needs a disk image on the local filesystem.",
            )
            return
        image_path = Path(selected_path)
        self._reading_page.set_title("Examining disk image…")
        self._reading_page.set_description(
            "Checking the image contents before choosing a write format."
        )
        self._read_progress.set_fraction(0)
        self._read_progress.set_text("")
        self._progress_track.set_text(image_path.name)
        self._progress_sectors.set_text("Detecting image type and disk geometry…")
        self._progress_message.set_text("")
        self._stack.set_visible_child_name("reading")

        def worker() -> None:
            guess = detect_image_format(image_path)
            GLib.idle_add(self._confirm_write_format, image_path, guess)

        threading.Thread(target=worker, name="image-format-detection", daemon=True).start()

    def _confirm_write_format(
        self, image_path: Path, guess: ImageFormatGuess
    ) -> bool:
        self._stack.set_visible_child_name("dashboard")
        if guess.method == "error":
            self._show_error("Unable to open image", guess.explanation)
            return GLib.SOURCE_REMOVE

        if guess.disk_format is None:
            finding = (
                "The format could not be determined. Choose the correct format "
                "from the complete Greaseweazle list."
            )
        else:
            finding = f"Suggested format: {guess.disk_format.label}\n{guess.explanation}"
        dialog = Adw.MessageDialog.new(
            self,
            "Confirm disk format",
            (
                f"Image: {image_path.name}\n\n{finding}\n\n"
                "Writing will overwrite the floppy disk currently in the drive. "
                "Confirm the format before continuing."
            ),
        )
        selected_format: list[str | None] = [None]
        dialog.set_extra_child(
            self._build_format_selector(
                dialog,
                selected_format,
                response_id="write",
                include_raw_flux=True,
                initial_format=guess.disk_format,
            )
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("write", "Write disk")
        dialog.set_response_enabled("write", guess.disk_format is not None)
        dialog.set_response_appearance("write", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def respond(_dialog: Adw.MessageDialog, response: str) -> None:
            if response != "write" or selected_format[0] is None:
                return
            format_name = selected_format[0]
            if format_name == "__raw_flux__":
                disk_format = (
                    guess.disk_format
                    if guess.disk_format is not None
                    and not guess.disk_format.gw_format
                    else RAW_FLUX_FORMAT
                )
            else:
                disk_format = next(
                    (
                        item
                        for item in supported_formats()
                        if item.gw_format == format_name
                    ),
                    None,
                )
            if disk_format is not None:
                self._start_write(image_path, disk_format)

        dialog.connect("response", respond)
        dialog.present()
        return GLib.SOURCE_REMOVE

    def _start_write(self, image_path: Path, disk_format: DiskFormat) -> None:
        can_verify = bool(disk_format.gw_format)
        self._reading_page.set_title(f"Writing {disk_format.label}…")
        self._reading_page.set_description(
            "Keep the drive connected and do not remove the disk. "
            + (
                "Each track is verified."
                if can_verify
                else "Raw flux will be written directly; sector verification is unavailable."
            )
        )
        self._read_progress.set_fraction(0)
        self._read_progress.set_text("0%")
        self._progress_track.set_text(
            f"Preparing {disk_format.track_count} track sides…"
        )
        self._progress_sectors.set_text(
            f"{disk_format.cylinders} cylinders • {disk_format.heads} "
            f"{'head' if disk_format.heads == 1 else 'heads'}"
        )
        self._progress_message.set_text("Starting Greaseweazle…")
        self._stack.set_visible_child_name("reading")
        controller = self._begin_cancellable_operation()

        def worker() -> None:
            try:
                def report_progress(update: WriteProgress) -> None:
                    GLib.idle_add(
                        self._update_write_progress, update, can_verify
                    )

                result = write_disk(
                    image_path,
                    disk_format,
                    progress=report_progress,
                    controller=controller,
                    drive=self._drive,
                )
            except Exception as error:
                result = WriteResult(
                    False,
                    "Writing stopped because of an unexpected error.",
                    f"{type(error).__name__}: {error}",
                )
            GLib.idle_add(self._finish_write, result, image_path)

        threading.Thread(target=worker, name="disk-writer", daemon=True).start()

    def _update_write_progress(
        self, update: WriteProgress, can_verify: bool
    ) -> bool:
        self._read_progress.set_fraction(update.fraction)
        self._read_progress.set_text(f"{update.fraction * 100:.1f}%")
        self._progress_track.set_text(
            f"Track {update.track_number} of {update.track_count}  •  "
            f"Cylinder {update.cylinder}  •  Head {update.head}"
        )
        status = "Writing and verifying track" if can_verify else "Writing raw flux"
        if update.retry is not None:
            status += f"  •  Verification retry {update.retry}"
        self._progress_sectors.set_text(status)
        self._progress_message.set_text(update.message)
        return GLib.SOURCE_REMOVE

    def _finish_write(self, result: WriteResult, image_path: Path) -> bool:
        self._end_cancellable_operation()
        health_report = build_write_health(result.progress, result.succeeded)
        if not result.succeeded:
            self._show_dashboard()
            dialog = self._show_error(
                "Unable to write disk", result.summary, result.diagnostic
            )
            if health_report is not None:
                dialog.add_response("health", "View track report")
                dialog.connect(
                    "response",
                    lambda _dialog, response: self._show_health_report(
                        "Write verification", health_report
                    )
                    if response == "health"
                    else None,
                )
            return GLib.SOURCE_REMOVE
        actions: list[Gtk.Widget] = []
        if health_report is not None:
            health = Gtk.Button(label="View Track Report")
            health.connect(
                "clicked",
                lambda _button: self._show_health_report(
                    "Write Verification", health_report
                ),
            )
            actions.append(health)
        self._show_result(
            "Write Complete", image_path.name, result.summary, tuple(actions)
        )
        return GLib.SOURCE_REMOVE

    def _start_auto_read(
        self, _button: Gtk.Button | None, *, save_image: bool
    ) -> None:
        self._start_detected_read(_button, save_image=save_image)

    def _start_detected_read(
        self,
        _button: Gtk.Button | None,
        *,
        save_image: bool,
        candidates: tuple[DiskFormat, ...] = DISK_FORMATS,
    ) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="greaseweazle-auto-")
        probe_image = Path(temporary.name) / "probe.scp"
        self._reading_page.set_title("Checking disk format…")
        self._reading_page.set_description(
            "Reading cylinder zero to identify the disk without a full capture."
        )
        self._read_progress.set_fraction(0)
        self._read_progress.set_text("0%")
        self._progress_track.set_text("Preparing cylinder 0, both sides…")
        self._progress_sectors.set_text("Quick format probe • 2 track sides")
        self._progress_message.set_text("Starting Greaseweazle…")
        self._stack.set_visible_child_name("reading")
        controller = self._begin_cancellable_operation()

        def worker() -> None:
            try:
                def report_read(update: ReadProgress) -> None:
                    GLib.idle_add(self._update_read_progress, update)

                read_result = read_disk(
                    PROBE_FORMAT,
                    probe_image,
                    progress=report_read,
                    tracks="c=0:h=0-1",
                    **self._capture_profile.read_options,
                    controller=controller,
                    drive=self._drive,
                )
                if not read_result.succeeded:
                    GLib.idle_add(self._finish_read, read_result, temporary, None)
                    return
                GLib.idle_add(self._show_detecting_probe)
                probe = probe_format(
                    probe_image,
                    Path(temporary.name),
                    candidates=candidates,
                    controller=controller,
                )
                if probe.disk_format is not None:
                    disk_format = probe.disk_format
                    GLib.idle_add(self._show_identified_read, disk_format)
                    image_path = Path(temporary.name) / f"disk{disk_format.suffix}"
                    read_result = read_disk(
                        disk_format,
                        image_path,
                        progress=report_read,
                        **self._capture_profile.read_options,
                        controller=controller,
                        drive=self._drive,
                    )
                    if not read_result.succeeded:
                        GLib.idle_add(self._finish_read, read_result, temporary, None)
                        return
                    try:
                        contents = open_image(image_path)
                    except (FilesystemError, OSError) as error:
                        # A valid-looking boot sector followed by an invalid
                        # filesystem is common on protected commercial disks.
                        # Preserve the physical layout rather than declaring
                        # the media bad or saving a lossy flat sector image.
                        raw_image = Path(temporary.name) / "protected-disk.scp"
                        GLib.idle_add(
                            self._show_preserving_nonstandard,
                            disk_format,
                            str(error),
                        )
                        raw_result = read_disk(
                            PRESERVATION_FORMAT,
                            raw_image,
                            progress=report_read,
                            tracks="c=0-82:h=0-1",
                            **self._capture_profile.read_options,
                            controller=controller,
                            drive=self._drive,
                        )
                        if not raw_result.succeeded:
                            failed = ReadResult(
                                False,
                                "The disk appears protected or nonstandard, but its raw capture failed.",
                                raw_result.diagnostic,
                            )
                            GLib.idle_add(
                                self._finish_read, failed, temporary, None
                            )
                            return
                        detection = DetectionResult(
                            None,
                            raw_image,
                            None,
                            probe.confidence,
                            (
                                f"Initially identified as {disk_format.label}, but "
                                f"filesystem validation failed: {error}"
                            ),
                            "protected",
                        )
                        GLib.idle_add(
                            self._finish_auto_detection,
                            detection,
                            temporary,
                            save_image,
                        )
                        return
                    contents = DiskContents(
                        contents.volume_label, contents.entries, disk_format.label
                    )
                    detection = DetectionResult(
                        disk_format,
                        image_path,
                        contents,
                        probe.confidence,
                        probe.diagnostic,
                    )
                    GLib.idle_add(
                        self._finish_auto_detection, detection, temporary, save_image
                    )
                    return

                # A damaged, unusual or protected disk gets the slower but
                # lossless path. The full capture can also be retained as SCP.
                raw_image = Path(temporary.name) / "disk.scp"
                GLib.idle_add(self._show_full_capture)
                read_result = read_disk(
                    AUTO_DETECT_FORMAT,
                    raw_image,
                    progress=report_read,
                    **self._capture_profile.read_options,
                    controller=controller,
                    drive=self._drive,
                )
                if not read_result.succeeded:
                    GLib.idle_add(self._finish_read, read_result, temporary, None)
                    return
                GLib.idle_add(self._show_detecting_format)

                def report_detection(update: DetectionProgress) -> None:
                    GLib.idle_add(self._update_detection_progress, update)

                detection = detect_format(
                    raw_image,
                    Path(temporary.name),
                    progress=report_detection,
                    candidates=candidates,
                    controller=controller,
                )
                GLib.idle_add(
                    self._finish_auto_detection, detection, temporary, save_image
                )
            except Exception as error:
                failed = ReadResult(
                    False,
                    "Automatic disk identification stopped unexpectedly.",
                    f"{type(error).__name__}: {error}",
                )
                GLib.idle_add(self._finish_read, failed, temporary, None)

        threading.Thread(target=worker, name="disk-auto-detection", daemon=True).start()

    def _show_detecting_probe(self) -> bool:
        self._reading_page.set_title("Identifying disk format…")
        self._reading_page.set_description("Checking the boot sector and track layout.")
        self._read_progress.set_fraction(1)
        self._read_progress.set_text("Probe read")
        self._progress_track.set_text("Testing supported disk formats…")
        self._progress_sectors.set_text("The drive is idle during this check")
        self._progress_message.set_text("")
        return GLib.SOURCE_REMOVE

    def _show_identified_read(self, disk_format: DiskFormat) -> bool:
        self._reading_page.set_title(f"Reading {disk_format.label}…")
        self._reading_page.set_description(
            "Format identified. Keep the drive connected and do not remove the disk."
        )
        self._read_progress.set_fraction(0)
        self._read_progress.set_text("0%")
        self._progress_track.set_text(f"Preparing {disk_format.track_count} tracks…")
        self._progress_sectors.set_text(
            f"{disk_format.cylinders} cylinders • {disk_format.heads} "
            f"{'head' if disk_format.heads == 1 else 'heads'} • "
            f"{disk_format.sectors_per_track} sectors per track"
        )
        self._progress_message.set_text("Starting final read…")
        return GLib.SOURCE_REMOVE

    def _show_full_capture(self) -> bool:
        self._reading_page.set_title("Reading unrecognised disk…")
        self._reading_page.set_description(
            "The quick check was inconclusive; capturing raw flux for safe identification."
        )
        self._read_progress.set_fraction(0)
        self._read_progress.set_text("0%")
        self._progress_track.set_text("Preparing 160 track sides…")
        self._progress_sectors.set_text("80 cylinders • 2 heads • raw flux capture")
        self._progress_message.set_text("Starting Greaseweazle…")
        return GLib.SOURCE_REMOVE

    def _show_preserving_nonstandard(
        self, disk_format: DiskFormat, filesystem_error: str
    ) -> bool:
        self._reading_page.set_title("Preserving protected or nonstandard disk…")
        self._reading_page.set_description(
            (
                f"The disk resembles {disk_format.label}, but its filesystem is not "
                "a normal browseable layout. Capturing raw flux without altering it."
            )
        )
        self._read_progress.set_fraction(0)
        self._read_progress.set_text("0%")
        self._progress_track.set_text("Preparing 166 track sides…")
        self._progress_sectors.set_text(
            "83 cylinders • 2 heads • includes possible protection tracks"
        )
        self._progress_message.set_text(filesystem_error)
        return GLib.SOURCE_REMOVE

    def _show_detecting_format(self) -> bool:
        self._reading_page.set_title("Identifying disk format…")
        self._reading_page.set_description(
            "Testing supported decoders against the captured flux."
        )
        self._read_progress.set_fraction(0)
        self._read_progress.set_text("Starting…")
        self._progress_track.set_text("Examining disk structure…")
        self._progress_sectors.set_text("The physical disk is no longer being read")
        self._progress_message.set_text("")
        return GLib.SOURCE_REMOVE

    def _update_detection_progress(self, update: DetectionProgress) -> bool:
        fraction = update.current / update.total
        self._read_progress.set_fraction(fraction)
        self._read_progress.set_text(f"{update.current} of {update.total}")
        label = update.label if update.label.startswith("Confirming ") else f"Trying {update.label}"
        self._progress_track.set_text(label)
        self._progress_sectors.set_text("Checking decoded sectors and filesystem signature")
        self._progress_message.set_text("")
        return GLib.SOURCE_REMOVE

    def _finish_auto_detection(
        self,
        detection: DetectionResult,
        temporary: tempfile.TemporaryDirectory[str],
        save_image: bool,
    ) -> bool:
        self._end_cancellable_operation()
        if detection.classification == "cancelled":
            temporary.cleanup()
            self._stack.set_visible_child_name("dashboard")
            return GLib.SOURCE_REMOVE
        if detection.disk_format is None or detection.contents is None:
            if save_image:
                self._choose_detected_image_location(detection, temporary)
            else:
                self._offer_unrecognised_capture(detection, temporary)
            return GLib.SOURCE_REMOVE

        if save_image:
            self._choose_detected_image_location(detection, temporary)
            return GLib.SOURCE_REMOVE

        self._finish_read(
            ReadResult(True, "Disk identified."),
            temporary,
            (
                detection.contents,
                Path(temporary.name) / "export-cache",
                detection.image_path,
                detection.disk_format,
                (),
            ),
        )
        return GLib.SOURCE_REMOVE

    def _offer_unrecognised_capture(
        self,
        detection: DetectionResult,
        temporary: tempfile.TemporaryDirectory[str],
    ) -> None:
        self._stack.set_visible_child_name("dashboard")
        if detection.classification == "protected":
            title = "Protected or nonstandard disk"
            body = (
                "The disk geometry was recognised, but its directory is deliberately "
                "nonstandard or damaged. A raw SCP capture was made so protection and "
                "unusual tracks are not lost. It cannot be browsed as a normal disk."
            )
        else:
            title = "Special or unrecognised disk"
            body = (
                "No supported filesystem could be identified reliably. The raw flux "
                "capture can be saved as SCP without losing the unusual disk data."
            )
        dialog = Adw.MessageDialog.new(self, title, body)
        dialog.add_response("close", "Discard capture")
        dialog.add_response("save", "Save raw SCP")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("close")

        def respond(_dialog: Adw.MessageDialog, response: str) -> None:
            if response == "save":
                self._choose_detected_image_location(detection, temporary)
            else:
                temporary.cleanup()

        dialog.connect("response", respond)
        dialog.present()

    def _choose_detected_image_location(
        self,
        detection: DetectionResult,
        temporary: tempfile.TemporaryDirectory[str],
    ) -> None:
        suffix = detection.disk_format.suffix if detection.disk_format else ".scp"
        chooser = Gtk.FileChooserNative.new(
            "Save detected disk image",
            self,
            Gtk.FileChooserAction.SAVE,
            "Save image",
            "Cancel",
        )
        chooser.set_current_name(f"disk{suffix}")
        image_filter = Gtk.FileFilter()
        image_filter.set_name(f"Disk image (*{suffix})")
        image_filter.add_pattern(f"*{suffix}")
        chooser.add_filter(image_filter)
        chooser.connect(
            "response", self._on_detected_image_location, detection, temporary
        )
        self._file_chooser = chooser
        chooser.show()

    def _on_detected_image_location(
        self,
        chooser: Gtk.FileChooserNative,
        response: int,
        detection: DetectionResult,
        temporary: tempfile.TemporaryDirectory[str],
    ) -> None:
        self._file_chooser = None
        if response != Gtk.ResponseType.ACCEPT:
            temporary.cleanup()
            self._stack.set_visible_child_name("dashboard")
            return
        selected = chooser.get_file()
        path = selected.get_path() if selected is not None else None
        if path is None:
            temporary.cleanup()
            self._stack.set_visible_child_name("dashboard")
            self._show_error(
                "Choose a local folder",
                "Greaseweazle images must be saved to a local filesystem path.",
            )
            return
        suffix = detection.disk_format.suffix if detection.disk_format else ".scp"
        destination = Path(path)
        if destination.suffix.lower() != suffix:
            destination = destination.with_suffix(suffix)
        self._progress_track.set_text(f"Saving {destination.name}…")
        self._stack.set_visible_child_name("reading")

        def save_worker() -> None:
            try:
                shutil.copy2(detection.image_path, destination)
            except OSError as error:
                GLib.idle_add(
                    self._finish_image_save_error,
                    temporary,
                    str(error),
                )
                return
            temporary.cleanup()
            GLib.idle_add(self._finish_image_save, destination)

        threading.Thread(target=save_worker, name="image-save", daemon=True).start()

    def _finish_image_save(self, destination: Path) -> bool:
        self._show_result(
            "Capture Saved",
            destination.name,
            f"The disk image was saved as {destination}.",
        )
        return GLib.SOURCE_REMOVE

    def _finish_image_save_error(
        self,
        temporary: tempfile.TemporaryDirectory[str],
        diagnostic: str,
    ) -> bool:
        temporary.cleanup()
        self._stack.set_visible_child_name("dashboard")
        self._show_error(
            "Unable to save disk image",
            "The disk was read, but the image could not be saved.",
            diagnostic,
        )
        return GLib.SOURCE_REMOVE

    def _choose_disk_format(
        self, _button: Gtk.Button | None, *, save_image: bool
    ) -> None:
        dialog = Adw.MessageDialog.new(
            self,
            "Choose the source disk",
            "Formats are grouped by manufacturer from the installed Greaseweazle.",
        )
        selected: list[str | None] = [None]
        dialog.set_extra_child(
            self._build_format_selector(
                dialog,
                selected,
                response_id="continue",
                include_atari_auto=True,
            )
        )
        dialog.add_response("cancel", "Cancel")
        continue_label = "Choose image location" if save_image else "Read disk"
        dialog.add_response("continue", continue_label)
        dialog.set_response_enabled("continue", False)
        dialog.set_response_appearance("continue", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("continue")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_format_response, selected, save_image)
        dialog.present()

    def _build_format_selector(
        self,
        dialog: Adw.MessageDialog,
        selected: list[str | None],
        *,
        response_id: str,
        include_atari_auto: bool = False,
        include_raw_flux: bool = False,
        initial_format: DiskFormat | None = None,
        excluded_formats: frozenset[str] = frozenset(),
        on_selected: Callable[[str], None] | None = None,
    ) -> Gtk.Widget:
        choice_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=12,
            margin_bottom=6,
        )
        if initial_format is None:
            initial_label = "Choose manufacturer and format…"
        elif not initial_format.gw_format:
            initial_label = "Raw formats — raw flux (no conversion)"
        else:
            initial_label = (
                f"{manufacturer_name(initial_format.gw_format)} — "
                f"{format_menu_label(initial_format.gw_format)}"
            )
        menu_button = Gtk.MenuButton(
            label=initial_label,
            hexpand=True,
            halign=Gtk.Align.FILL,
        )
        menu = Gio.Menu()
        raw_flux_added = False
        available_groups = tuple(
            (
                manufacturer,
                tuple(
                    disk_format
                    for disk_format in formats
                    if disk_format.gw_format not in excluded_formats
                ),
            )
            for manufacturer, formats in grouped_formats()
        )
        available_groups = tuple(
            (manufacturer, formats)
            for manufacturer, formats in available_groups
            if formats
        )
        for manufacturer, formats in available_groups:
            submenu = Gio.Menu()
            if include_raw_flux and manufacturer == "Raw formats":
                raw_section = Gio.Menu()
                item = Gio.MenuItem.new("Raw flux image — no conversion", None)
                item.set_action_and_target_value(
                    "format.select", GLib.Variant("s", "__raw_flux__")
                )
                raw_section.append_item(item)
                submenu.append_section(None, raw_section)
                raw_flux_added = True
            if include_atari_auto and manufacturer == "Atari":
                automatic = Gio.Menu()
                item = Gio.MenuItem.new("ST — detect subtype automatically", None)
                item.set_action_and_target_value(
                    "format.select", GLib.Variant("s", "__atari_auto__")
                )
                automatic.append_item(item)
                submenu.append_section(None, automatic)
            format_section = Gio.Menu()
            for disk_format in formats:
                item = Gio.MenuItem.new(
                    format_menu_label(disk_format.gw_format), None
                )
                item.set_action_and_target_value(
                    "format.select", GLib.Variant("s", disk_format.gw_format)
                )
                format_section.append_item(item)
            submenu.append_section(None, format_section)
            menu.append_submenu(manufacturer, submenu)
        if include_raw_flux and not raw_flux_added:
            raw_submenu = Gio.Menu()
            item = Gio.MenuItem.new("Raw flux image — no conversion", None)
            item.set_action_and_target_value(
                "format.select", GLib.Variant("s", "__raw_flux__")
            )
            raw_submenu.append_item(item)
            menu.append_submenu("Raw formats", raw_submenu)

        action_group = Gio.SimpleActionGroup()
        select_action = Gio.SimpleAction.new(
            "select", GLib.VariantType.new("s")
        )

        def select_format(_action: Gio.SimpleAction, parameter: GLib.Variant) -> None:
            format_name = parameter.get_string()
            selected[0] = format_name
            if format_name == "__atari_auto__":
                label = "Atari ST — detect subtype automatically"
            elif format_name == "__raw_flux__":
                label = "Raw formats — raw flux (no conversion)"
            else:
                disk_format = next(
                    item for item in supported_formats() if item.gw_format == format_name
                )
                label = (
                    f"{manufacturer_name(disk_format.gw_format)} — "
                    f"{format_menu_label(format_name)}"
                )
            menu_button.set_label(label)
            dialog.set_response_enabled(response_id, True)
            if on_selected is not None:
                on_selected(format_name)

        select_action.connect("activate", select_format)
        action_group.add_action(select_action)
        menu_button.insert_action_group("format", action_group)
        menu_button.set_menu_model(menu)
        choice_box.append(menu_button)
        choice_box.append(
            Gtk.Label(
                label=(
                    f"{sum(len(items) for _name, items in available_groups)} "
                    "available formats"
                ),
                xalign=0,
                css_classes=["dim-label"],
            )
        )
        if initial_format is not None:
            selected[0] = (
                initial_format.gw_format
                if initial_format.gw_format
                else "__raw_flux__"
            )
        return choice_box

    def _on_format_response(
        self,
        _dialog: Adw.MessageDialog,
        response: str,
        selected_format: list[str | None],
        save_image: bool,
    ) -> None:
        if response != "continue":
            return
        format_name = selected_format[0]
        if format_name is None:
            return
        if self._capture_profile.preserve_raw:
            if not save_image:
                self._show_error(
                    "Raw capture cannot be browsed directly",
                    "Use “Extract disk to image” with the Protected software profile. "
                    "The resulting SCP can then be inspected or written back losslessly.",
                )
                return
            self._choose_image_location(PRESERVATION_FORMAT)
            return
        if format_name == "__atari_auto__":
            atari_formats = tuple(
                item
                for item in supported_formats()
                if item.gw_format.startswith("atarist.")
            )
            self._start_detected_read(
                None, save_image=save_image, candidates=atari_formats
            )
            return
        disk_format = next(
            (item for item in supported_formats() if item.gw_format == format_name),
            None,
        )
        if disk_format is None:
            return
        if not save_image and disk_format.suffix not in {".adf", ".st", ".ssd", ".dsd", ".d64"}:
            self._show_error(
                "Directory browsing is not available for this format",
                (
                    f"{disk_format.gw_format} can be read with “Extract disk to image”, "
                    "but its filesystem browser has not been implemented yet."
                ),
            )
            return
        if not save_image:
            temporary = tempfile.TemporaryDirectory(prefix="greaseweazle-gui-")
            destination = Path(temporary.name) / f"disk{disk_format.suffix}"
            self._start_read(disk_format, destination, temporary)
            return
        self._choose_image_location(disk_format)

    def _choose_image_location(self, disk_format: DiskFormat) -> None:
        chooser = Gtk.FileChooserNative.new(
            "Save disk image",
            self,
            Gtk.FileChooserAction.SAVE,
            "Read disk",
            "Cancel",
        )
        chooser.set_current_name(f"disk{disk_format.suffix}")
        image_filter = Gtk.FileFilter()
        image_filter.set_name(f"{disk_format.label} image (*{disk_format.suffix})")
        image_filter.add_pattern(f"*{disk_format.suffix}")
        chooser.add_filter(image_filter)
        chooser.connect("response", self._on_image_location_response, disk_format)
        self._file_chooser = chooser
        chooser.show()

    def _on_image_location_response(
        self,
        chooser: Gtk.FileChooserNative,
        response: int,
        disk_format: DiskFormat,
    ) -> None:
        self._file_chooser = None
        if response != Gtk.ResponseType.ACCEPT:
            return
        selected = chooser.get_file()
        path = selected.get_path() if selected is not None else None
        if path is None:
            self._show_error(
                "Choose a local folder",
                "Greaseweazle needs a local filesystem path for the disk image.",
            )
            return
        destination = Path(path)
        if destination.suffix.lower() != disk_format.suffix:
            destination = destination.with_suffix(disk_format.suffix)
        self._start_read(disk_format, destination)

    def _start_read(
        self,
        disk_format: DiskFormat,
        destination: Path,
        temporary: tempfile.TemporaryDirectory[str] | None = None,
    ) -> None:
        self._reading_page.set_title(f"Reading {disk_format.label}…")
        self._reading_page.set_description(
            "Keep the drive connected and do not remove the disk."
            if temporary is not None
            else f"Saving {destination.name}. Keep the drive connected and do not remove the disk."
        )
        self._read_progress.set_fraction(0)
        self._read_progress.set_text("0%")
        self._progress_track.set_text(
            f"Preparing {disk_format.track_count} tracks…"
        )
        self._progress_sectors.set_text(
            f"{disk_format.cylinders} cylinders • {disk_format.heads} "
            f"{'head' if disk_format.heads == 1 else 'heads'} • "
            f"{disk_format.sectors_per_track} sectors per track"
        )
        self._progress_message.set_text("Starting Greaseweazle…")
        self._stack.set_visible_child_name("reading")
        controller = self._begin_cancellable_operation()

        def worker() -> None:
            active_temporary = temporary
            try:
                def report_progress(update: ReadProgress) -> None:
                    GLib.idle_add(self._update_read_progress, update)

                result = read_disk(
                    disk_format,
                    destination,
                    progress=report_progress,
                    controller=controller,
                    drive=self._drive,
                    **self._capture_profile.read_options,
                )
                if not result.succeeded:
                    GLib.idle_add(self._finish_read, result, active_temporary, None)
                    return
                if active_temporary is None:
                    GLib.idle_add(
                        self._finish_image_only_read, destination, disk_format, result
                    )
                    return
                GLib.idle_add(self._show_extracting_files)
                if active_temporary is None:
                    active_temporary = tempfile.TemporaryDirectory(
                        prefix="greaseweazle-gui-"
                    )
                cache_path = Path(active_temporary.name) / "export-cache"
                try:
                    contents = open_image(destination)
                except (FilesystemError, OSError) as error:
                    active_temporary.cleanup()
                    failed = ReadResult(
                        False,
                        "The disk was read, but its directory could not be opened.",
                        str(error),
                    )
                    GLib.idle_add(self._finish_read, failed, None, None)
                    return
                GLib.idle_add(
                    self._finish_read,
                    result,
                    active_temporary,
                    (contents, cache_path, destination, disk_format, result.progress),
                )
            except Exception as error:
                # This worker is the outer boundary for hardware and image
                # processing. Never leave the UI stranded if an unexpected
                # library or subprocess error escapes.
                failed = ReadResult(
                    False,
                    "Reading stopped because of an unexpected error.",
                    f"{type(error).__name__}: {error}",
                )
                GLib.idle_add(self._finish_read, failed, active_temporary, None)

        threading.Thread(target=worker, name="disk-reader", daemon=True).start()

    def _finish_image_only_read(
        self,
        destination: Path,
        disk_format: DiskFormat,
        result: ReadResult,
    ) -> bool:
        self._end_cancellable_operation()
        report_note = ""
        if self._save_capture_report:
            try:
                report_path = write_capture_report(
                    destination,
                    disk_format,
                    result,
                    profile_name=self._capture_profile.name,
                    device_model=self._device_model,
                    device_port=self._device_port,
                )
                report_note = f"\n\nCapture report: {report_path.name}"
            except OSError as error:
                report_note = f"\n\nThe capture report could not be saved: {error}"
        health_report = build_track_health(result.progress)
        body = (
            f"The disk image was saved as {destination}.\n\n"
            f"{health_report.summary}{report_note}"
            if health_report is not None
            else f"The disk image was saved as {destination}.{report_note}"
        )
        actions: list[Gtk.Widget] = []
        if health_report is not None:
            health = Gtk.Button(label="View Track Report")
            health.connect(
                "clicked",
                lambda _button: self._show_health_report(
                    "Read Quality", health_report
                ),
            )
            actions.append(health)
        self._show_result(
            "Capture Complete", destination.name, body, tuple(actions)
        )
        return GLib.SOURCE_REMOVE

    def _update_read_progress(self, update: ReadProgress) -> bool:
        self._read_progress.set_fraction(update.fraction)
        self._read_progress.set_text(f"{update.fraction * 100:.1f}%")
        self._progress_track.set_text(
            f"Track {update.track_number} of {update.track_count}  •  "
            f"Cylinder {update.cylinder}  •  Head {update.head}"
        )
        if update.sectors_read is not None and update.sectors_total is not None:
            sector_text = f"Sectors recovered: {update.sectors_read} of {update.sectors_total}"
        else:
            sector_text = "Reading flux data"
        if update.retry is not None:
            sector_text += f"  •  Retry {update.retry}"
        self._progress_sectors.set_text(sector_text)
        self._progress_message.set_text(update.message)
        return GLib.SOURCE_REMOVE

    def _show_extracting_files(self) -> bool:
        self._read_progress.set_fraction(1)
        self._read_progress.set_text("100%")
        self._progress_track.set_text("All tracks read")
        self._progress_sectors.set_text("Reading the disk directory…")
        self._progress_message.set_text("")
        return GLib.SOURCE_REMOVE

    def _finish_read(
        self,
        result: ReadResult,
        temporary: tempfile.TemporaryDirectory[str] | None,
        browser_details: tuple[
            DiskContents, Path, Path, DiskFormat, tuple[ReadProgress, ...]
        ] | None,
    ) -> bool:
        self._end_cancellable_operation()
        if not result.succeeded:
            if temporary is not None:
                temporary.cleanup()
            self._stack.set_visible_child_name("dashboard")
            self._show_error("Unable to read disk", result.summary, result.diagnostic)
            return GLib.SOURCE_REMOVE

        if temporary is None or browser_details is None:
            if temporary is not None:
                temporary.cleanup()
            self._stack.set_visible_child_name("dashboard")
            self._show_error(
                "Unable to browse disk",
                "The disk was read, but its directory could not be opened.",
                result.diagnostic,
            )
            return GLib.SOURCE_REMOVE

        existing = self._stack.get_child_by_name("browser")
        if existing is not None:
            self._stack.remove(existing)
        contents, cache_path, image_path, disk_format, read_progress = browser_details
        health_report = build_track_health(result.progress)
        try:
            browser = DiskBrowser(
                contents,
                cache_path,
                on_done=self._leave_browser,
                health_report=health_report,
                on_retry_damaged=(
                    lambda: self._start_track_retry(
                        image_path,
                        disk_format,
                        temporary,
                        read_progress,
                    )
                    if health_report is not None and health_report.damaged_count
                    else None
                ),
            )
        except Exception as error:
            temporary.cleanup()
            self._stack.set_visible_child_name("dashboard")
            self._show_error(
                "Unable to open disk browser",
                "The disk was read, but the file view could not be opened.",
                f"{type(error).__name__}: {error}",
            )
            return GLib.SOURCE_REMOVE
        if temporary not in self._temporary_directories:
            self._temporary_directories.append(temporary)
        self.set_default_size(1180, 720)
        self._browser_subtitle = (
            f"{contents.volume_label} • {contents.format_label}"
            if contents.format_label
            else contents.volume_label
        )
        self._stack.add_named(browser, "browser")
        self._stack.set_visible_child_name("browser")
        return GLib.SOURCE_REMOVE

    def _start_track_retry(
        self,
        image_path: Path,
        disk_format: DiskFormat,
        temporary: tempfile.TemporaryDirectory[str],
        previous_progress: tuple[ReadProgress, ...],
    ) -> None:
        report = build_track_health(previous_progress)
        if report is None or not report.damaged_count:
            return
        self._reading_page.set_title("Retrying damaged tracks…")
        self._reading_page.set_description(
            "Only damaged track sides will be re-read; the image is replaced atomically."
        )
        self._read_progress.set_fraction(0)
        self._read_progress.set_text("0%")
        self._progress_track.set_text(
            f"Preparing {report.damaged_count} damaged track side(s)…"
        )
        self._progress_sectors.set_text("Difficult-media recovery settings")
        self._progress_message.set_text("Starting Greaseweazle…")
        self._stack.set_visible_child_name("reading")
        controller = self._begin_cancellable_operation()

        def worker() -> None:
            def progress(update: ReadProgress) -> None:
                GLib.idle_add(self._update_read_progress, update)

            try:
                retried = retry_damaged_tracks(
                    image_path,
                    disk_format,
                    report,
                    progress=progress,
                    controller=controller,
                    drive=self._drive,
                )
            except Exception as error:
                retried = RetryTracksResult(
                    False,
                    "Retrying damaged tracks stopped unexpectedly.",
                    f"{type(error).__name__}: {error}",
                )
            GLib.idle_add(
                self._finish_track_retry,
                retried,
                image_path,
                disk_format,
                temporary,
                previous_progress,
            )

        threading.Thread(target=worker, name="track-retry", daemon=True).start()

    def _finish_track_retry(
        self,
        retried: RetryTracksResult,
        image_path: Path,
        disk_format: DiskFormat,
        temporary: tempfile.TemporaryDirectory[str],
        previous_progress: tuple[ReadProgress, ...],
    ) -> bool:
        self._end_cancellable_operation()
        if not retried.succeeded:
            self._stack.set_visible_child_name("dashboard")
            self._show_error(
                "Unable to retry damaged tracks", retried.summary, retried.diagnostic
            )
            return GLib.SOURCE_REMOVE
        try:
            contents = open_image(image_path)
        except (FilesystemError, OSError) as error:
            self._stack.set_visible_child_name("dashboard")
            self._show_error(
                "Unable to reopen recovered image",
                "The retry completed, but the filesystem still could not be opened.",
                str(error),
            )
            return GLib.SOURCE_REMOVE
        combined = previous_progress + retried.progress
        result = ReadResult(True, retried.summary, retried.diagnostic, combined)
        return self._finish_read(
            result,
            temporary,
            (
                contents,
                Path(temporary.name) / "export-cache",
                image_path,
                disk_format,
                combined,
            ),
        )

    def _leave_browser(self) -> None:
        self._show_dashboard()

    def _show_health_report(
        self, title: str, report: TrackHealthReport
    ) -> None:
        grid = Gtk.Grid(column_spacing=14, row_spacing=4, margin_top=8)
        grid.attach(Gtk.Label(label="Cylinder", css_classes=["heading"]), 0, 0, 1, 1)
        heads = sorted({track.head for track in report.tracks})
        for column, head in enumerate(heads, start=1):
            grid.attach(Gtk.Label(label=f"Head {head}", css_classes=["heading"]), column, 0, 1, 1)
        lookup = {(track.cylinder, track.head): track for track in report.tracks}
        for row, cylinder in enumerate(
            sorted({track.cylinder for track in report.tracks}), start=1
        ):
            grid.attach(Gtk.Label(label=str(cylinder), xalign=1), 0, row, 1, 1)
            for column, head in enumerate(heads, start=1):
                track = lookup.get((cylinder, head))
                if track is None:
                    marker = Gtk.Label(label="—", css_classes=["dim-label"])
                else:
                    css = {
                        TrackCondition.GOOD: "success",
                        TrackCondition.RECOVERED: "warning",
                        TrackCondition.DAMAGED: "error",
                    }[track.condition]
                    marker = Gtk.Label(label="●", css_classes=[css])
                    marker.set_tooltip_text(track.message)
                grid.attach(marker, column, row, 1, 1)
        scroller = Gtk.ScrolledWindow(min_content_height=320, max_content_height=420)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(grid)
        self._show_workspace(title, report.summary, scroller)

    def _show_error(
        self, title: str, summary: str, diagnostic: str = ""
    ) -> Adw.MessageDialog:
        body = summary
        if diagnostic:
            cleaned = diagnostic.strip()
            self._diagnostic_log.append(
                f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
                f"{title}\n{summary}\n{cleaned}"
            )
        dialog = Adw.MessageDialog.new(self, title, body)
        dialog.add_response("close", "Close")
        if diagnostic:
            view = Gtk.TextView(
                editable=False,
                cursor_visible=False,
                monospace=True,
                wrap_mode=Gtk.WrapMode.WORD_CHAR,
                top_margin=6,
                bottom_margin=6,
                left_margin=6,
                right_margin=6,
            )
            view.get_buffer().set_text(diagnostic.strip())
            scroller = Gtk.ScrolledWindow(
                min_content_height=140, max_content_height=280
            )
            scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scroller.set_child(view)
            dialog.set_extra_child(scroller)
            dialog.add_response("copy", "Copy details")
            dialog.add_response("save", "Save details…")
            dialog.connect(
                "response",
                lambda _dialog, response: self._copy_diagnostic(diagnostic)
                if response == "copy"
                else self._choose_diagnostic_save(diagnostic)
                if response == "save"
                else None,
            )
        dialog.set_default_response("close")
        dialog.set_close_response("close")
        dialog.present()
        return dialog

    def _copy_diagnostic(self, diagnostic: str) -> None:
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(diagnostic)

    def _show_diagnostic_log(self, _button: Gtk.Button | None) -> None:
        text = "\n\n".join(self._diagnostic_log)
        view = Gtk.TextView(
            editable=False,
            cursor_visible=False,
            monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
        )
        view.get_buffer().set_text(
            text or "No operation errors have been recorded this session."
        )
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(view)
        actions: list[Gtk.Widget] = []
        if text:
            copy_button = Gtk.Button(label="Copy")
            copy_button.connect("clicked", lambda _button: self._copy_diagnostic(text))
            save_button = Gtk.Button(label="Save…")
            save_button.connect(
                "clicked", lambda _button: self._choose_diagnostic_save(text)
            )
            clear_button = Gtk.Button(label="Clear")
            clear_button.add_css_class("destructive-action")

            def clear(_button: Gtk.Button) -> None:
                self._diagnostic_log.clear()
                view.get_buffer().set_text(
                    "No operation errors have been recorded this session."
                )
                for button in (copy_button, save_button, clear_button):
                    button.set_sensitive(False)

            clear_button.connect("clicked", clear)
            actions.extend((copy_button, save_button, clear_button))
        self._show_workspace(
            "Diagnostic Log",
            "Local filenames and tool output; disk-file contents are never included",
            scroller,
            tuple(actions),
        )

    def _choose_diagnostic_save(self, diagnostic: str) -> None:
        chooser = Gtk.FileChooserNative.new(
            "Save diagnostic log",
            self,
            Gtk.FileChooserAction.SAVE,
            "Save",
            "Cancel",
        )
        chooser.set_current_name("greaseweazle-diagnostics.txt")
        chooser.connect("response", self._on_diagnostic_save, diagnostic)
        self._file_chooser = chooser
        chooser.show()

    def _on_diagnostic_save(
        self, chooser: Gtk.FileChooserNative, response: int, diagnostic: str
    ) -> None:
        self._file_chooser = None
        if response != Gtk.ResponseType.ACCEPT:
            return
        selected = chooser.get_file()
        selected_path = selected.get_path() if selected is not None else None
        if selected_path is None:
            return
        try:
            Path(selected_path).write_text(diagnostic, encoding="utf-8")
        except OSError as error:
            self._show_error("Unable to save diagnostics", str(error))

    def begin_device_detection(
        self,
        detector: Callable[[], DeviceProbeResult] = detect_device,
        *,
        silent: bool = False,
    ) -> None:
        """Run device detection without blocking GTK's event loop."""
        if self._device_detection_active:
            return
        self._device_detection_active = True
        self._window_actions["retry-device"].set_enabled(False)
        if not silent:
            self._welcome_page.set_description("Checking the USB connection…")

        def worker() -> None:
            result = detector()
            GLib.idle_add(self._finish_device_detection, result, silent)

        threading.Thread(target=worker, name="device-detection", daemon=True).start()

    def _poll_device(self) -> bool:
        if (
            self._initial_detection_complete
            and not self._device_detection_active
            and self._active_operation is None
            and self._stack.get_visible_child_name() == "dashboard"
        ):
            self.begin_device_detection(silent=True)
        return GLib.SOURCE_CONTINUE

    def _finish_device_detection(
        self, result: DeviceProbeResult, silent: bool = False
    ) -> bool:
        was_connected = self._device_connected
        self._device_detection_active = False
        self._initial_detection_complete = True
        self._device_connected = result.connected
        self._host_tools_available = result.host_tools_available
        for name in (
            "read-disk",
            "extract-image",
            "write-disk",
            "rpm",
            "bandwidth",
            "clean",
        ):
            self._window_actions[name].set_enabled(result.connected)
        self._window_actions["create-image"].set_enabled(
            result.host_tools_available
        )
        self._window_actions["retry-device"].set_enabled(not result.connected)
        self._browse_disk_button.set_sensitive(result.connected)
        if result.connected:
            self._device_model = result.model
            self._device_port = result.port
            self._refresh_welcome_status()
            if not silent:
                self._show_dashboard()
            threading.Thread(
                target=supported_formats,
                name="format-catalog-loader",
                daemon=True,
            ).start()
            return GLib.SOURCE_REMOVE

        self._refresh_welcome_status()
        if not silent:
            self._show_dashboard()
        if silent:
            if was_connected and result.diagnostic:
                self._diagnostic_log.append(
                    f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
                    f"Device disconnected\n{result.summary}\n{result.diagnostic}"
                )
            return GLib.SOURCE_REMOVE
        dialog = Adw.MessageDialog.new(
            self,
            "Greaseweazle not available",
            (
                f"{result.summary}\n\n"
                "You can continue to open existing images, or connect the "
                "hardware and choose Drive → Reconnect Device."
            ),
        )
        dialog.add_response("quit", "Quit")
        dialog.add_response("offline", "Use images offline")
        dialog.set_response_appearance(
            "offline", Adw.ResponseAppearance.SUGGESTED
        )
        dialog.set_default_response("offline")
        dialog.set_close_response("offline")
        dialog.connect("response", self._on_detection_dialog_response)
        dialog.present()
        return GLib.SOURCE_REMOVE

    def _on_detection_dialog_response(
        self, _dialog: Adw.MessageDialog, response: str
    ) -> None:
        if response != "quit":
            return
        application = self.get_application()
        if application is not None:
            application.quit()

    def show_documentation_state(self, state: str) -> bool:
        """Render a deterministic real UI state for bundled documentation images."""
        self._stack.set_transition_duration(0)
        if state == "help":
            self._show_help()
        elif state == "main":
            self._host_tools_available = True
            self._device_connected = True
            self._device_model = "Greaseweazle F1"
            self._device_port = "/dev/ttyACM1"
            for name in (
                "read-disk",
                "extract-image",
                "write-disk",
                "rpm",
                "bandwidth",
                "clean",
                "create-image",
            ):
                self._window_actions[name].set_enabled(True)
            self._browse_disk_button.set_sensitive(True)
            self._refresh_welcome_status()
            self._show_dashboard()
        elif state == "read-progress":
            self._reading_page.set_title("Reading Atari ST 800 KB…")
            self._reading_page.set_description(
                "Keep the drive connected and do not remove the disk."
            )
            self._read_progress.set_fraction(0.575)
            self._read_progress.set_text("57.5%")
            self._progress_track.set_text(
                "Track 92 of 160  •  Cylinder 45  •  Head 1"
            )
            self._progress_sectors.set_text(
                "Sectors recovered: 10 of 10  •  Retry 1.1"
            )
            self._progress_message.set_text(
                "IBM MFM (10/10 sectors) from Raw Flux"
            )
            self._stack.set_visible_child_name("reading")
        elif state == "write-progress":
            self._reading_page.set_title("Writing Amiga DD…")
            self._reading_page.set_description(
                "Keep the drive connected and do not remove the disk. Each track is verified."
            )
            self._read_progress.set_fraction(0.725)
            self._read_progress.set_text("72.5%")
            self._progress_track.set_text(
                "Track 116 of 160  •  Cylinder 57  •  Head 1"
            )
            self._progress_sectors.set_text("Writing and verifying track")
            self._progress_message.set_text(
                "AmigaDOS: Writing Track 57.1, verified"
            )
            self._stack.set_visible_child_name("reading")
        elif state == "capture-complete":
            self._show_result(
                "Capture Complete",
                "ninja-rabbits.scp",
                "The raw disk image was saved successfully.\n\nAll 166 track sides were captured.\n\nCapture report: ninja-rabbits.scp.capture.json",
            )
        elif state == "blank-image":
            self._show_result(
                "Image Created",
                "Atari ST 800 KB",
                "Created blank-games.st as Atari ST 800 KB.\n\nIt contains a ready-to-use Atari TOS FAT12 filesystem.",
            )
        elif state == "image-inspector":
            disk_format = DISK_FORMATS[3]
            self._finish_inspection(
                ImageInspection(
                    Path("/home/user/Images/games.st"),
                    819200,
                    "3d704c7d3908c2af97b9be4310486112f61809ce340c82cb99fb92260f5608a1",
                    ImageFormatGuess(
                        disk_format,
                        "content",
                        "FAT boot sector: 80 cylinders, 2 heads, 10 sectors/track",
                    ),
                    "Atari ST FAT12",
                    "GAMES",
                    "Filesystem structures and root directory are readable.",
                )
            )
        elif state == "image-library":
            entries = (
                CatalogueEntry(Path("/images/Workbench.adf"), 901120, "a" * 64, "Amiga DD", "AmigaDOS OFS", "Workbench"),
                CatalogueEntry(Path("/images/Ninja Rabbits.scp"), 28401152, "b" * 64, "Raw flux image", None, None),
                CatalogueEntry(Path("/images/Games.st"), 819200, "c" * 64, "Atari ST 800 KB", "Atari ST FAT12", "GAMES", 2),
                CatalogueEntry(Path("/backup/Games.st"), 819200, "c" * 64, "Atari ST 800 KB", "Atari ST FAT12", "GAMES", 2),
            )
            self._finish_catalogue(Path("/images"), entries)
        elif state == "track-health":
            tracks = []
            for cylinder in range(18):
                for head in range(2):
                    condition = (
                        TrackCondition.DAMAGED
                        if (cylinder, head) == (11, 1)
                        else TrackCondition.RECOVERED
                        if (cylinder, head) in {(4, 0), (9, 1)}
                        else TrackCondition.GOOD
                    )
                    tracks.append(
                        TrackHealth(
                            cylinder,
                            head,
                            condition,
                            8 if condition is TrackCondition.DAMAGED else 10,
                            10,
                            2 if condition is not TrackCondition.GOOD else 1,
                            "Giving up: 8/10 sectors"
                            if condition is TrackCondition.DAMAGED
                            else "10/10 sectors",
                        )
                    )
            self._show_health_report(
                "Disk Health", TrackHealthReport(tuple(tracks))
            )
        elif state == "drive-tools":
            self._finish_hardware_tool(
                HardwareToolResult(
                    True,
                    "Drive speed measurement complete.",
                    "300.18 RPM\n300.21 RPM\n300.16 RPM\n300.19 RPM\n300.20 RPM\nAverage: 300.19 RPM",
                )
            )
        elif state == "diagnostic-log":
            self._diagnostic_log[:] = [
                "[2026-08-24T00:00:00+01:00] Unable to browse disk\nThe disk was read, but its directory could not be opened.\nThe disk contains a looping or invalid FAT chain.",
                "[2026-08-24T00:02:12+01:00] Device disconnected\nNo connected Greaseweazle was found.",
            ]
            self._show_diagnostic_log(None)
        elif state == "disk-browser":
            temporary = tempfile.TemporaryDirectory(prefix="gw-help-browser-")
            self._temporary_directories.append(temporary)
            contents = DiskContents(
                "GAMES",
                (
                    ImageEntry(
                        "AUTO",
                        True,
                        children=(
                            ImageEntry(
                                "START.PRG", False, 48216, _reader=lambda: b""
                            ),
                        ),
                    ),
                    ImageEntry("README.TXT", False, 1842, _reader=lambda: b""),
                    ImageEntry("NINJA.PRG", False, 241664, _reader=lambda: b""),
                    ImageEntry("SCORES.DAT", False, 512, _reader=lambda: b""),
                ),
                "Atari ST FAT12",
            )
            self._finish_read(
                ReadResult(True, "Image opened successfully."),
                temporary,
                (
                    contents,
                    Path(temporary.name) / "files",
                    Path(temporary.name) / "games.st",
                    DISK_FORMATS[3],
                    (),
                ),
            )
            browser = self._stack.get_child_by_name("browser")
            if isinstance(browser, DiskBrowser):
                local_folder = Path(temporary.name) / "Local Files"
                local_folder.mkdir()
                for folder_name in ("Archive", "Disk Images", "Documents"):
                    (local_folder / folder_name).mkdir()
                (local_folder / "capture-notes.txt").write_text(
                    "Capture notes", encoding="utf-8"
                )
                browser._local.current_directory = local_folder
                browser._local.refresh()
                browser._local._path.set_text("~/Files")
        return GLib.SOURCE_REMOVE
