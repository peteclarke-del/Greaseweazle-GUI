"""Main application window."""

from __future__ import annotations

import threading
import tempfile
import shutil
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .browser import DiskBrowser
from .device import DeviceProbeResult, detect_device
from .disk_formats import (
    AUTO_DETECT_FORMAT,
    DISK_FORMATS,
    PRESERVATION_FORMAT,
    PROBE_FORMAT,
    RAW_FLUX_FORMAT,
    DiskFormat,
)
from .filesystems import DiskContents, FilesystemError, open_image
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
from .read_disk import ReadProgress, ReadResult, read_disk
from .write_disk import WriteProgress, WriteResult, write_disk


class MainWindow(Adw.ApplicationWindow):
    """Initial application window and startup-device gate."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.set_title("Greaseweazle")
        self.set_default_size(720, 560)
        self.set_size_request(460, 400)
        self._temporary_directories: list[tempfile.TemporaryDirectory[str]] = []
        self._file_chooser: Gtk.FileChooserNative | None = None

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        self.set_content(toolbar_view)

        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        toolbar_view.set_content(self._stack)
        self._stack.add_named(self._build_checking_page(), "checking")
        self._stack.add_named(self._build_dashboard(), "dashboard")
        self._stack.add_named(self._build_reading_page(), "reading")
        self._stack.set_visible_child_name("checking")

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
        self._reading_page.set_child(progress_box)
        return self._reading_page

    def _build_dashboard(self) -> Gtk.Widget:
        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=24,
            margin_top=32,
            margin_bottom=32,
            margin_start=24,
            margin_end=24,
        )

        device_group = Adw.PreferencesGroup(
            title="Device", description="The connected Greaseweazle is ready."
        )
        self._device_row = Adw.ActionRow(title="Greaseweazle")
        self._device_row.add_prefix(Gtk.Image.new_from_icon_name("drive-removable-media-symbolic"))
        self._device_row.set_activatable(False)
        device_group.add(self._device_row)
        content.append(device_group)

        operations_group = Adw.PreferencesGroup(
            title="Disk operations",
            description="Choose what you want to do with the disk in the drive.",
        )
        operations_group.add(
            self._operation_row(
                "Read disk",
                "Automatically identify and browse the disk without saving an image.",
                "folder-open-symbolic",
                lambda button: self._ask_read_format(button, save_image=False),
            )
        )
        operations_group.add(
            self._operation_row(
                "Extract disk to image",
                "Save the appropriate image format, or raw SCP for special disks.",
                "document-save-symbolic",
                lambda button: self._ask_read_format(button, save_image=True),
            )
        )
        operations_group.add(
            self._operation_row(
                "Write disk",
                "Write a supported disk image to a physical floppy disk.",
                "document-send-symbolic",
                self._choose_write_image,
            )
        )
        operations_group.add(
            self._operation_row(
                "Create blank image",
                "Create a new formatted disk image.",
                "document-new-symbolic",
            )
        )
        content.append(operations_group)

        clamp = Adw.Clamp(maximum_size=620, tightening_threshold=500)
        clamp.set_child(content)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(clamp)
        return scroller

    @staticmethod
    def _operation_row(
        title: str,
        subtitle: str,
        icon_name: str,
        callback: Callable[[Gtk.Button], None] | None = None,
    ) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
        button = Gtk.Button(valign=Gtk.Align.CENTER)
        if callback is None:
            button.set_label("Coming soon")
            button.set_sensitive(False)
        else:
            button.set_label(title)
            button.add_css_class("suggested-action")
            button.connect("clicked", callback)
        row.add_suffix(button)
        return row

    def _ask_read_format(self, button: Gtk.Button, *, save_image: bool) -> None:
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

        def respond(_dialog: Adw.MessageDialog, response: str) -> None:
            if response == "choose":
                self._choose_disk_format(button, save_image=save_image)
            elif response == "detect":
                self._start_auto_read(button, save_image=save_image)

        dialog.connect("response", respond)
        dialog.present()

    def _choose_write_image(self, _button: Gtk.Button) -> None:
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

        def worker() -> None:
            try:
                def report_progress(update: WriteProgress) -> None:
                    GLib.idle_add(
                        self._update_write_progress, update, can_verify
                    )

                result = write_disk(
                    image_path, disk_format, progress=report_progress
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
        self._stack.set_visible_child_name("dashboard")
        if not result.succeeded:
            self._show_error("Unable to write disk", result.summary, result.diagnostic)
            return GLib.SOURCE_REMOVE
        dialog = Adw.MessageDialog.new(
            self,
            "Complete",
            f"{image_path.name}: {result.summary}",
        )
        dialog.add_response("close", "Close")
        dialog.set_default_response("close")
        dialog.set_close_response("close")
        dialog.present()
        return GLib.SOURCE_REMOVE

    def _start_auto_read(self, _button: Gtk.Button, *, save_image: bool) -> None:
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

        def worker() -> None:
            try:
                def report_read(update: ReadProgress) -> None:
                    GLib.idle_add(self._update_read_progress, update)

                read_result = read_disk(
                    PROBE_FORMAT,
                    probe_image,
                    progress=report_read,
                    tracks="c=0:h=0-1",
                )
                if not read_result.succeeded:
                    GLib.idle_add(self._finish_read, read_result, temporary, None)
                    return
                GLib.idle_add(self._show_detecting_probe)
                probe = probe_format(
                    probe_image, Path(temporary.name), candidates=candidates
                )
                if probe.disk_format is not None:
                    disk_format = probe.disk_format
                    GLib.idle_add(self._show_identified_read, disk_format)
                    image_path = Path(temporary.name) / f"disk{disk_format.suffix}"
                    read_result = read_disk(
                        disk_format, image_path, progress=report_read
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
                    AUTO_DETECT_FORMAT, raw_image, progress=report_read
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
            (detection.contents, Path(temporary.name) / "export-cache"),
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
                failed = ReadResult(False, "The image could not be saved.", str(error))
                GLib.idle_add(self._finish_read, failed, temporary, None)
                return
            temporary.cleanup()
            GLib.idle_add(self._finish_image_save, destination)

        threading.Thread(target=save_worker, name="image-save", daemon=True).start()

    def _finish_image_save(self, destination: Path) -> bool:
        self._stack.set_visible_child_name("dashboard")
        dialog = Adw.MessageDialog.new(
            self,
            "Complete",
            f"The disk image was saved as {destination.name}.",
        )
        dialog.add_response("close", "Close")
        dialog.present()
        return GLib.SOURCE_REMOVE

    def _choose_disk_format(self, _button: Gtk.Button, *, save_image: bool) -> None:
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
    ) -> Gtk.Widget:
        choice_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=12,
            margin_bottom=6,
        )
        initial_label = (
            "Raw formats — raw flux (no conversion)"
            if initial_format is not None and not initial_format.gw_format
            else
            f"{manufacturer_name(initial_format.gw_format)} — "
            f"{format_menu_label(initial_format.gw_format)}"
            if initial_format is not None
            else "Choose manufacturer and format…"
        )
        menu_button = Gtk.MenuButton(
            label=initial_label,
            hexpand=True,
            halign=Gtk.Align.FILL,
        )
        menu = Gio.Menu()
        raw_flux_added = False
        for manufacturer, formats in grouped_formats():
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

        select_action.connect("activate", select_format)
        action_group.add_action(select_action)
        menu_button.insert_action_group("format", action_group)
        menu_button.set_menu_model(menu)
        choice_box.append(menu_button)
        choice_box.append(
            Gtk.Label(
                label=f"{sum(len(items) for _name, items in grouped_formats())} installed formats",
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
        if not save_image and disk_format.suffix not in {".adf", ".st"}:
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

        def worker() -> None:
            active_temporary = temporary
            try:
                def report_progress(update: ReadProgress) -> None:
                    GLib.idle_add(self._update_read_progress, update)

                result = read_disk(disk_format, destination, progress=report_progress)
                if not result.succeeded:
                    GLib.idle_add(self._finish_read, result, active_temporary, None)
                    return
                if active_temporary is None:
                    GLib.idle_add(
                        self._finish_image_only_read, destination, disk_format
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
                    (contents, cache_path),
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
        self, destination: Path, disk_format: DiskFormat
    ) -> bool:
        self._stack.set_visible_child_name("dashboard")
        dialog = Adw.MessageDialog.new(
            self,
            "Complete",
            f"The disk image was saved as {destination.name}.",
        )
        dialog.add_response("close", "Close")
        dialog.present()
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
        browser_details: tuple[DiskContents, Path] | None,
    ) -> bool:
        if not result.succeeded or temporary is None or browser_details is None:
            if temporary is not None:
                temporary.cleanup()
            self._stack.set_visible_child_name("dashboard")
            self._show_error("Unable to browse disk", result.summary, result.diagnostic)
            return GLib.SOURCE_REMOVE

        existing = self._stack.get_child_by_name("browser")
        if existing is not None:
            self._stack.remove(existing)
        contents, cache_path = browser_details
        try:
            browser = DiskBrowser(
                contents,
                cache_path,
                on_done=self._leave_browser,
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
        self._temporary_directories.append(temporary)
        self.set_default_size(1180, 720)
        self._stack.add_named(browser, "browser")
        self._stack.set_visible_child_name("browser")
        return GLib.SOURCE_REMOVE

    def _leave_browser(self) -> None:
        self.set_default_size(720, 560)
        self._stack.set_visible_child_name("dashboard")

    def _show_error(self, title: str, summary: str, diagnostic: str = "") -> None:
        body = summary
        if diagnostic:
            cleaned = diagnostic.strip()
            if len(cleaned) > 1800:
                cleaned = f"…{cleaned[-1800:]}"
            body = f"{body}\n\nDetails:\n{cleaned}"
        dialog = Adw.MessageDialog.new(self, title, body)
        dialog.add_response("close", "Close")
        dialog.set_default_response("close")
        dialog.set_close_response("close")
        dialog.present()

    def begin_device_detection(
        self,
        detector: Callable[[], DeviceProbeResult] = detect_device,
    ) -> None:
        """Run device detection without blocking GTK's event loop."""

        def worker() -> None:
            result = detector()
            GLib.idle_add(self._finish_device_detection, result)

        threading.Thread(target=worker, name="device-detection", daemon=True).start()

    def _finish_device_detection(self, result: DeviceProbeResult) -> bool:
        if result.connected:
            self._device_row.set_title(result.model)
            self._device_row.set_subtitle(result.port)
            self._stack.set_visible_child_name("dashboard")
            threading.Thread(
                target=supported_formats,
                name="format-catalog-loader",
                daemon=True,
            ).start()
            return GLib.SOURCE_REMOVE

        dialog = Adw.MessageDialog.new(
            self,
            "Greaseweazle not available",
            (
                f"{result.summary}\n\n"
                "Connect the Greaseweazle by USB, check that your user has "
                "permission to access it, then start the application again."
            ),
        )
        dialog.add_response("quit", "Quit")
        dialog.set_default_response("quit")
        dialog.set_close_response("quit")
        dialog.connect("response", self._on_detection_dialog_response)
        dialog.present()
        return GLib.SOURCE_REMOVE

    def _on_detection_dialog_response(self, _dialog: Adw.MessageDialog, _response: str) -> None:
        application = self.get_application()
        if application is not None:
            application.quit()
