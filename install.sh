#!/bin/sh
# Install Raks on Batocera (or any Linux using a custom.sh-style autostart).
#   ./install.sh              install to /userdata/system/raks and register autostart
#   ./install.sh uninstall    remove autostart entry and the installed copy
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${RAKS_DEST:-/userdata/system/raks}"
CUSTOM="${RAKS_CUSTOM:-/userdata/system/custom.sh}"
BEGIN="# >>> raks >>>"
END="# <<< raks <<<"

strip_block() {
  [ -f "$CUSTOM" ] || return 0
  tmp="$CUSTOM.raks.tmp"
  awk -v b="$BEGIN" -v e="$END" '$0==b{skip=1;next} $0==e{skip=0;next} !skip{print}' "$CUSTOM" >"$tmp"
  cat "$tmp" >"$CUSTOM"; rm -f "$tmp"
}

if [ "$1" = "uninstall" ]; then
  [ -x "$DEST/run.sh" ] && "$DEST/run.sh" stop || true
  strip_block
  rm -rf "$DEST"
  echo "Raks removed."
  exit 0
fi

mkdir -p "$DEST"
if [ "$SRC" != "$DEST" ]; then
  [ -f "$DEST/config.json" ] && cp "$DEST/config.json" /tmp/raks-config.keep
  for item in host client presets docs run.sh install.sh config.json LICENSE README.md contrib; do
    [ -e "$SRC/$item" ] && { rm -rf "$DEST/$item"; cp -r "$SRC/$item" "$DEST/$item"; }
  done
  [ -f /tmp/raks-config.keep ] && { mv /tmp/raks-config.keep "$DEST/config.json"; echo "Kept your existing config.json"; }
fi
chmod +x "$DEST/run.sh" "$DEST/install.sh" "$DEST/host/raks_host.py"

touch "$CUSTOM"
strip_block
cat >>"$CUSTOM" <<EOT
$BEGIN
# Raks: phones as gamepads. Batocera calls custom.sh with "start" / "stop".
"$DEST/run.sh" "\$@"
$END
EOT
chmod +x "$CUSTOM"

echo "Raks installed in $DEST"
echo "  * Start now:  $DEST/run.sh start"
echo "  * Edit settings: $DEST/config.json  (port, max_players, pin, actions)"
echo "  * It will also start automatically on boot."
