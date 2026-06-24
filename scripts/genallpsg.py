#!/usr/bin/env python3
"""Convert one or more MIDI files to SN76489-only VGM files.

This is a wrapper around genpsg.py. MIDI source paths are always passed
explicitly on the command line. Optional routing presets are read from psg.txt.
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENPSG = os.path.join(ROOT, "scripts", "genpsg.py")


def load_sections(path):
    """psg.txt -> {section: {key: [tokens...]}} where key is tone0/tone1/tone2/noise."""
    sections = {}
    if not path:
        return sections
    if not os.path.exists(path):
        raise SystemExit(f"PSG map not found: {path}")
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
    args = []
    for pc in range(3):
        toks = section.get(f"tone{pc}")
        if not toks:
            continue
        ch = toks[0]
        spec = ":".join([ch] + toks[1:])
        args.append(f"--tone{pc}={spec}")
    if "noise" in section and section["noise"] and section["noise"][0] == "drums":
        args.append("--noise=drums")
    return args


def main():
    ap = argparse.ArgumentParser(description="Convert MIDI files to PSG-only VGM with genpsg.py.")
    ap.add_argument("midi", nargs="+", help="input MIDI path(s)")
    ap.add_argument("-o", "--out-dir", default=".", help="output directory for .vgm files")
    ap.add_argument(
        "-m",
        "--map",
        default="",
        help="PSG routing map; use '' to disable",
    )
    args = ap.parse_args()

    sections = load_sections(args.map or "")
    os.makedirs(args.out_dir, exist_ok=True)

    for mid in args.midi:
        if not os.path.exists(mid):
            raise SystemExit(f"MIDI not found: {mid}")
        stem = os.path.splitext(os.path.basename(mid))[0]
        out = os.path.join(args.out_dir, stem + "_PSG.vgm")
        cmd = [sys.executable, GENPSG, mid, out, *spec_args(sections.get(stem, {}))]
        print(f"=> {mid} -> {out}")
        if subprocess.run(cmd).returncode != 0:
            raise SystemExit(f"genpsg failed for {mid}")


if __name__ == "__main__":
    main()
