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
# file name. Linux Mint 22 is based on Ubuntu 24.04 and uses the same package.
package_distro=ubuntu24.04

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
