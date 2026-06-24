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
- MIDI ch10 のドラムを既定で FluidSynth + SoundFont から PCM 化
- `--pcm-shot` で短い装飾音パートを PCM ワンショットとして薄く追加
- `--fm6 --psg-drums` で FM6 まで使い、ドラムを PSG ノイズ化
- `--bell-psg` でオルゴール系主旋律へ PSG 矩形ユニゾンを追加
- `genpsg.py` で SN76489 PSG 専用 VGM を生成

## 必要なもの

通常の変換:

```sh
sudo apt-get update
sudo apt-get install -y python3 fluidsynth fluid-soundfont-gm
```

PCM ドラムを使わず `--psg-drums` だけで変換する場合は Python 3.10+ だけで動きます。

```sh
sudo apt-get install -y python3
```

既定の SoundFont は `SOUNDFONT`、`/usr/share/sounds/sf2/default-GM.sf2`、
`/usr/share/sounds/sf2/FluidR3_GM.sf2` の順に探します。別の SoundFont を使う場合は
`--sf2=/path/to/file.sf2` または `SOUNDFONT=/path/to/file.sf2` を指定します。

SGDK プロジェクトへ組み込む場合は、別途 SGDK の `rescomp` と `xgmtool` / `xgm2tool` が必要です。
このリポジトリ自体は VGM の生成までを担当します。

Python の追加 pip パッケージは不要です。

## 使い方

ローカルコマンドとしてインストール:

```sh
./install.sh
midi2vgm 入力.mid 出力.vgm [オプション]
```

インストール先は既定で `~/.local/bin/midi2vgm` です。別の場所に入れる場合は
`PREFIX=/path/to/prefix ./install.sh` を使います。

基本形:

```sh
python3 scripts/genvgm.py 入力.mid 出力.vgm [オプション]
```

例:

```sh
mkdir -p out
python3 scripts/genvgm.py /path/to/your_song.mid out/your_song.vgm --atten=6
```

PCM ドラムを使わず、PSG ノイズドラムにする場合:

```sh
python3 scripts/genvgm.py /path/to/your_song.mid out/your_song_psgdrum.vgm --psg-drums --atten=6
```

PCM を使わず、FM6 まで BGM に使う場合:

```sh
python3 scripts/genvgm.py /path/to/your_song.mid out/your_song_fm6.vgm --fm6 --psg-drums --atten=6
```

オルゴール系主旋律へ PSG ユニゾンを足し、短い装飾音を PCM shot にする場合:

```sh
python3 scripts/genvgm.py /path/to/02_introduction.mid out/02_introduction.vgm \
  --bell-psg --pcm-shot=auto+4 --atten=6
```

## genvgm.py のオプション

- PCM drums
  既定で MIDI ch10 のドラムを FluidSynth でレンダリングし、VGM stream PCM として埋め込みます。
  XGM2 の PCM 再生へ渡す用途を想定しています。
- `--psg-drums`
  PCM ドラムを使わず、MIDI ch10 のドラムを PSG ノイズへ変換します。
- `--pcm-shot=auto`
  短い装飾音らしいパートを自動検出し、薄い PCM ワンショット層として追加します。
- `--pcm-shot=4,5`
  指定した MIDI チャンネルを PCM shot にします。チャンネル番号は 1 始まりです。
- `--pcm-shot=auto+4`
  自動検出と手動指定を併用します。
- `--fm6`
  YM2612 FM6 まで BGM に使います。FM6 と DAC は排他なので、PCM 系オプションとは併用できません。
  PCM ドラムが既定のため、使う場合は `--psg-drums` も指定してください。
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

## MIDI から FM パッチへの変換

`genvgm.py` は MIDI の音色をそのまま再生するシンセではありません。MIDI の GM プログラム番号、
音域、平均音長、音符数、表情コントロールの有無を見て、メガドライブの YM2612 で破綻しにくい
現在は `bass` を含む 14 種類の FM パッチへ寄せます。

基本方針は次の通りです。

- MIDI ch10 はドラムとして扱い、既定では PCM、`--psg-drums` なら PSG ノイズへ送ります。
- ドラム以外で平均音域が最も低い MIDI チャンネルを bass として扱い、FM の低音用パッチへ送ります。
- それ以外の MIDI チャンネルは GM プログラム番号で `piano`、`bell`、`organ`、`guitar`、
  `distguitar`、`bassgtr`、`strings`、`brass`、`softlead`、`clar`、`flute`、`synthlead`、`pad`、`pluck`
  のいずれかへ分類します。
- FM は通常 5ch まで使います。パート数が多い場合は、短い音・軽い補助・表情が少ないパートを PSG へ逃がします。
- `--fm6` を指定した場合だけ FM6 を追加ボイスとして使います。ただし FM6 と DAC/PCM は排他です。

GM プログラム番号から FM パッチへの対応は次の通りです。番号は MIDI 内部の 0 始まりです。
一般的な MIDI エディタが 1 始まりで表示する場合は、表示値から 1 を引いた値として見てください。
`bass` は GM program だけではなく、ドラム以外で平均音域が最も低い MIDI チャンネルに優先して割り当てます。
`softlead` は金管系のうち、長めでモジュレーションまたはピッチベンドがある旋律向けの派生パッチです。

| GM program | 主な GM 音色 | FM パッチ |
|---:|---|---|
| 0-7 | Piano / Electric Piano | `piano` |
| 8-15 | Celesta / Glockenspiel / Music Box / Vibraphone など | `bell` |
| 16-23 | Organ 系 | `organ` |
| 24-28, 31 | Guitar / Plucked 系 | `guitar` |
| 29-30 | Overdriven / Distortion Guitar | `distguitar` |
| 32-39 | Bass 系 | `bassgtr`。最低音域の土台に選ばれた場合は `bass` |
| 40-55 | Strings / Ensemble / Choir 系 | `strings` |
| 56-63 | Trumpet / Trombone / Brass 系 | `brass`。長めで表情がある場合は `softlead` |
| 64-71 | Sax / Reed 系 | `clar` |
| 72-79 | Pipe / Flute 系 | `flute` |
| 80-87 | Synth Lead 系 | `synthlead` |
| 88-103 | Pad / Synth Effects 系 | `pad` |
| 104-111 | Ethnic 系 | `pluck` |
| 112-119 | Percussive / Sound Effects 系 | `bell` |
| 120-127 | Sound Effects 系 | `pad` |
| その他 | 未分類 | `flute` |

各 FM パッチの意図は次の通りです。

| パッチ | 用途 | 音作りの方針 |
|---|---|---|
| `bass` | 最低音域の土台 | alg4。基音と 2 倍音を使うタイトな低音。平均音長が非常に長い場合はキャリアを持続寄りに変えて、土台がすぐ消えないようにします。 |
| `bassgtr` | GM のベース系パート | alg4。最低音域ではない bass program の受け皿です。`bass` より丸く、短い減衰で補助的に鳴らします。 |
| `piano` | ピアノ、エレピ | alg4。DX 風のエレピ寄り。高倍音の短いアタックと中程度の減衰で、打鍵感を出します。 |
| `bell` | オルゴール、グロッケン、ヴィブラフォン | alg4。高い倍音を速く減衰させ、硬いアタックと少し残る余韻を作ります。`--bell-psg` を使うとアタックに PSG のピンを足します。 |
| `organ` | オルガン | alg7。減衰をほぼ持たない並列キャリアで、薄いドローバー感を出します。 |
| `guitar` | ギター、撥弦 | alg4。`pluck` より胴鳴りを少し残し、ナイロンギターやクリーンギターの伴奏を FM 側で支えます。 |
| `distguitar` | 歪みギター | alg5。強めのフィードバックとデチューンしたキャリアで、Overdriven / Distortion Guitar のリフを `guitar` より太く潰して鳴らします。 |
| `pluck` | 民族楽器、硬い撥弦 | alg4。`guitar` より明るい倍音と速い減衰で、粒立ちを優先します。 |
| `strings` | 弦、合唱、パッド | alg7。複数キャリアを軽くデチューンし、薄いコーラス感と持続感を出します。 |
| `brass` | 金管 | alg5。強いアタック、フィードバック、倍音で前に出る音にします。 |
| `softlead` | 表情のある長めの金管リード | alg7。`brass` より柔らかく、LFO のビブラート量を多めにして伸びる旋律向けにします。 |
| `clar` | サックス、クラリネット | alg4。少し鼻にかかったリード感を持つ中庸の旋律パッチです。 |
| `flute` | フルート、笛、未分類 | alg7。デチューンした並列キャリアと軽いビブラートで、細めのリードや未分類パートの受け皿にします。 |
| `synthlead` | シンセリード | alg7。並列キャリア、軽いデチューン、強めの LFO で、伸びる電子リードを作ります。 |
| `pad` | パッド、効果音系 | alg7。遅めのアタックとデチューンで、背景に薄く敷く音を作ります。 |

YM2612 の設定では、パッチごとに次の要素を使い分けています。

- `alg`: オペレータ接続。`alg7` は並列キャリアで持続音向き、`alg4` / `alg5` はモジュレータで輪郭を作ります。
- `fb`: フィードバック量。brass、bell、distguitar ではアタックや倍音感を強めます。
- `mul`: 倍音比。bell、piano、guitar、distguitar、pluck では高めの倍音を短く鳴らして打鍵感を作ります。
- `tl`: オペレータ音量。`--atten=N` は主に可聴キャリア側の TL を増やして全体音量を下げます。
- `ar` / `d1r` / `d2r` / `slrr`: エンベロープ。打鍵系は速いアタックと速めの減衰、持続系はゆるい減衰にします。
- `dt`: DT1 デチューン。持続音ではプラス/マイナス方向にずらして厚みを出します。
- `rs`: レートスケーリング。高音ほど減衰が速くなるため、piano、guitar、distguitar、pluck の高音が長く残りすぎるのを抑えます。
- `fms`: LFO の周波数変調量。flute、strings、softlead などの持続音で軽いビブラートを付けます。

同じ FM パッチに複数の MIDI チャンネルが入る場合は、パッチ単位で FM ハードウェアチャンネルを共有します。
各グループに最低 1 本を割り当て、音符数が多いグループや複数 MIDI チャンネルを含むグループへ優先的に
追加ボイスを渡します。FM が足りないときは古い発音を奪うため、変換後の聞こえ方は MIDI の完全再現ではなく、
メガドライブ音源上で破綻しにくい再配置になります。

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

- 既定の PCM ドラムと `--pcm-shot` は XGM2 の PCM stream へ渡す想定です。
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

## 制限

- MIDI パーサは小さく作っています。tick-based の Standard MIDI File を対象にし、SMPTE division は
  対応していません。
- FM 音色割り当ては GM プログラムを見たヒューリスティックで、完全な MIDI シンセではありません。
- 曲によっては `--fm6`、`--bell-psg`、`--pcm-shot`、`genpsg.py` の tone 指定などの手動調整が必要です。
- ループは、ゲーム側で生成 VGM の先頭へ戻す前提です。
- 汎用 VGM プレイヤーでの聞こえ方だけでなく、最終的に使う XGM / XGM2 変換後の結果を確認してください。

## ライセンス

MIT。詳細は `LICENSE` を参照してください。
