#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Terminals opened by Snap-packaged editors can leak their private GTK and
# GLib loader paths into child processes. Loading those modules into the host
# Python process can crash before the application starts. Use the host
# defaults whenever the inherited toolkit configuration belongs to a Snap.
if [[ "${GTK_PATH:-}" == /snap/* || "${GTK_EXE_PREFIX:-}" == /snap/* ]]; then
    unset GTK_PATH GTK_EXE_PREFIX GTK_IM_MODULE_FILE
    unset GDK_PIXBUF_MODULE_FILE GDK_PIXBUF_MODULEDIR
    unset GIO_MODULE_DIR GSETTINGS_SCHEMA_DIR LOCPATH
    unset XDG_DATA_HOME XDG_DATA_DIRS
fi

if [[ -n "${PYTHONPATH:-}" ]]; then
    export PYTHONPATH="${script_dir}/src:${PYTHONPATH}"
else
    export PYTHONPATH="${script_dir}/src"
fi

exec python3 -m greaseweazle_gui "$@"
