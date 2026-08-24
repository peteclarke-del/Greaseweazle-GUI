# Contributing to Greaseweazle-GUI

This application handles media that may be irreplaceable. Changes must preserve
source images, make destructive actions explicit, and fail safely.

## Before starting

Open an issue for a material format change, new dependency, or workflow
redesign. Do not attach copyrighted software, private images, credentials, or
device identifiers. Report security defects according to [SECURITY.md](SECURITY.md).

## Development workflow

1. Create a focused branch from current `main`.
2. Keep hardware subprocess arguments as arrays; never interpolate user input
   into a shell command.
3. Treat image contents, filenames, local paths, and Greaseweazle output as
   untrusted.
4. Add regression coverage for changed detection, filesystem, or I/O logic.
5. Update user documentation when behaviour or terminology changes.
6. Submit a pull request using the repository template.

## Tests

Run before submitting:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
ruff check src tests
ruff format --check src tests
bash -n greaseweazle-gui
bash -n packaging/*.sh
desktop-file-validate data/com.github.pclarke.GreaseweazleGUI.desktop
appstreamcli validate --no-net data/com.github.pclarke.GreaseweazleGUI.metainfo.xml
```

Format changes should include generated fixtures and negative cases for
truncation, corruption, invalid geometry, and cancellation. Physical hardware
evidence is valuable, but does not replace deterministic tests.

Filesystem support is separate from Greaseweazle track-format support. A new
browser reader must be bounded against loops, invalid offsets, oversized
directories, recursive structures, and truncated images. Document whether the
reader can identify content independently or relies on an image suffix.

## Pull requests

Explain the user-visible result, formats affected, destructive-operation
boundary, failure modes tested, accessibility impact, and exact verification
commands. Keep unrelated changes in separate pull requests.
