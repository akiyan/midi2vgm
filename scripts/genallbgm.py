#!/usr/bin/env python3
"""Convert one or more MIDI files to YM2612/SN76489 VGM files.

This is a small wrapper around genvgm.py. It does not search a repository-local
input directory; MIDI source paths are passed explicitly on the command line.
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENVGM = os.path.join(ROOT, "scripts", "genvgm.py")


def load_tokens(path):
    """Read adjustment tokens as {key: set(tokens)}. '#' starts a comment.

    Line format: '<key> tok ...'. key may be a full basename such as
    '02_introduction' or a numeric prefix such as '02'.
    """
    table = {}
    if not path:
        return table
    if not os.path.exists(path):
        raise SystemExit(f"adjustments file not found: {path}")
    for line in open(path, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        table.setdefault(parts[0], set()).update(t.lower() for t in parts[1:])
    return table


def tokens_for(stem, table):
    toks = set()
    prefix = stem.split("_", 1)[0]
    for key, key_tokens in table.items():
        if stem == key or prefix == key or stem.startswith(key + "_"):
            toks |= key_tokens
    return toks


def flags_for(tokens):
    flags = ["--fm6"] if "fm6" in tokens else ["--pcm-drums"]
    if "bell+psg" in tokens:
        flags.append("--bell-psg")
    for tok in sorted(tokens):
        if tok == "pcm-shot":
            flags.append("--pcm-shot=auto")
        elif tok.startswith("pcm-shot="):
            flags.append("--" + tok)
    return flags


def output_path(mid, out_dir):
    stem = os.path.splitext(os.path.basename(mid))[0]
    return os.path.join(out_dir, stem + ".vgm")


def main():
    ap = argparse.ArgumentParser(description="Convert MIDI files to VGM with genvgm.py.")
    ap.add_argument("midi", nargs="+", help="input MIDI path(s)")
    ap.add_argument("-o", "--out-dir", default=".", help="output directory for .vgm files")
    ap.add_argument(
        "-a",
        "--adjustments",
        default="",
        help="per-song adjustment file; use '' to disable",
    )
    ap.add_argument("--atten", default="6", help="FM attenuation passed to genvgm.py")
    args = ap.parse_args()

    adjustments = args.adjustments or ""
    table = load_tokens(adjustments)
    os.makedirs(args.out_dir, exist_ok=True)

    for mid in args.midi:
        if not os.path.exists(mid):
            raise SystemExit(f"MIDI not found: {mid}")
        stem = os.path.splitext(os.path.basename(mid))[0]
        tokens = tokens_for(stem, table)
        out = output_path(mid, args.out_dir)
        cmd = [sys.executable, GENVGM, mid, out, *flags_for(tokens), f"--atten={args.atten}"]
        print(f"[{' '.join(sorted(tokens)) or 'pcm'}] {mid} -> {out}")
        if subprocess.run(cmd).returncode != 0:
            raise SystemExit(f"genvgm failed for {mid}")


if __name__ == "__main__":
    main()
