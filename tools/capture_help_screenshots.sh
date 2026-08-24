#!/usr/bin/env bash
set -euo pipefail

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_dir="$project_dir/src/greaseweazle_gui/help_images"
mkdir -p "$output_dir"

if (( $# )); then
  states=("$@")
else
  states=(
    main
    read-progress
    capture-complete
    disk-browser
    write-progress
    blank-image
    image-inspector
    track-health
    image-library
    drive-tools
    diagnostic-log
  )
fi

for state in "${states[@]}"; do
  GREASEWEAZLE_GUI_DOCUMENTATION_STATE="$state" "$project_dir/greaseweazlegui" &
  app_pid=$!
  window_id=""
  for _attempt in {1..30}; do
    window_id=$(xwininfo -root -tree 2>/dev/null | awk '
      /"GreaseWeazleGUI"/ && /__main__\.py/ { print $1; exit }
    ')
    if [[ -n "$window_id" ]]; then
      break
    fi
    sleep 0.1
  done
  if [[ -z "$window_id" ]]; then
    kill "$app_pid" 2>/dev/null || true
    wait "$app_pid" 2>/dev/null || true
    printf 'Could not locate the %s documentation window\n' "$state" >&2
    exit 1
  fi
  sleep 0.4
  filename="$state.png"
  if [[ "$state" == "main" ]]; then
    filename="main-workspace.png"
  fi
  import -window "$window_id" "$output_dir/$filename"
  kill "$app_pid" 2>/dev/null || true
  wait "$app_pid" 2>/dev/null || true
done
