#!/usr/bin/env python3
"""MIDI → YM2413 (OPLL, MSX-MUSIC) + AY-3-8910 (MSX PSG) の VGM を生成する（MSX 向け）。

MSX の FM 音源 MSX-MUSIC（YM2413、クロック 3579545Hz）と PSG（AY-3-8910、1789772.5Hz）だけで鳴らす。
VGM は YM2413（コマンド 0x51）と AY8910（0xA0）を使い、vgmplay / libvgm などでそのまま試聴できる。

OPLL の制約への対応:
  - 旋律は 9ch。ch10 のドラムがある曲はリズムモード（BD/SD/TOM/CYM/HH の FM ドラム）にして旋律は 6ch。
  - 音色は内蔵 15 種と自作 1 種だけ。GM プログラムを内蔵音色へ写し、内蔵に近いものがない
    ストリングス系（40-55, 88-95）は自作音色（--user=strings|pad|... で選択）にまとめる。
  - 音量は 4bit（3dB 刻み）。ベロシティ・CC7・CC11 を 40log10 で dB にして減衰量にする。
  - 同じ音を重ねただけのチャンネル（一定のティック差のエコーを含め、同じ音程か 1〜2 オクターブ違い）は
    FM に入れない。同時刻・同じ音程のものは鳴らさず、エコーやオクターブ違いは PSG に余りがあれば
    PSG で少し小さく重ねる。
  - 各パートは同時発音数ぶんの FM チャンネルを専有する（音色の切り替えを避ける）。FM に入らない
    単音パートは PSG（矩形 3ch、エンベロープはソフトで段階制御）へ回し、それでも余るパートは鳴らさない。
  - ピッチベンド（±2 半音）とダンパー（CC64）を反映する。モジュレーション・パン・エフェクトは使わない。
  - 曲頭の無音を削る（genvgm.py / genpsg.py と同じく、初期化の後の最初のイベントを 0 に寄せる）。
    MIDI の頭のセットアップ用の小節（リセットや音色の設定だけで 1〜3 秒）を待たずに鳴り始め、
    ループ点は初期化の直後（曲頭）。--keep-lead-in で MIDI どおりの時刻のままにする。

使い方:
  genopll.py IN.mid OUT.vgm [--fm=CH,CH...] [--psg=CH,CH...] [--drop=CH,...] [--no-rhythm]
                           [--user=strings|pad|brass|bass] [--prog=CH:OPLL] [--psg-atten=N] [--atten=N]
                           [--keep-lead-in]
    CH は MIDI チャンネル（1 始まり）。--fm / --psg で割り当てを固定、--prog=CH:N で OPLL 音色 N（0=自作）。
"""
import math
import os
import struct
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psg_voice as pv

OPLL_CLOCK = 3579545
AY_CLOCK = 1789773
SR = 44100
DRUM_CH = 9
BEND_RANGE = 2.0

# GM プログラム → OPLL 内蔵音色（1-15）。0 は自作音色。
# 1 Violin 2 Guitar 3 Piano 4 Flute 5 Clarinet 6 Oboe 7 Trumpet 8 Organ 9 Horn 10 Synth
# 11 Harpsichord 12 Vibraphone 13 Synth bass 14 Acoustic bass 15 Electric guitar
def gm_to_opll(p):
    if p <= 5: return 3
    if p <= 7: return 11
    if p <= 15: return 12
    if p <= 23: return 8 if p < 22 else 6          # organs; harmonica/accordion → oboe
    if p <= 26: return 2
    if p <= 31: return 15
    if p <= 37: return 14
    if p <= 39: return 13
    if p <= 44: return 0 if p >= 42 else 1          # violin/viola → violin; cello/contrabass → user
    if p == 45: return 2                             # pizzicato
    if p == 46: return 11                            # harp
    if p == 47: return 14                            # timpani
    if p <= 55: return 0                             # string/voice ensembles → user
    if p == 56: return 7
    if p <= 58: return 9
    if p == 59: return 7
    if p == 60: return 9
    if p <= 63: return 7
    if p <= 67: return 5                             # saxes
    if p <= 69: return 6
    if p == 70: return 6
    if p == 71: return 5
    if p <= 79: return 4
    if p <= 87: return 10
    if p <= 95: return 0                             # pads → user
    if p <= 103: return 10
    if p <= 111: return 2
    if p <= 119: return 12
    return 10

# 自作音色（OPLL レジスタ 0x00-0x07）
USER_PATCHES = {
    # やわらかい持続音（ストリングス合奏）
    "strings": bytes([0x61, 0x61, 0x1B, 0x05, 0x52, 0x42, 0x13, 0x15]),
    # さらに立ち上がりの遅いパッド
    "pad":     bytes([0x61, 0x61, 0x1C, 0x04, 0x32, 0x32, 0x12, 0x14]),
    "brass":   bytes([0x21, 0x21, 0x14, 0x06, 0x71, 0x61, 0x22, 0x16]),
    "bass":    bytes([0x01, 0x01, 0x10, 0x07, 0xF3, 0xF4, 0x23, 0x13]),
}

# GM ドラム → OPLL リズム（bit: 4 BD, 3 SD, 2 TOM, 1 CYM, 0 HH）
def drum_bit(note):
    if note in (35, 36): return 4
    if note in (37, 38, 39, 40): return 3
    if note in (41, 43, 45, 47, 48, 50): return 2
    if note in (49, 51, 52, 53, 55, 57, 59): return 1
    return 0                                         # hats, tambourine, cowbell and the rest

argv = [a for a in sys.argv[1:] if not a.startswith("--")]
opts = {a.split("=", 1)[0][2:]: (a.split("=", 1)[1] if "=" in a else "")
        for a in sys.argv[1:] if a.startswith("--")}
if len(argv) < 2:
    sys.exit(__doc__)
MID, OUT = argv[0], argv[1]

def chlist(name):
    v = opts.get(name, "")
    return [int(x) - 1 for x in v.split(",") if x]

# ============ MIDI 解析 ============
data = open(MID, "rb").read()
assert data[:4] == b"MThd", "not a MIDI file"
fmt, ntrk, div = struct.unpack(">HHH", data[8:14])
assert div & 0x8000 == 0, "SMPTE division not supported"

def read_tracks(d):
    i = 14; tr = []
    while i < len(d):
        if d[i:i+4] != b"MTrk":
            i += 1; continue
        ln = struct.unpack(">I", d[i+4:i+8])[0]
        tr.append(d[i+8:i+8+ln]); i += 8 + ln
    return tr

def parse_track(buf):
    ev = []; i = 0; tick = 0; status = 0
    while i < len(buf):
        dt = 0
        while True:
            c = buf[i]; i += 1; dt = (dt << 7) | (c & 0x7F)
            if not (c & 0x80): break
        tick += dt
        b0 = buf[i]
        if b0 & 0x80:
            status = b0; i += 1
        if status == 0xFF:
            mtype = buf[i]; i += 1; mlen = 0
            while True:
                c = buf[i]; i += 1; mlen = (mlen << 7) | (c & 0x7F)
                if not (c & 0x80): break
            md = buf[i:i+mlen]; i += mlen
            if mtype == 0x51 and mlen == 3:
                ev.append((tick, "tempo", (md[0] << 16) | (md[1] << 8) | md[2], -1))
        elif status in (0xF0, 0xF7):
            sl = 0
            while True:
                c = buf[i]; i += 1; sl = (sl << 7) | (c & 0x7F)
                if not (c & 0x80): break
            i += sl
        else:
            hi = status & 0xF0; chn = status & 0x0F
            if hi in (0xC0, 0xD0):
                if hi == 0xC0: ev.append((tick, "prog", buf[i], chn))
                i += 1
            else:
                a = buf[i]; b = buf[i+1]; i += 2
                if hi == 0x90 and b > 0: ev.append((tick, "on", (a, b), chn))
                elif hi == 0x80 or hi == 0x90: ev.append((tick, "off", (a, 0), chn))
                elif hi == 0xB0: ev.append((tick, "cc", (a, b), chn))
                elif hi == 0xE0: ev.append((tick, "bend", ((b << 7) | a) - 8192, chn))
    return ev

events = []
for n, t in enumerate(read_tracks(data)):
    events += [(e[0], n, k, e) for k, e in enumerate(parse_track(t))]
events.sort(key=lambda e: (e[0], e[1], e[2]))

timed = []                                    # (sec, kind, value, chan)
cur_tempo = 500000; last_tick = 0; sec = 0.0
for tick, _, _, (t_, kind, val, ch) in events:
    sec += (tick - last_tick) * (cur_tempo / 1e6) / div
    last_tick = tick
    if kind == "tempo":
        cur_tempo = val
    else:
        timed.append((sec, kind, val, ch))

# ============ 音符（ダンパー込み）とチャンネルの状態 ============
def notes_of(ch):
    """[(start, end, midi, vel)] of channel ch, note-offs held while CC64 is down."""
    out, held, pedal, sustained = [], {}, False, []
    for s, kind, val, c in timed:
        if c != ch:
            continue
        if kind == "on":
            note, vel = val
            if note in held:                         # the same key again: end the last one here
                st, v0 = held.pop(note)
                out.append((st, s, note, v0))
            held[note] = (s, vel)
        elif kind == "off":
            note = val[0]
            if note in held:
                if pedal:
                    sustained.append(note)
                else:
                    st, vel = held.pop(note)
                    out.append((st, s, note, vel))
        elif kind == "cc" and val[0] == 64:
            down = val[1] >= 64
            if pedal and not down:
                for note in sustained:
                    if note in held:
                        st, vel = held.pop(note)
                        out.append((st, s, note, vel))
                sustained = []
            pedal = down
    end = timed[-1][0] if timed else 0
    for note, (st, vel) in held.items():
        out.append((st, end, note, vel))
    out.sort()
    return [n for n in out if n[1] > n[0]]

def controller_track(ch, number, default):
    """[(sec, value)] of a controller (or 'bend') on ch, starting with the default."""
    out = [(0.0, default)]
    for s, kind, val, c in timed:
        if c != ch:
            continue
        if number == "bend" and kind == "bend":
            out.append((s, val))
        elif kind == "cc" and val[0] == number:
            out.append((s, val[1]))
    return out

def value_at(track, s):
    v = track[0][1]
    for t, x in track:
        if t > s:
            break
        v = x
    return v

def max_poly(notes):
    edges = sorted([(n[0], 1) for n in notes] + [(n[1], -1) for n in notes], key=lambda e: (e[0], e[1]))
    cur = best = 0
    for _, d in edges:
        cur += d; best = max(best, cur)
    return best

programs = {}
for s, kind, val, c in timed:
    if kind == "prog":
        programs.setdefault(c, val)
channels = sorted({c for s, k, v, c in timed if k == "on"})
melodic = [c for c in channels if c != DRUM_CH]
notes = {c: notes_of(c) for c in melodic}

# 重ねただけのチャンネル: ノートオンの列が、一定のティック差（エコー、2 拍まで）と一定の音程差
# （0 / ±12 / ±24）で別のチャンネルと一致する
onsets = {}
for tick, _, _, (t_, kind, val, ch) in events:
    if kind == "on":
        onsets.setdefault(ch, []).append((tick, val[0]))
doubles = {}                                   # ch -> (of_ch, semitones, delay ticks)
for i, a in enumerate(melodic):
    for b in melodic[i + 1:]:
        if b in doubles or a in doubles:
            continue
        oa, ob = onsets.get(a, []), onsets.get(b, [])
        if len(oa) != len(ob) or not oa:
            continue
        delay = ob[0][0] - oa[0][0]
        if abs(delay) > 2 * div or any((y[0] - x[0]) != delay for x, y in zip(oa, ob)):
            continue
        diffs = {y[1] - x[1] for x, y in zip(oa, ob)}
        if len(diffs) == 1 and next(iter(diffs)) in (0, 12, -12, 24, -24):
            if delay < 0:                       # the later one is the copy
                a, b, delay = b, a, -delay
            doubles[b] = (a, onsets[b][0][1] - onsets[a][0][1], delay)

# ============ 割り当て ============
rhythm = DRUM_CH in channels and "no-rhythm" not in opts
fm_capacity = 6 if rhythm else 9
avg = {c: sum(n[2] for n in notes[c]) / len(notes[c]) for c in melodic if notes[c]}
poly = {c: max_poly(notes[c]) for c in melodic}
forced_fm, forced_psg, dropped = chlist("fm"), chlist("psg"), chlist("drop")
parts = [c for c in melodic if c not in dropped and notes[c]]
bass = min(parts, key=lambda c: avg[c]) if parts else None
order = sorted(parts, key=lambda c: (c in doubles, c != bass, -len(notes[c])))
fm, psg_parts, unused = [], [], []
fm_used = 0
for c in forced_fm:
    if c in parts:
        fm.append(c); fm_used += poly[c]
for c in forced_psg:
    if c in parts and c not in fm:
        psg_parts.append(c)
for c in order:
    if c in fm or c in psg_parts:
        continue
    if c in doubles and doubles[c][1] == 0 and doubles[c][2] == 0:
        unused.append(c); continue                 # an exact double adds nothing
    if c not in doubles and fm_used + poly[c] <= fm_capacity:
        fm.append(c); fm_used += poly[c]
    elif len(psg_parts) < 3:
        psg_parts.append(c)
    else:
        unused.append(c)
if fm_used > fm_capacity:
    sys.exit(f"--fm needs {fm_used} FM channels, only {fm_capacity}")

# FM チャンネルの割り振り（パートごとに同時発音数ぶん）
fm_voices = {}                                  # part -> [opll ch]
nextch = 0
for c in fm:
    fm_voices[c] = list(range(nextch, nextch + poly[c])); nextch += poly[c]
prog_override = {}
for item in opts.get("prog", "").split(","):
    if ":" in item:
        ch, inst = item.split(":")
        prog_override[int(ch) - 1] = int(inst)
instrument = {c: prog_override.get(c, gm_to_opll(programs.get(c, 0))) for c in fm}
user_patch = USER_PATCHES[opts.get("user", "strings")]

# ============ 音量 ============
BASE_ATTEN = int(opts.get("atten", 0))
PSG_ATTEN = int(opts.get("psg-atten", 2))
cc7 = {c: controller_track(c, 7, 100) for c in channels}
cc11 = {c: controller_track(c, 11, 127) for c in channels}
bend = {c: controller_track(c, "bend", 0) for c in channels}

def gain_db(ch, s, vel):
    def db(v):
        return 40 * math.log10(max(v, 1) / 127)
    return db(vel) + db(value_at(cc7[ch], s)) + db(value_at(cc11[ch], s))

def atten_steps(db, base):
    return max(0, min(15, base + int(round(-db / 3))))

# ============ VGM 書き出し ============
actions = []; seq = 0
def emit(sec, kind, a, b):
    global seq
    actions.append((int(round(sec * SR)), seq, kind, a, b)); seq += 1

def opll(sec, reg, val):  emit(sec, 0x51, reg, val & 0xFF)
def ay(sec, reg, val):    emit(sec, 0xA0, reg, val & 0xFF)

def opll_freq(midi):
    f = 440.0 * 2 ** ((midi - 69) / 12)
    for block in range(8):
        fnum = int(round(f * (1 << (19 - block)) * 72 / OPLL_CLOCK))
        if fnum < 512:
            return block, max(0, fnum)
    return 7, 511

def ay_period(midi):
    f = 440.0 * 2 ** ((midi - 69) / 12)
    return max(1, min(4095, int(round(AY_CLOCK / (16 * f)))))

# 初期化
for r, v in enumerate(user_patch):
    opll(0, r, v)
for ch in range(9):
    opll(0, 0x20 + ch, 0)
if rhythm:
    for r, v in ((0x16, 0x20), (0x17, 0x50), (0x18, 0xC0), (0x26, 0x05), (0x27, 0x05), (0x28, 0x01)):
        opll(0, r, v)
    opll(0, 0x0E, 0x20)
ay(0, 7, 0xB8)                                   # tones on, noise off; MSX: port B out, port A in
for r in (8, 9, 10):
    ay(0, r, 0)
INIT = len(actions)                              # the writes above come first; the song's events follow

def bent(ch, s, midi):
    return midi + value_at(bend[ch], s) / 8192 * BEND_RANGE

def bend_times(ch, start, end):
    return [t for t, _ in bend[ch][1:] if start < t < end]

# FM 旋律
for c in fm:
    voices = fm_voices[c]
    inst = instrument[c]
    busy = {v: -1.0 for v in voices}             # voice -> end time of its note
    last = {v: None for v in voices}
    for start, end, midi, vel in notes[c]:
        free = [v for v in voices if busy[v] <= start + 1e-6]
        v = free[0] if free else min(voices, key=lambda x: busy[x])
        busy[v] = end
        att = atten_steps(gain_db(c, start, vel), BASE_ATTEN)
        block, fnum = opll_freq(bent(c, start, midi))
        opll(start, 0x30 + v, (inst << 4) | att)
        opll(start, 0x20 + v, 0)                 # key off first: the note starts again
        opll(start, 0x10 + v, fnum & 0xFF)
        opll(start, 0x20 + v, 0x10 | (block << 1) | (fnum >> 8))
        for t in bend_times(c, start, end):
            block, fnum = opll_freq(bent(c, t, midi))
            opll(t, 0x10 + v, fnum & 0xFF)
            opll(t, 0x20 + v, 0x10 | (block << 1) | (fnum >> 8))
        opll(end, 0x20 + v, (block << 1) | (fnum >> 8))

# PSG（単音化）
def mono(segs):
    """notes → non-overlapping segments, the last note pressed sounding."""
    edges = sorted([(n[0], 1, n) for n in segs] + [(n[1], 0, n) for n in segs], key=lambda e: (e[0], e[1]))
    stack, out, cur = [], [], None
    for t, on, n in edges:
        if on:
            stack.append(n)
        elif n in stack:
            stack.remove(n)
        top = stack[-1] if stack else None
        if top is not cur:
            if cur is not None and t > cur_start:
                out.append((cur_start, t, cur[2], cur[3]))
            cur, cur_start = top, t
    return out

for k, c in enumerate(psg_parts):
    shift = 0
    segs = mono(notes[c])
    decay = "sustain" if programs.get(c, 0) in range(40, 56) or programs.get(c, 0) in range(88, 96) else "soft"
    for i, (start, end, midi, vel) in enumerate(segs):
        m = pv.fold_pitch(midi + shift, 36, 108)
        per = ay_period(m)
        a0 = atten_steps(gain_db(c, start, vel), BASE_ATTEN + PSG_ATTEN + (2 if c in doubles else 0))
        ay(start, 2 * k, per & 0xFF); ay(start, 2 * k + 1, per >> 8)
        ay(start, 8 + k, 15 - a0)
        for off, a in pv.decay_schedule(decay, a0, end - start):
            ay(start + off, 8 + k, 15 - min(15, a))
        nxt = segs[i + 1][0] if i + 1 < len(segs) else None
        if nxt is None or nxt > end + 1e-4:
            ay(end, 8 + k, 0)

# リズム
if rhythm:
    vols = {4: 0x36, 3: 0x37, 2: 0x38, 1: 0x38, 0: 0x37}
    level = {4: 0, 3: 0, 2: 0, 1: 0, 0: 0}       # attenuation per drum, kept for the shared registers
    for s, kind, val, c in timed:
        if c != DRUM_CH or kind != "on":
            continue
        note, vel = val
        bit = drum_bit(note)
        level[bit] = atten_steps(gain_db(c, s, vel), BASE_ATTEN + 1)
        opll(s, 0x36, level[4])
        opll(s, 0x37, (level[0] << 4) | level[3])
        opll(s, 0x38, (level[2] << 4) | level[1])
        opll(s, 0x0E, 0x20)
        opll(s, 0x0E, 0x20 | (1 << bit))

body = bytearray()
def wait(samples):
    while samples > 0:
        n = min(samples, 0xFFFF)
        body.extend((0x61, n & 0xFF, n >> 8)); samples -= n

# 書き出し（初期化、ループ点 = 初期化直後 = 曲頭、曲のイベントは曲頭の無音を削って最初のイベントを 0 に寄せる）
for _, _, kind, a, b in actions[:INIT]:
    body.extend((kind, a, b))
loop_pos = len(body)
events = sorted(actions[INIT:], key=lambda a: (a[0], a[1]))
t0 = events[0][0] if events and "keep-lead-in" not in opts else 0
cur = 0
for samp, _, kind, a, b in events:
    samp -= t0
    if samp > cur:
        wait(samp - cur); cur = samp
    body.extend((kind, a, b))
total_samples = cur
body.append(0x66)

def gd3_text(text): return text.encode("utf-16le") + b"\x00\x00"
fields = [os.path.splitext(os.path.basename(MID))[0], "", "", "", "MSX", "MSX", "", "", "", "genopll.py", ""]
payload = b"".join(gd3_text(f) for f in fields)
gd3 = b"Gd3 " + struct.pack("<II", 0x00000100, len(payload)) + payload

DATA_OFF = 0x100
hdr = bytearray(DATA_OFF)
hdr[0:4] = b"Vgm "
gd3_pos = DATA_OFF + len(body)
struct.pack_into("<I", hdr, 0x04, gd3_pos + len(gd3) - 4)
struct.pack_into("<I", hdr, 0x08, 0x00000171)
struct.pack_into("<I", hdr, 0x10, OPLL_CLOCK)       # YM2413
struct.pack_into("<I", hdr, 0x14, gd3_pos - 0x14)
struct.pack_into("<I", hdr, 0x18, total_samples)
struct.pack_into("<I", hdr, 0x1C, DATA_OFF + loop_pos - 0x1C)
struct.pack_into("<I", hdr, 0x20, total_samples - 0)
struct.pack_into("<I", hdr, 0x24, 60)
struct.pack_into("<I", hdr, 0x34, DATA_OFF - 0x34)
struct.pack_into("<I", hdr, 0x74, AY_CLOCK)          # AY8910
hdr[0x78] = 0x00                                     # AY8910
hdr[0x79] = 0x01                                     # legacy output
open(OUT, "wb").write(bytes(hdr) + bytes(body) + gd3)

def names(chs):
    return ",".join(f"ch{c + 1}" for c in chs) or "-"
print(f"{OUT}: dur={total_samples / SR:.1f}s bytes={len(hdr) + len(body) + len(gd3)} rhythm={'on' if rhythm else 'off'}")
print("  fm: " + ", ".join(f"ch{c + 1}(prog {programs.get(c, 0)}→{instrument[c]}, {len(fm_voices[c])}v)" for c in fm))
print(f"  psg: {names(psg_parts)}  unused: {names(unused)}  doubles: "
      + ", ".join(f"ch{b + 1}=ch{a + 1}{d:+d}" + (f" {t} ticks later" if t else "")
                  for b, (a, d, t) in doubles.items()))
