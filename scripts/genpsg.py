#!/usr/bin/env python3
"""MIDI → SN76489(PSG) のみの VGM を生成する（Game Gear 向け）。

メガドライブ／ゲームギアの PSG は同じ SN76489（矩形3ch + ノイズ1ch、クロック 3579545Hz）なので、
ここで作る PSG 専用 VGM はそのまま GG で鳴り、本リポジトリの XGM プレイヤー（MD）でも試聴できる。

FM(YM2612) も PCM も一切使わない（VGM ヘッダの YM2612 クロックは 0）。各 MIDI チャンネルを
矩形3ch(tone0/tone1/tone2)とノイズ1ch(noise)へ手動マップする。割り当てとボイス指定は
コマンドライン引数から渡す。指定が無ければ音符数・音域から自動選定する。

PSG の制約への対応:
  - 各 tone は単音。和音チャンネルは「最後に押した音」優先で単音化（held スタック）する。
  - PSG は低音が出ない（周期 1023 ＝ 約109Hz ＝ MIDI45 付近が下限）。範囲外の音は自動でオクターブ
    折り返し（floor 未満は上げ、ceil 超は下げ）。手動で oct+N / oct-N も指定可。
  - PSG はエンベロープを持たないので、ソフトでボリュームを段階制御して音色感（decay）を作る:
      pluck   … 速い減衰（撥弦/エレピ/ベースの粒立ち）
      soft    … ゆるい減衰（既定）
      sustain … 減衰させず note-off まで保持（パッド/持続ベース）
  - ノイズは drums（ch10）を kick/snare/hat に振り分けて短く鳴らす。

使い方:
  genpsg.py IN.mid OUT.vgm [--tone0=SPEC] [--tone1=SPEC] [--tone2=SPEC] [--noise=drums]
                           [--floor=N] [--ceil=N]
    SPEC = <midi_ch(1始まり)>[:decay=pluck|soft|sustain][:oct=±N][:vib][:atten=N]
    引数省略時は自動選定（bass + 音符数上位2）。
"""
import math, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psg_voice as pv

PSG_CLOCK = pv.PSG_CLOCK
SR = 44100
DRUM_CH = 9                 # MIDI ch10（0始まり 9）
PITCH_FLOOR = pv.PITCH_FLOOR  # PSG 下限の目安（A2≒110Hz）。これ未満はオクターブ上げ。
PITCH_CEIL = pv.PITCH_CEIL    # これ超はオクターブ下げ（極端な高音の暴れ防止）。
LOOP_TAIL_FADE_SEC = 12.0   # 末尾の CC7/11 フェードは無視（XGM 側でループするため）

argv = [a for a in sys.argv[1:] if not a.startswith("--")]
opts = {a.split("=", 1)[0][2:]: (a.split("=", 1)[1] if "=" in a else "")
        for a in sys.argv[1:] if a.startswith("--")}
if len(argv) < 2:
    sys.exit("usage: genpsg.py IN.mid OUT.vgm [--tone0=SPEC] [--tone1=SPEC] [--tone2=SPEC] [--noise=drums]")
MID, OUT = argv[0], argv[1]
PITCH_FLOOR = int(opts.get("floor", PITCH_FLOOR))
PITCH_CEIL = int(opts.get("ceil", PITCH_CEIL))

# ============ MIDI 解析（genvgm.py と同じ最小パーサ） ============
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
                ev.append((tick, "tempo", (md[0] << 16) | (md[1] << 8) | md[2], 0))
        elif status in (0xF0, 0xF7):
            sl = 0
            while True:
                c = buf[i]; i += 1; sl = (sl << 7) | (c & 0x7F)
                if not (c & 0x80): break
            i += sl
        else:
            hi = status & 0xF0; chn = status & 0x0F
            if hi == 0xC0:
                ev.append((tick, "prog", buf[i], chn)); i += 1
            elif hi == 0xD0:
                i += 1
            elif hi in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                a = buf[i]; b = buf[i+1]; i += 2
                if hi == 0x90 and b > 0: ev.append((tick, "on", (a, b), chn))
                elif hi == 0x80 or (hi == 0x90 and b == 0): ev.append((tick, "off", (a, 0), chn))
    return ev

events = []
for t in read_tracks(data):
    events += parse_track(t)
events.sort(key=lambda e: e[0])

timed = []                                    # (sec, kind, note, chan, vel)
prog = {}; notecnt = {}; pitchsum = {}
cur_tempo = 500000; last_tick = 0; sec = 0.0
last_note_sec = 0.0
for tick, kind, a, c in events:
    sec += (tick - last_tick) * (cur_tempo / 1e6) / div
    last_tick = tick
    if kind == "tempo":   cur_tempo = a
    elif kind == "prog":  prog.setdefault(c, a)
    else:
        note, vel = a
        timed.append((sec, kind, note, c, vel))
        if kind == "on":
            last_note_sec = max(last_note_sec, sec)
            notecnt[c] = notecnt.get(c, 0) + 1
            pitchsum[c] = pitchsum.get(c, 0) + note

mel = [c for c in notecnt if c != DRUM_CH]
avgp = {c: pitchsum[c] / notecnt[c] for c in mel}

# ============ チャンネル割り当て ============
def parse_spec(spec):
    """'<ch[+ch...]>:decay=pluck:oct=+1:vib:atten=2' -> (midi_chs, cfg)
    ch を '+' で複数指定すると、それらを 1 本の PSG 矩形へマージ（共有）する。メロディが
    複数パートに分かれて受け渡される曲で、片方が休んでも無音にならないようにするため。"""
    parts = spec.split(":")
    midi_chs = [int(x) - 1 for x in parts[0].split("+")]   # 1始まり -> 0始まり（複数可）
    cfg = {"decay": "soft", "oct": 0, "vib": False, "atten": 0}
    for p in parts[1:]:
        if p == "vib":
            cfg["vib"] = True
        elif p.startswith("decay="):
            cfg["decay"] = p.split("=", 1)[1]
        elif p.startswith("oct="):
            cfg["oct"] = int(p.split("=", 1)[1])
        elif p.startswith("atten="):
            cfg["atten"] = int(p.split("=", 1)[1])
    return midi_chs, cfg

tone_specs = []                                 # [(pc, [midi_ch...], cfg), ...]  pc=0..2
for pc in range(3):
    s = opts.get(f"tone{pc}")
    if s:
        chs, cfg = parse_spec(s)
        tone_specs.append((pc, chs, cfg))
noise_on = opts.get("noise", "") == "drums" or (DRUM_CH in notecnt and "noise" not in opts and not tone_specs)

if not tone_specs:
    # 自動選定: bass(最低音域) + 音符数上位。tone0=最高音(リード)…tone2=最低音(ベース)。
    if mel:
        bass_ch = min(mel, key=lambda c: avgp[c])
        rest = sorted([c for c in mel if c != bass_ch], key=lambda c: -notecnt[c])
        chosen = ([bass_ch] + rest)[:3]
        chosen.sort(key=lambda c: -avgp[c])     # 高音→低音
        defaults = ["soft", "soft", "sustain"]
        for pc, ch in enumerate(chosen):
            tone_specs.append((pc, [ch], {"decay": defaults[pc], "oct": 0, "vib": False, "atten": 0}))
    noise_on = DRUM_CH in notecnt

# ============ 単音化 ============
def reduce_mono(chans):
    """chans（1 つ以上の MIDI ch）の on/off を 1 本の単音セグメント列に畳む（連続・無重複）。
    単一 ch は「最後に押した音」優先（従来どおり＝既存出力を変えない）。複数 ch をマージする
    ときは「最高音」優先＝メロディの上声を残しつつ、片方が休んでももう片方で繋いで無音を防ぐ。"""
    multi = len(chans) > 1
    evs = sorted([(s, k, n, v) for (s, k, n, c, v) in timed if c in chans and k in ("on", "off")],
                 key=lambda e: (e[0], 0 if e[1] == "off" else 1))
    stack = []                                  # [(midi, vel)]
    segs = []
    cur = None                                  # (start, midi, vel)
    def sounding():
        if not stack:
            return None
        return max(stack, key=lambda x: x[0]) if multi else stack[-1]  # 複数=最高音 / 単一=最後
    for s, k, n, v in evs:
        if k == "on":
            stack.append((n, v))
        else:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == n:
                    del stack[i]; break
        t = sounding()
        want = (t[0], t[1]) if t else None
        now = (want[0] if want else None)
        playing = (cur[1] if cur else None)
        if now != playing:
            if cur is not None and s > cur[0]:
                segs.append((cur[0], s, cur[1], cur[2]))
            cur = (s, want[0], want[1]) if want else None
    return segs

def fold_pitch(m):
    return pv.fold_pitch(m, PITCH_FLOOR, PITCH_CEIL)

# ============ VGM 生成 ============
body = bytearray()
def psg(b): body.extend((0x50, b & 0xFF))
def wait(samples):
    while samples > 0:
        n = min(samples, 65535)
        body.extend((0x61, n & 0xFF, (n >> 8) & 0xFF)); samples -= n

def u32(v):
    return bytes((v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF))

def midi_freq(m): return 440.0 * (2.0 ** ((m - 69) / 12.0))
def psg_period(midi): return max(1, min(1023, int(round(PSG_CLOCK / (32 * midi_freq(midi))))))

def vel_atten(vel, base):
    # PSG 音量レジスタ: 0=最大, 15=無音。ベロシティが小さいほど減衰を増やす。
    return max(0, min(15, base + int(round((127 - vel) * 6 / 127))))

# ---- アクション列（時刻順に解決） ----
actions = []; seq = 0
def emit(sec, fn):
    global seq
    actions.append((int(round(sec * SR)), seq, fn)); seq += 1

def set_pitch(pc, midi):
    per = psg_period(midi)
    psg(0x80 | (pc << 5) | (per & 0x0F)); psg((per >> 4) & 0x3F)
def set_vol(pc, a):  psg(0x80 | (pc << 5) | 0x10 | (a & 0x0F))
def tone_off(pc):    psg(0x80 | (pc << 5) | 0x10 | 0x0F)

def emit_tone_segment(pc, start, end, midi, vel, cfg):
    midi = fold_pitch(midi + 12 * cfg["oct"])
    dur = end - start
    a0 = vel_atten(vel, 2 + cfg["atten"])
    # 立ち上がり: 周期＋初期音量
    def on(pc=pc, midi=midi, a0=a0):
        set_pitch(pc, midi); set_vol(pc, a0)
    emit(start, on)
    # ビブラート（ソフト・ピッチ揺らし）。set_pitch は float midi を受ける。
    if cfg["vib"]:
        for off, m2 in pv.vibrato_schedule(midi, dur, phase=pc * 0.7):
            emit(start + off, lambda pc=pc, m2=m2: set_pitch(pc, m2))
    # 音量エンベロープ（decay スタイル別）。pv.decay_schedule が dur 内のステップを返す。
    for off, a in pv.decay_schedule(cfg["decay"], a0, dur):
        emit(start + off, lambda pc=pc, a=a: set_vol(pc, a))

def noise_hit(note):
    if note <= 37:   rate, vol = 0b10, 0x07       # キック
    elif note >= 48: rate, vol = 0b00, 0x09       # ハイハット/シンバル
    else:            rate, vol = 0b01, 0x07       # スネア
    def on():
        psg(0xE0 | (1 << 2) | rate); psg(0xF0 | vol)
    return on, vol

# 初期化: 全 PSG ch 消音
for pc in range(4):
    psg(0x80 | (pc << 5) | 0x10 | 0x0F)

# tone セグメント
used_tone = []
for pc, chs, cfg in tone_specs:
    chs = [c for c in chs if c in notecnt]
    if not chs:
        continue
    used_tone.append((pc, chs, cfg))
    segs = reduce_mono(chs)
    for k, (start, end, midi, vel) in enumerate(segs):
        emit_tone_segment(pc, start, end, midi, vel, cfg)
        nxt = segs[k + 1][0] if k + 1 < len(segs) else None
        if nxt is None or nxt > end + 1e-4:        # 後続が即接続でなければ消音
            emit(end, lambda pc=pc: tone_off(pc))

# noise（ドラム）
if noise_on:
    for s, kind, note, c, vel in timed:
        if c == DRUM_CH and kind == "on":
            on, v0 = noise_hit(note)
            emit(s, on)
            emit(s + 0.05, lambda v=min(15, v0 + 5): psg(0xF0 | v))
            emit(s + 0.12, lambda: psg(0xF0 | 0x0F))

# 書き出し（ループ点 = 初期化直後＝曲頭）
loop_pos = len(body)
actions.sort(key=lambda a: (a[0], a[1]))
t0 = actions[0][0] if actions else 0
cur = 0
for samp, _, fn in actions:
    samp -= t0
    if samp > cur:
        wait(samp - cur); cur = samp
    fn()
total_samples = cur; loop_samples = total_samples
body.append(0x66)

# ============ VGM ヘッダ（PSG のみ、YM2612 クロック=0） ============
def gd3_text(text): return text.encode("utf-16le") + b"\x00\x00"
def make_gd3():
    # トラック名の拡張子 .psg で SN76489 のみ（GG）を示す
    track_name = os.path.splitext(os.path.basename(MID))[0] + ".psg"
    fields = [track_name, "", "Kamaitachi no yoru (GG PSG)", "",
              "Game Gear", "Game Gear", "akiyan feat inu", "",
              "", "genpsg.py", ""]
    payload = b"".join(gd3_text(f) for f in fields)
    return b"Gd3 " + struct.pack("<II", 0x00000100, len(payload)) + payload

DATA_OFF = 0x40
gd3 = make_gd3()
hdr = bytearray(DATA_OFF)
hdr[0x00:0x04] = b"Vgm "
gd3_pos = DATA_OFF + len(body)
total_len = gd3_pos + len(gd3)
struct.pack_into("<I", hdr, 0x04, total_len - 4)
struct.pack_into("<I", hdr, 0x08, 0x00000150)
struct.pack_into("<I", hdr, 0x0C, PSG_CLOCK)        # SN76489 クロック（MD/GG 共通）
struct.pack_into("<I", hdr, 0x18, total_samples)
struct.pack_into("<I", hdr, 0x1C, (DATA_OFF + loop_pos) - 0x1C)
struct.pack_into("<I", hdr, 0x20, loop_samples)
struct.pack_into("<I", hdr, 0x24, 60)
struct.pack_into("<H", hdr, 0x28, 0x0009)           # SN76489 feedback
hdr[0x2A] = 16                                       # SN76489 shift register width
struct.pack_into("<I", hdr, 0x2C, 0)                # YM2612 クロック = 0（FM 不使用）
struct.pack_into("<I", hdr, 0x14, gd3_pos - 0x14)
struct.pack_into("<I", hdr, 0x34, DATA_OFF - 0x34)

open(OUT, "wb").write(bytes(hdr) + bytes(body) + gd3)
print(f"{OUT}: dur={total_samples/SR:.1f}s bytes={total_len}")
print(f"  tone: " + ", ".join(f"pc{pc}=ch{'+'.join(str(c+1) for c in chs)}({cfg['decay']}"
                               f"{'+vib' if cfg['vib'] else ''}{',oct%+d'%cfg['oct'] if cfg['oct'] else ''})"
                               for pc, chs, cfg in used_tone))
print(f"  noise: {'drums(ch10)' if noise_on else 'none'}")
