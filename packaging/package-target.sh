# shellcheck shell=bash
# The package_distro variable is set here for the scripts that source this file.
# shellcheck disable=SC2034
#
# The system the Debian package is built for, and the name of the package
# file. build-deb.sh sources this file; nothing else builds the name.
#
# The installed package records the same name, with the version left as
# {version}, in /usr/lib/greaseweazlegui/package-target. Check for
# Application Updates (greaseweazle_gui.app_update) reads that record and
# downloads the file of that name from a newer release, so an installed copy
# only ever takes the package built for its own distribution release and
# architecture. tests/test_app_update.py runs these functions and checks that
# the application reads what they write.

# The distribution release the package is built for, as it appears in the
# file name. It is the release of the build system unless PACKAGE_DISTRO names
# one. Each release gets its own package because the bundled dependencies
# include compiled modules for that release's Python. Linux Mint 22 is based
# on Ubuntu 24.04 and uses the same package.
if [[ -n "${PACKAGE_DISTRO:-}" ]]; then
    package_distro="${PACKAGE_DISTRO}"
else
    package_distro="$(. /etc/os-release && printf '%s%s' "${ID}" "${VERSION_ID}")"
fi

# supported_python DISTRO
#
# Prints the system Python version the package for DISTRO must be built
# with, or fails for a release no package is made for.
supported_python() {
    case "$1" in
        ubuntu24.04) echo 3.12 ;;
        ubuntu26.04) echo 3.14 ;;
        *) return 1 ;;
    esac
}

# package_file_name VERSION ARCH
#
# Prints the name of the package file for one version and architecture.
package_file_name() {
    printf 'Greaseweazle-GUI_%s_%s_%s.deb' "$1" "${package_distro}" "$2"
}

# write_package_target FILE ARCH
#
# Writes the record of the system the package is built for to FILE.
write_package_target() {
    printf 'distro=%s\narch=%s\npackage=%s\n' \
        "${package_distro}" "$2" "$(package_file_name '{version}' "$2")" > "$1"
}
