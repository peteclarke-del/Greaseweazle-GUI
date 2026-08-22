# Security policy

Greaseweazle GUI parses untrusted floppy images and can write to physical
media through an external hardware tool. Security reports are welcome even
though the application is intended for a single local GNOME user.

## Supported versions

| Version | Security fixes |
| --- | --- |
| Current `main` branch | Yes |
| Latest published release | Yes |
| Older tags and unmaintained branches | No |

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private
[Report a vulnerability](https://github.com/peteclarke-del/GreaseWeaselGUI/security/advisories/new)
workflow. If that workflow is unavailable, contact the repository owner
privately using the address on the maintainer's GitHub profile. Include the
affected version or commit, host distribution, a minimal reproduction using
media you may lawfully share, and sanitised logs.

You should receive an acknowledgement within five working days. Disclosure
timing will be coordinated with the reporter. These are response targets, not
a service-level agreement.

Reports are especially useful for command or argument injection, unsafe image
parsing, path traversal, unintended host-file access, unauthorised physical
disk writes, misleading format detection that could cause data loss, and
vulnerable dependencies.

Use generated media and disposable disks for research. Do not test systems or
data you do not own. This project does not operate a bug bounty.
