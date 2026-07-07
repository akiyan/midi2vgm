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

# 任意: GeneralUser GS(軽量な GM+GS SoundFont)を自動検出パスへ取得する。
# 既定では落とさない。INSTALL_SOUNDFONT=1 ./install.sh で有効化。
if [ "${INSTALL_SOUNDFONT:-0}" = "1" ]; then
  SF2_DIR=${SF2_DIR:-"$HOME/.local/share/sounds/sf2"}
  SF2_PATH="$SF2_DIR/GeneralUser-GS.sf2"
  SF2_URL="https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/main/GeneralUser-GS.sf2"
  if [ -f "$SF2_PATH" ]; then
    echo "soundfont present: $SF2_PATH"
  else
    mkdir -p "$SF2_DIR"
    echo "downloading GeneralUser GS -> $SF2_PATH"
    if command -v curl >/dev/null 2>&1; then
      curl -fSL -o "$SF2_PATH" "$SF2_URL"
    elif command -v wget >/dev/null 2>&1; then
      wget -O "$SF2_PATH" "$SF2_URL"
    else
      echo "error: need curl or wget to download the soundfont" >&2
      exit 1
    fi
    echo "soundfont installed: $SF2_PATH (use --soundfont=generaluser)"
  fi
fi
