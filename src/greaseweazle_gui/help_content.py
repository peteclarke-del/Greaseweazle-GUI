"""User-focused technical content for the in-application guide."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HelpSection:
    heading: str
    paragraphs: tuple[str, ...]
    steps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HelpTopic:
    slug: str
    title: str
    summary: str
    screenshot: str
    screenshot_alt: str
    sections: tuple[HelpSection, ...]


HELP_TOPICS = (
    HelpTopic(
        "overview",
        "Getting Started",
        "Understand the workspace, menus, device state, and preservation rules.",
        "main-workspace.png",
        "Main GreaseWeazleGUI workspace with Open Image and Read Disk buttons",
        (
            HelpSection(
                "Workspace layout",
                (
                    "The main window is a container for every substantial task. File, Disk, Drive, and Help contain the complete command set. The centre of the window changes to show progress, a disk browser, technical results, or this guide.",
                    "Open Image and Read Disk remain on the start page because they are the two most common entry points. Use the Back button in the header to return to the start page from a result or browser.",
                ),
            ),
            HelpSection(
                "Preservation rules",
                (
                    "Reading and inspection never modify the source disk or image. The image browser is read-only. Writing a physical disk is destructive and always requires format confirmation.",
                    "For original, protected, unknown, or irreplaceable media, use Extract Disk to Image with the Protected Software profile. This retains raw flux in SCP rather than forcing the disk into a sector format.",
                ),
            ),
        ),
    ),
    HelpTopic(
        "device",
        "Device and Drive Selection",
        "Connect Greaseweazle, select drive A or B, and understand offline mode.",
        "main-workspace.png",
        "Connected Greaseweazle model, serial port, and selected drive",
        (
            HelpSection(
                "Connection state",
                (
                    "At startup the application runs gw info outside the GTK event loop. The start page shows the detected model and serial port. Physical disk commands stay disabled until both the host tools and hardware are available.",
                    "The application checks for removal and reconnection while it is idle on the start page. It does not poll during an active operation, which avoids competing for the USB device.",
                ),
                (
                    "Connect the Greaseweazle and externally powered floppy drive.",
                    "Open Drive and choose Drive A or Drive B to match the ribbon cable selection.",
                    "Choose Drive, Reconnect Device after changing hardware if automatic reconnection has not completed.",
                ),
            ),
            HelpSection(
                "Offline operation",
                (
                    "If no device is present, choose Use Images Offline. File operations such as Open Disk Image, Inspect or Convert Image, Image Library, and capture comparison remain available. Commands that require the drive are visibly disabled.",
                ),
            ),
        ),
    ),
    HelpTopic(
        "read",
        "Read and Browse a Disk",
        "Identify a disk, read it once, and browse its directory.",
        "read-progress.png",
        "Read progress showing track, cylinder, head, sectors, and retry state",
        (
            HelpSection(
                "Choose how to identify the disk",
                (
                    "Choose Read Disk on the start page or Disk, Read and Browse Disk. If the exact format is known, choose it from the manufacturer-grouped list. Atari ST also provides a family-level choice that detects 360, 400, 440, 720, 800, or 880 KB geometry.",
                    "Automatic detection first reads cylinder zero and tests plausible decoders. A recognised standard disk is then read directly into its normal sector image. If the probe is inconclusive, the application captures raw flux and tests supported formats without another physical read pass.",
                ),
                (
                    "Insert the disk and set its write-protect tab when possible.",
                    "Choose a capture profile. Normal is fastest, Difficult Media increases retries, and Archival reads more revolutions.",
                    "Choose Detect Automatically unless the exact low-level format is known.",
                    "Monitor track, cylinder, head, recovered sectors, and retry status in the progress page.",
                    "When directory validation succeeds, use the in-window dual-pane browser.",
                ),
            ),
            HelpSection(
                "Protected or damaged directories",
                (
                    "A valid track geometry does not prove that a commercial game has a normal filesystem. If FAT or directory validation detects a loop, overlap, invalid pointer, or impossible size, the application treats the disk as potentially protected or nonstandard and offers a raw SCP capture.",
                    "Do not interpret a failed directory listing as proof that the physical disk is bad. Review the track health report and preserve raw flux before trying recovery.",
                ),
            ),
        ),
    ),
    HelpTopic(
        "extract",
        "Extract Disk to Image",
        "Create a permanent sector image or preservation-grade raw capture.",
        "capture-complete.png",
        "Completed capture result inside the main window",
        (
            HelpSection(
                "Image choice",
                (
                    "Disk, Extract Disk to Image saves the complete disk rather than opening the temporary browser image. Standard Amiga disks use ADF, Atari ST disks use ST, Acorn DFS uses SSD or DSD, Commodore 1541 uses D64, and unusual media can be retained as SCP.",
                    "If automatic detection already captured SCP, later format analysis uses that capture. The physical disk is not read again simply to create a derived sector image.",
                ),
                (
                    "Choose the format or automatic detection.",
                    "Select the destination after the format is known.",
                    "Leave Save Capture Report enabled to create an adjacent .capture.json file.",
                    "Wait for Capture Complete before removing the disk.",
                ),
            ),
            HelpSection(
                "Capture report",
                (
                    "The JSON sidecar records the image filename, byte size, SHA-256, UTC capture time, Greaseweazle format, geometry, capture profile, device model and port, per-track output, and diagnostic text. It is written atomically beside the image.",
                ),
            ),
        ),
    ),
    HelpTopic(
        "browser",
        "Disk and File Browser",
        "Navigate the image and copy multiple files to the local filesystem.",
        "disk-browser.png",
        "Dual-pane disk browser with disk image on the left and local files on the right",
        (
            HelpSection(
                "Two-pane operation",
                (
                    "The left pane is the disk image and is always read-only. The right pane is the local filesystem. Both panes show their path at the top and support multiple selection, sorting, hidden-file control, keyboard navigation, context menus, and a traditional menu and toolbar.",
                    "The greater-than button copies selected disk items to the current local folder. The less-than button is disabled while the image is read-only. Source captures are never edited in place.",
                ),
                (
                    "Double-click a folder or press Enter to open it.",
                    "Use Backspace or Alt+Up to move to the parent folder.",
                    "Select one or more disk items and press the greater-than button, drag them to GNOME Files, or use Copy and Paste.",
                    "For naming conflicts choose Skip Existing, Keep Both, or Replace.",
                    "Open View, Disk Health to inspect track quality when physical read data is available.",
                ),
            ),
            HelpSection(
                "Supported filesystems",
                (
                    "Greaseweazle low-level format support and directory browsing are separate. The application can capture every format advertised by the installed host tools, but a normal file listing is possible only when the decoded image contains a filesystem understood by an installed reader.",
                    "The built-in bounded readers cover AmigaDOS OFS and FFS, Atari TOS and compatible FAT12 IMG or IMA images, Acorn DFS SSD and DSD, and Commodore 1541 D64. This includes suitable PC, MS-DOS, and other FAT12 sector images. Other formats can still be captured, inspected, converted, hashed, and written without presenting an empty or invented directory.",
                ),
            ),
        ),
    ),
    HelpTopic(
        "write",
        "Write an Image to Disk",
        "Detect the source image, confirm the format, write, and verify every track.",
        "write-progress.png",
        "Write and verification progress with cylinder, head, and retry status",
        (
            HelpSection(
                "Before writing",
                (
                    "Writing overwrites the floppy in the selected drive. The application inspects content first, then uses extension and size only as a fallback. You must confirm the final Greaseweazle format from the complete manufacturer-grouped list.",
                    "SCP and A2R are offered as raw flux with no sector conversion. This preserves timing and protection data. Converting raw flux to a sector format can discard weak bits, deliberate errors, and nonstandard tracks.",
                ),
                (
                    "Choose Disk, Write Image to Disk and select the source image.",
                    "Check the detected explanation and select the exact target format.",
                    "Confirm only after inserting the destination disk and checking drive A or B.",
                    "Keep the device connected until Write Complete appears.",
                    "Open View Track Report to inspect verification retries or failures.",
                ),
            ),
            HelpSection(
                "Verification",
                (
                    "Greaseweazle verifies supported sector formats during writing. Green track sides completed normally, amber track sides needed retries, and red identifies the final track side associated with a failed operation. Raw flux writing may not provide sector-level verification.",
                ),
            ),
        ),
    ),
    HelpTopic(
        "blank",
        "Create a Blank Image",
        "Build any creatable Greaseweazle media layout and initialise known filesystems.",
        "blank-image.png",
        "Completed blank Atari image with a ready-to-use FAT12 filesystem",
        (
            HelpSection(
                "Creating media",
                (
                    "Choose File, Create Blank Image. Formats come from the installed Greaseweazle version and are grouped by manufacturer. Detector-only or internally invalid definitions are omitted.",
                    "Atari ST formats can receive an Atari TOS FAT12 filesystem. Amiga DD and HD formats can receive AmigaDOS OFS. Enter a volume label and leave Create a ready-to-use filesystem selected. Other formats are created as valid media-level images and must be initialised on their target computer.",
                ),
                (
                    "Choose the exact machine and geometry.",
                    "Review whether filesystem creation is supported.",
                    "Choose the destination filename. The correct suffix is supplied.",
                    "Wait for Image Created. The destination is atomically replaced only after successful creation.",
                ),
            ),
        ),
    ),
    HelpTopic(
        "image-tools",
        "Inspect, Convert, and Compare",
        "Validate images without hardware and preserve the original file.",
        "image-inspector.png",
        "Image inspector showing detected format, geometry, filesystem, integrity, and SHA-256",
        (
            HelpSection(
                "Inspection",
                (
                    "File, Inspect or Convert Image calculates SHA-256 and reports the content-based format decision, geometry, byte size, filesystem, volume label, and structural integrity. Inspection is read-only and works without a Greaseweazle device.",
                ),
            ),
            HelpSection(
                "Conversion",
                (
                    "Convert creates a new file through the installed Greaseweazle codecs. The source is not modified, and the destination is replaced atomically only after a successful conversion. Choose a format that is compatible with the information present in the source.",
                    "A sector image cannot represent arbitrary flux timing, weak bits, or some protection schemes. Keep the original SCP or A2R whenever converting raw media.",
                ),
            ),
            HelpSection(
                "Capture comparison",
                (
                    "Compare first checks SHA-256. Identical hashes mean byte-for-byte equality. For compatible ADF and ST geometry, differing data is then reported by cylinder and head. Raw captures with different timing cannot be reduced to a trustworthy sector-side comparison, so they are reported as different without a false track equivalence.",
                ),
            ),
        ),
    ),
    HelpTopic(
        "health",
        "Track Health and Recovery",
        "Interpret the track map and retry only damaged fixed-sector tracks.",
        "track-health.png",
        "Cylinder and head health map using green, amber, and red markers",
        (
            HelpSection(
                "Map meaning",
                (
                    "Each row is a cylinder and each column is a head. Green means the final read recovered every expected sector without a reported retry. Amber means recovery succeeded after more than one attempt. Red means sectors were still missing or Greaseweazle gave up.",
                    "Hover a marker to see the original Greaseweazle track message. The summary counts damaged and recovered track sides rather than hiding them behind a single completion percentage.",
                ),
            ),
            HelpSection(
                "Selective retry",
                (
                    "For fixed-sector ADF and ST captures, Retry Damaged Tracks reads only red cylinder and head positions with difficult-media settings. Recovered track blocks are merged into a copy and the image is replaced atomically. Unexpected partial layouts or geometry mismatches leave the source unchanged.",
                ),
            ),
        ),
    ),
    HelpTopic(
        "library",
        "Image Library",
        "Catalogue a local folder and find duplicate captures.",
        "image-library.png",
        "In-window image library listing formats, volume labels, and duplicate counts",
        (
            HelpSection(
                "Local catalogue",
                (
                    "File, Image Library recursively scans a folder for known floppy image suffixes. It records path, size, SHA-256, detected format, filesystem, and volume label for the current view. Files are inspected read-only and nothing is uploaded.",
                    "Matching SHA-256 values are exact duplicates. Similar filenames or labels do not count as duplicates. Symbolic links are skipped and a safety limit prevents an unexpectedly large directory tree from consuming unbounded resources.",
                ),
            ),
        ),
    ),
    HelpTopic(
        "maintenance",
        "Drive Maintenance",
        "Measure spindle speed, test USB bandwidth, and use a cleaning disk safely.",
        "drive-tools.png",
        "Drive maintenance result displayed inside the main application window",
        (
            HelpSection(
                "Spindle speed and bandwidth",
                (
                    "Drive, Measure Spindle Speed samples five revolutions on the selected drive. A nominal 300 RPM or 360 RPM mechanism should remain close to its rated speed. Large variation can indicate belt, motor, index, or media problems.",
                    "Test USB Bandwidth checks communication between the host and Greaseweazle. It does not read disk sectors. Retain the output in the Diagnostic Log when investigating unstable transfers.",
                ),
            ),
            HelpSection(
                "Head cleaning",
                (
                    "Clean Drive Heads runs the Greaseweazle zig-zag cleaning command. Use only a proper cleaning disk with the correct cleaning fluid and follow its manufacturer instructions. Never start this command with a data disk inserted. The confirmation is intentionally destructive in appearance because misuse can damage media.",
                ),
            ),
        ),
    ),
    HelpTopic(
        "troubleshooting",
        "Troubleshooting and Diagnostics",
        "Resolve startup, format, filesystem, read, and write failures.",
        "diagnostic-log.png",
        "Diagnostic log with copy, save, and clear controls",
        (
            HelpSection(
                "Startup and device problems",
                (
                    "If host tools are unavailable, verify that gw is on PATH by running gw info in a terminal. If the host tools work but the device is absent, check USB data cable, permissions, power, and whether another program owns the serial port.",
                    "The local Device block remains authoritative if gw identifies the hardware and a later online firmware-release check fails. Network outages or GitHub API rate limits are retained in diagnostics but do not disable local disk operations.",
                    "The source launcher removes inherited Snap and editor GTK module paths that can load incompatible libraries. The warning about an unknown gtk-modules key comes from the desktop GTK settings and does not prevent this application from running.",
                ),
            ),
            HelpSection(
                "Disk and filesystem problems",
                (
                    "Wrong geometry usually causes missing sectors on many tracks or an image size that does not match its format. A healthy track map with a directory error can instead indicate copy protection or a deliberately nonstandard filesystem. Preserve SCP before experimenting.",
                    "A looping FAT chain, recursive directory, overlapping DFS files, or invalid Commodore sector pointer is rejected to prevent corrupt metadata from causing an unbounded read or unsafe extraction.",
                ),
            ),
            HelpSection(
                "Diagnostic log",
                (
                    "Help, Diagnostic Log shows command output and local filenames from failed operations. Copy or save it when requesting support. The log does not include the contents of files stored on the disk image. Clear removes only the in-memory session log.",
                ),
            ),
        ),
    ),
    HelpTopic(
        "reference",
        "Menu and Keyboard Reference",
        "Find every command and the browser shortcuts in one place.",
        "main-workspace.png",
        "GreaseWeazleGUI application menu in the window header",
        (
            HelpSection(
                "Application menus",
                (
                    "File contains Open Disk Image, Inspect or Convert Image, Image Library, Create Blank Image, and Quit. Disk contains Read and Browse Disk, Extract Disk to Image, and Write Image to Disk. Drive contains drive A or B, spindle speed, USB bandwidth, cleaning, and reconnection. Help contains this User Guide and the Diagnostic Log.",
                ),
            ),
            HelpSection(
                "Browser shortcuts",
                (
                    "Ctrl+O opens the selected item. Ctrl+X, Ctrl+C, and Ctrl+V cut, copy, and paste in the active pane. Ctrl+A selects all. Delete moves selected local items to Trash. Backspace and Alt+Up open the parent folder. Enter opens the single selected item. Multiple selections are supported with the normal GTK Ctrl and Shift selection gestures.",
                ),
            ),
        ),
    ),
)
