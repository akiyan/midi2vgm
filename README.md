# midi2vgm

MIDI を Sega Mega Drive / Genesis 向けの VGM に変換する Python ツール群です。

主な出力は YM2612(FM) + SN76489(PSG) の `.vgm` です。SGDK の `rescomp` や
`xgmtool`/`xgm2tool` に渡すことで、XGM / XGM2 再生用の素材として組み込めます。

このリポジトリは公開用なので、MIDI ファイル、生成済み VGM、SoundFont、ROM、ゲーム側ハーネスは
含めません。MIDI のソースパスはコマンドライン引数で指定します。

## Features

- Standard MIDI File を Python 標準ライブラリだけで解析
- GM プログラム、音域、音数から MIDI パートを YM2612 FM / SN76489 PSG へ自動割り当て
- FM は通常最大 5ch 使用し、FM6/DAC を空ける構成
- `--pcm-drums` で MIDI ch10 のドラムを FluidSynth + SoundFont から PCM 化
- `--pcm-shot` で短い装飾音パートを PCM ワンショットとして薄く追加
- `--fm6` で FM6 まで使う代わりにドラムを PSG ノイズ化
- `--bell-psg` でオルゴール系主旋律へ PSG 矩形ユニゾンを追加
- PSG 専用 VGM 生成用の `genpsg.py` / `genallpsg.py`
- 曲別の調整ファイルを `--adjustments` で指定可能
- PSG 専用の手動ルーティングを `--map` で指定可能

## Requirements

必須:

```sh
sudo apt-get update
sudo apt-get install -y python3
```

PCM ドラムまたは PCM shot を使う場合:

```sh
sudo apt-get install -y fluidsynth fluid-soundfont-gm
```

既定の SoundFont は Ubuntu の `/usr/share/sounds/sf2/default-GM.sf2` です。別の SoundFont を使う場合は
`--sf2=/path/to/file.sf2` または `SOUNDFONT=/path/to/file.sf2` を指定します。

SGDK プロジェクトへ組み込む場合は、別途 SGDK の `rescomp` と `xgmtool` / `xgm2tool` が必要です。
このリポジトリ自体は VGM の生成までを担当します。

Python の追加 pip パッケージは不要です。

## Quick Start

```sh
git clone <repo-url> midi2vgm
cd midi2vgm
mkdir -p out
python3 scripts/genvgm.py /path/to/your_song.mid out/your_song.vgm --pcm-drums --atten=6
```

PCM を使わず、FM6 まで BGM に使う場合:

```sh
python3 scripts/genvgm.py /path/to/your_song.mid out/your_song_fm6.vgm --fm6 --atten=6
```

PSG 専用 VGM を作る場合:

```sh
python3 scripts/genpsg.py /path/to/your_song.mid out/your_song_psg.vgm \
  --tone0=1:decay=soft:vib \
  --tone1=2:decay=pluck \
  --tone2=5:decay=sustain:oct=+1 \
  --noise=drums
```

## Directory Layout

```text
scripts/
  genvgm.py       MIDI -> YM2612 + SN76489 VGM
  genallbgm.py    wrapper for explicit MIDI paths -> .vgm
  genpsg.py       MIDI -> SN76489-only VGM
  genallpsg.py    PSG wrapper for explicit MIDI paths
  psg_voice.py    shared PSG decay/vibrato/octave-folding helpers
assets/midi/
  adjustments.txt example per-song options for genallbgm.py
  annotations.md  example catalog/notes for a MIDI set
assets/vgm/
  psg.txt         PSG-only manual routing table
docs/
  midi-vgm-conversion-policy.md  conversion design notes
  sfc-bgm-routing.md             example routing snapshot from the source project
res/bgm/
  generated normal VGM output directory
```

## genvgm.py

```sh
python3 scripts/genvgm.py IN.mid OUT.vgm [options]
```

Options:

- `--pcm-drums`
  Render MIDI ch10 drums through FluidSynth and embed them as VGM stream PCM.
  This is intended for XGM2-style PCM playback.
- `--pcm-shot=auto`
  Detect short decorative pitched parts and add them as a light PCM one-shot layer.
- `--pcm-shot=4,5`
  Add specific MIDI channels as PCM shot layers. Channel numbers are 1-based.
- `--pcm-shot=auto+4`
  Combine automatic detection with manual channel selection.
- `--fm6`
  Use YM2612 FM6 for music. This cannot be combined with PCM because FM6 and DAC
  are mutually exclusive on the YM2612. Drums are converted to PSG noise.
- `--bell-psg`
  Add a PSG square-wave unison to bell/music-box style lead attacks.
- `--no-psg`
  Avoid PSG tone channels and route melodic parts to FM. Drums are omitted unless
  another mode handles them.
- `--atten=N`
  Add `N` to FM operator TL values. Larger TL means lower volume. `6` is a useful
  starting point.
- `--sf2=PATH`
  SoundFont for FluidSynth PCM rendering.

Examples:

```sh
python3 scripts/genvgm.py /path/to/02_introduction.mid out/02_introduction.vgm \
  --pcm-drums --bell-psg --pcm-shot=auto+4 --atten=6

python3 scripts/genvgm.py /path/to/03_gerende_no_koibitotachi.mid out/03_gerende.vgm \
  --fm6 --atten=6
```

## Multi-file Wrapper

`scripts/genallbgm.py` is a thin wrapper around `genvgm.py`. MIDI paths are explicit
arguments; there is no implicit input directory.

```sh
python3 scripts/genallbgm.py -o out /path/to/02_introduction.mid /path/to/03_gerende.mid
python3 scripts/genallbgm.py --adjustments ./my-adjustments.txt -o out /path/to/02_introduction.mid
```

Per-song flags are read from `--adjustments` when specified. No adjustment file
is loaded implicitly. The repository includes `assets/midi/adjustments.txt` as an
example preset.

Format:

```text
# key token...
02 bell+PSG pcm-shot=auto+4
03 fm6
```

`key` can be a full song basename such as `02_introduction` or a numeric prefix such
as `02`. Tokens are case-insensitive.

Supported tokens:

- `fm6`
- `bell+PSG`
- `pcm-shot`
- `pcm-shot=auto`
- `pcm-shot=4,5`
- `pcm-shot=auto+4`

## PSG-only Conversion

`genpsg.py` creates a VGM that uses only SN76489 PSG. This is useful for Game Gear
style output or for checking what a track sounds like under hard PSG constraints.

Direct use:

```sh
python3 scripts/genpsg.py IN.mid OUT.vgm \
  --tone0=1:decay=soft:vib \
  --tone1=4:decay=pluck \
  --tone2=8:decay=sustain:oct=+1 \
  --noise=drums
```

Wrapper use:

```sh
python3 scripts/genallpsg.py -o out /path/to/02_introduction.mid
python3 scripts/genallpsg.py --map ./my-psg.txt -o out /path/to/02_introduction.mid
```

No PSG map is loaded implicitly. The `--map` file format:

```text
[song_basename]
tone0 = 1 decay=soft vib
tone1 = 4 decay=pluck
tone2 = 8 decay=sustain oct=+1
noise = drums
```

Multiple MIDI channels can be merged into one PSG tone with `+`:

```text
tone0 = 1+4+5 decay=soft vib
```

When multiple channels are merged, the converter keeps the higher note so melodic
handoffs do not collapse into silence.

## SGDK / XGM Integration

Generated VGM can be referenced from SGDK resources and converted by SGDK tooling.
For XGM2-style music:

```text
XGM2 bgm02 "bgm/02_introduction.vgm"
```

Typical flow:

1. Generate `.vgm` into your game project's resource directory.
2. Add the VGM to the SGDK `.res` file as `XGM` or `XGM2`.
3. Run SGDK `rescomp` / normal project build.

Notes:

- `--pcm-drums` and `--pcm-shot` are meant for XGM2-style PCM streams.
- `--fm6` is for PCM-free arrangements because YM2612 FM6 shares the DAC path.
- Always test the converted result through the same XGM driver used by the target
  project.

## Public Repository Policy

This repository intentionally ignores:

- local `*.mid` inputs
- generated `*.vgm` files
- SoundFont files
- ROMs and emulator captures

Keep only code, text presets, and documentation in git. If you maintain a private
project with licensed MIDI assets, pass those paths to the CLI tools directly.

## Limitations

- The MIDI parser is intentionally small. It supports standard tick-based SMF and
  does not support SMPTE division.
- FM patch assignment is heuristic and GM-program based, not a full MIDI synth.
- Some tracks need manual adjustment through `adjustments.txt` or `psg.txt`.
- Loop handling assumes game-side looping from the beginning of the generated VGM.
- Final balance should be judged after VGM -> XGM/XGM2 conversion, not only from
  generic VGM playback.

## License

MIT. See `LICENSE`.
