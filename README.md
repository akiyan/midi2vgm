# midi2vgm

MIDI を Sega Mega Drive / Genesis 向けの VGM に変換する Python ツールです。

主な出力は YM2612(FM) + SN76489(PSG) の `.vgm` です。生成した VGM は、SGDK の
`rescomp` や `xgmtool` / `xgm2tool` に渡して XGM / XGM2 再生用素材として組み込めます。

このリポジトリは公開用なので、MIDI ファイル、生成済み VGM、SoundFont、ROM、ゲーム側ハーネスは
含めません。入力 MIDI と出力 VGM のパスはコマンドライン引数で明示します。

## 機能

- Standard MIDI File を Python 標準ライブラリだけで解析
- GM プログラム、音域、音数から MIDI パートを YM2612 FM / SN76489 PSG へ自動割り当て
- 通常は FM を最大 5ch に抑え、FM6/DAC を空ける構成
- `--pcm-drums` で MIDI ch10 のドラムを FluidSynth + SoundFont から PCM 化
- `--pcm-shot` で短い装飾音パートを PCM ワンショットとして薄く追加
- `--fm6` で FM6 まで使い、ドラムを PSG ノイズ化
- `--bell-psg` でオルゴール系主旋律へ PSG 矩形ユニゾンを追加
- `genpsg.py` で SN76489 PSG 専用 VGM を生成

## 必要なもの

通常の変換:

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

## 使い方

基本形:

```sh
python3 scripts/genvgm.py 入力.mid 出力.vgm [オプション]
```

例:

```sh
mkdir -p out
python3 scripts/genvgm.py /path/to/your_song.mid out/your_song.vgm --pcm-drums --atten=6
```

PCM を使わず、FM6 まで BGM に使う場合:

```sh
python3 scripts/genvgm.py /path/to/your_song.mid out/your_song_fm6.vgm --fm6 --atten=6
```

オルゴール系主旋律へ PSG ユニゾンを足し、短い装飾音を PCM shot にする場合:

```sh
python3 scripts/genvgm.py /path/to/02_introduction.mid out/02_introduction.vgm \
  --pcm-drums --bell-psg --pcm-shot=auto+4 --atten=6
```

## genvgm.py のオプション

- `--pcm-drums`
  MIDI ch10 のドラムを FluidSynth でレンダリングし、VGM stream PCM として埋め込みます。
  XGM2 の PCM 再生へ渡す用途を想定しています。
- `--pcm-shot=auto`
  短い装飾音らしいパートを自動検出し、薄い PCM ワンショット層として追加します。
- `--pcm-shot=4,5`
  指定した MIDI チャンネルを PCM shot にします。チャンネル番号は 1 始まりです。
- `--pcm-shot=auto+4`
  自動検出と手動指定を併用します。
- `--fm6`
  YM2612 FM6 まで BGM に使います。FM6 と DAC は排他なので、PCM 系オプションとは併用できません。
  ドラムは PSG ノイズに変換されます。
- `--bell-psg`
  bell / music box 系の主旋律アタックへ PSG 矩形波のユニゾンを重ねます。
- `--no-psg`
  PSG tone を使わず、旋律パートを FM に寄せます。別モードで扱わない限りドラムは省略されます。
- `--atten=N`
  FM オペレータの TL に `N` を加えて音量を下げます。TL は大きいほど小音量です。
  `6` が扱いやすい初期値です。
- `--sf2=PATH`
  FluidSynth で使う SoundFont を指定します。

## PSG 専用 VGM

`genpsg.py` は SN76489 PSG だけを使う VGM を生成します。Game Gear 風の制約で鳴らしたい場合や、
PSG のみでどこまで成立するかを確認したい場合に使います。

```sh
python3 scripts/genpsg.py 入力.mid 出力_psg.vgm \
  --tone0=1:decay=soft:vib \
  --tone1=4:decay=pluck \
  --tone2=8:decay=sustain:oct=+1 \
  --noise=drums
```

`--toneN` の書式:

```text
--tone0=<MIDI ch>[:decay=pluck|soft|sustain][:oct=±N][:vib][:atten=N]
```

複数の MIDI チャンネルを 1 本の PSG tone にまとめることもできます。

```sh
python3 scripts/genpsg.py /path/to/song.mid out/song_psg.vgm \
  --tone0=1+4+5:decay=soft:vib \
  --tone1=7:decay=soft \
  --tone2=8:decay=sustain \
  --noise=drums
```

複数チャンネルをまとめた場合は高い音を優先し、メロディの受け渡しで無音になりにくくします。

## SGDK / XGM への組み込み

SGDK の `.res` では、生成済み VGM を次のように参照できます。

```text
XGM2 bgm02 "bgm/02_introduction.vgm"
```

基本的な流れ:

1. `genvgm.py` または `genpsg.py` で `.vgm` を生成する。
2. 生成した `.vgm` をゲーム側プロジェクトのリソースディレクトリへ置く。
3. SGDK の `.res` に `XGM` または `XGM2` として追加する。
4. ゲーム側プロジェクトを通常どおりビルドする。

注意点:

- `--pcm-drums` と `--pcm-shot` は XGM2 の PCM stream へ渡す想定です。
- `--fm6` は PCM を使わないアレンジ用です。YM2612 の FM6 と DAC は同時に使えません。
- 最終的な音量や発音の確認は、対象プロジェクトで使う XGM ドライバ経由で行ってください。

## ディレクトリ構成

```text
scripts/
  genvgm.py     MIDI -> YM2612 + SN76489 VGM
  genpsg.py     MIDI -> SN76489 専用 VGM
  psg_voice.py  PSG の減衰、ビブラート、オクターブ折り返し処理
assets/midi/
  adjustments.txt  元プロジェクトの曲別調整例
  annotations.md   元プロジェクトの MIDI 曲メモ
assets/vgm/
  psg.txt          元プロジェクトの PSG 手動マッピング例
docs/
  midi-vgm-conversion-policy.md  変換方針メモ
  sfc-bgm-routing.md             元プロジェクトのルーティング例
```

`assets/` 以下のテキストは、元プロジェクトで使った調整・分析メモです。変換ツールが暗黙に読む
入力ディレクトリではありません。

## 公開リポジトリとしての方針

このリポジトリでは次のものを管理しません。

- ローカルの `*.mid` 入力
- 生成済みの `*.vgm`
- SoundFont
- ROM
- エミュレータ録画やスクリーンショット

git に入れるのは、コード、テキスト設定例、ドキュメントだけにします。権利関係のある MIDI は、
各自の手元のパスをコマンドラインで指定してください。

## 制限

- MIDI パーサは小さく作っています。tick-based の Standard MIDI File を対象にし、SMPTE division は
  対応していません。
- FM 音色割り当ては GM プログラムを見たヒューリスティックで、完全な MIDI シンセではありません。
- 曲によっては `--fm6`、`--bell-psg`、`--pcm-shot`、`genpsg.py` の tone 指定などの手動調整が必要です。
- ループは、ゲーム側で生成 VGM の先頭へ戻す前提です。
- 汎用 VGM プレイヤーでの聞こえ方だけでなく、最終的に使う XGM / XGM2 変換後の結果を確認してください。

## ライセンス

MIT。詳細は `LICENSE` を参照してください。
