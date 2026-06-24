#!/usr/bin/env python3
"""MIDI ファイルを一括で VGM 化する（変換ルールの一元管理）。

既定は `--pcm-drums`（ドラムを 3 PCM チャンネルへ振り分け＝XGM2 の 3 PCM 音）。
`assets/midi/adjustments.txt` で `<name> fm6` と指定した曲だけ `--fm6`（FM6ch・ドラムは
PSG ノイズ）にする。出力は `res/bgm/<name>.vgm`。

使い方:
  python3 scripts/genallbgm.py                         # assets/midi/*.mid を一括変換
  python3 scripts/genallbgm.py 02_introduction [...]    # 指定曲だけ

要 fluidsynth + GM SoundFont（--pcm-drums のドラム合成）。公開リポジトリでは MIDI と
生成物 res/bgm/*.vgm はコミットしない。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ATTEN = "6"

def load_tokens():
    """assets/midi/adjustments.txt を読み {key: set(tokens)} を返す。'#' はコメント。
    行形式: '<key> tok ...'（key はフル名 '05_washi...' でも先頭番号 '05' でも可）。
    認識トークン: 'fm6'（FM6ch・ドラム PSG ノイズ） / 'bell+psg'（bell 主旋律に PSG 矩形ユニゾン）
    / 'pcm-shot' or 'pcm-shot=auto|ch,ch...|auto+ch...'（短い装飾音を空きPCMへ重ねる。chはMIDIの1始まり）。"""
    path = os.path.join(HERE, "assets/midi/adjustments.txt")
    table = {}
    if not os.path.exists(path):
        return table
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        table.setdefault(parts[0], set()).update(t.lower() for t in parts[1:])
    return table


def tokens_for(song, table):
    toks = set()
    for k, ts in table.items():
        if song == k or song.split("_", 1)[0] == k or song.startswith(k + "_"):
            toks |= ts
    return toks


def build_one(song, out_name, toks):
    flags = ["--fm6"] if "fm6" in toks else ["--pcm-drums"]   # fm6=PSG ノイズdrums / pcm=3ch PCMdrums
    if "bell+psg" in toks:
        flags.append("--bell-psg")
    for tok in sorted(toks):
        if tok == "pcm-shot":
            flags.append("--pcm-shot=auto")
        elif tok.startswith("pcm-shot="):
            flags.append("--" + tok)
    mid = os.path.join(HERE, f"assets/midi/{song}.mid")
    out = os.path.join(HERE, f"res/bgm/{out_name}.vgm")
    cmd = ["python3", os.path.join(HERE, "scripts/genvgm.py"), mid, out, *flags, f"--atten={ATTEN}"]
    print(f"[{' '.join(sorted(toks)) or 'pcm'}] {out_name}")
    if subprocess.run(cmd).returncode != 0:
        sys.exit(f"genvgm failed for {out_name}")


def discover_songs():
    midi_dir = os.path.join(HERE, "assets", "midi")
    if not os.path.isdir(midi_dir):
        return []
    songs = []
    for name in sorted(os.listdir(midi_dir)):
        stem, ext = os.path.splitext(name)
        if ext.lower() in (".mid", ".midi"):
            songs.append(stem)
    return songs


def main():
    only = sys.argv[1:]
    songs = only or discover_songs()
    if not songs:
        sys.exit("no MIDI files found under assets/midi/ and no songs were specified")
    table = load_tokens()
    os.makedirs(os.path.join(HERE, "res", "bgm"), exist_ok=True)
    for s in songs:
        toks = tokens_for(s, table)
        build_one(s, s, toks)


if __name__ == "__main__":
    main()
