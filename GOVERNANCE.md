# Project governance

## Scope and roles

Greaseweazle-GUI is a native GNOME application for inspecting, imaging, and
writing floppy media through Greaseweazle hardware. Peter Clarke
(`@peteclarke-del`) is the current maintainer and release owner. Contributors
may propose, implement, test, and review changes; repository administration and
release authority remain with the maintainer unless this file is updated.

## Decision priorities

Decisions are made in this order:

1. Prevent unintended modification or loss of physical disks and source images.
2. Preserve physical layout, filesystem metadata, and nonstandard protection.
3. Fail closed when format, geometry, path, or device state is uncertain.
4. Prefer reproducible generated-media and real-hardware evidence.
5. Keep one authoritative implementation for detection and disk operations.
6. Maintain a clear, keyboard-operable GNOME interface.

Significant format, security, licensing, dependency, hardware-support, or
release-policy changes require an issue before implementation. Normal changes
are decided through pull-request review.

Only the maintainer creates releases. Security reports follow
[SECURITY.md](SECURITY.md); conduct concerns follow
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
