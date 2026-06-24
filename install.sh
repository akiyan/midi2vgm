#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PREFIX=${PREFIX:-"$HOME/.local"}
BIN_DIR=${BIN_DIR:-"$PREFIX/bin"}
APP_DIR=${APP_DIR:-"$PREFIX/share/midi2vgm"}

mkdir -p "$BIN_DIR" "$APP_DIR/scripts"

install -m 0644 "$ROOT/scripts/genvgm.py" "$APP_DIR/scripts/genvgm.py"
install -m 0644 "$ROOT/scripts/genpsg.py" "$APP_DIR/scripts/genpsg.py"
install -m 0644 "$ROOT/scripts/psg_voice.py" "$APP_DIR/scripts/psg_voice.py"

cat > "$BIN_DIR/midi2vgm" <<EOF
#!/usr/bin/env sh
exec python3 "$APP_DIR/scripts/genvgm.py" "\$@"
EOF
chmod 0755 "$BIN_DIR/midi2vgm"

echo "installed: $BIN_DIR/midi2vgm"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "note: add $BIN_DIR to PATH to run midi2vgm from any shell" ;;
esac
