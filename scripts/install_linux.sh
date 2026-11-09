#!/bin/sh
set -eu

bundle_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install_dir="$HOME/.local/opt/cave-portable/current"
icon_dir="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
desktop_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
bin_dir="$HOME/.local/bin"

mkdir -p "$install_dir" "$icon_dir" "$desktop_dir" "$bin_dir"
install -m 755 "$bundle_dir/CAVE-Portable" "$install_dir/CAVE-Portable"
install -m 644 "$bundle_dir/cave-portable.png" "$icon_dir/cave-portable.png"
ln -sfn "$install_dir/CAVE-Portable" "$bin_dir/cave-portable"

cat > "$desktop_dir/cave-portable.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=CAVE Portable
Comment=Weather visualization and official warning companion
Exec="$bin_dir/cave-portable"
TryExec=$bin_dir/cave-portable
Icon=cave-portable
Terminal=false
Categories=Science;
StartupNotify=true
StartupWMClass=Caveportable
EOF

printf 'Installed CAVE Portable for %s\n' "$HOME"
