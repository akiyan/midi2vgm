#!/usr/bin/env python3
"""assets/vgm/psg.txt を読み、各曲を PSG 専用 VGM（GG 向け）へ一括変換する。

出力は assets/vgm/<曲名>_PSG.vgm。MIDI は assets/midi/<曲名>.mid を使う。
変換本体は scripts/genpsg.py。psg.txt のフォーマットは psg.txt 冒頭のコメント参照。

  使い方: python3 scripts/genallpsg.py [曲名 ...]
    曲名を渡すとその曲だけ変換（拡張子なしのベース名 or psg.txt のセクション名）。
    省略時は psg.txt の全セクションを変換する。
"""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIDI_DIR = os.path.join(ROOT, "assets", "midi")
OUT_DIR = os.path.join(ROOT, "assets", "vgm")
PSG_TXT = os.path.join(OUT_DIR, "psg.txt")
GENPSG = os.path.join(ROOT, "scripts", "genpsg.py")


def load_sections(path):
    """psg.txt -> {section: {key: [tokens...]}}（key=tone0/tone1/tone2/noise）。"""
    sections = {}
    cur = None
    for raw in open(path, encoding="utf-8"):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = line[1:-1].strip()
            sections[cur] = {}
        elif cur is not None and "=" in line:
            key, val = line.split("=", 1)
            sections[cur][key.strip()] = val.split()
    return sections


def spec_args(section):
    """セクション dict -> genpsg.py の --toneN=/--noise= 引数列。"""
    args = []
    for pc in range(3):
        toks = section.get(f"tone{pc}")
        if not toks:
            continue
        ch = toks[0]
        spec = ":".join([ch] + toks[1:])      # '1:decay=soft:vib' のような形に
        args.append(f"--tone{pc}={spec}")
    if "noise" in section and section["noise"] and section["noise"][0] == "drums":
        args.append("--noise=drums")
    return args


def main():
    sections = load_sections(PSG_TXT)
    want = sys.argv[1:]
    os.makedirs(OUT_DIR, exist_ok=True)
    targets = want if want else list(sections.keys())
    for name in targets:
        base = name[:-4] if name.endswith(".mid") else name
        mid = os.path.join(MIDI_DIR, base + ".mid")
        if not os.path.exists(mid):
            print(f"!! MIDI not found: {mid}", file=sys.stderr)
            continue
        out = os.path.join(OUT_DIR, base + "_PSG.vgm")
        args = spec_args(sections.get(base, {}))
        cmd = [sys.executable, GENPSG, mid, out] + args
        print("=>", base, " ".join(args) or "(auto)")
        r = subprocess.run(cmd)
        if r.returncode != 0:
            sys.exit(f"genpsg failed for {base}")


if __name__ == "__main__":
    main()
