#!/usr/bin/env python3
"""マルチ音色 MIDI → YM2612(FM) + SN76489(PSG) を鳴らす VGM を生成する。

SGDK の rescomp が `XGM name file.vgm` で VGM→XGM へ変換し、XGM ドライバ（FM+PSG）で
再生できる。本スクリプトは標準ライブラリだけで MIDI を解析し、各 MIDI チャンネルを
GM プログラム/音域で分類して、FM6ch と PSG(矩形3ch+ノイズ1ch)へ振り分ける。

  エンジン割り当て（パートごとに音色を固定＝一貫した音色）:
    ドラム(ch10)                 → PSG ノイズ（音程→周期、減衰付き）
    ベース(最低音域)             → FM（基音+2倍音のベース）
    撥弦(GM24-31) or リード筆頭   → PSG 矩形（明るい/プラック）。撥弦が無ければ最高音域の
                                   リード系を PSG に回し、PSG を活用しつつ FM の負荷も下げる
    その他                       → FM。GM プログラムで音色パッチを選ぶ
                                   （ブラス/リード/弦/パイプ＝それぞれ別倍音構成）
  和音は各プール内でボイス割当（空き無ければ最古を奪う）。ループ点は曲頭。

  使い方: python3 scripts/genvgm.py IN.mid OUT.vgm [--no-psg] [--pcm-drums] [--fm6] [--sf2=PATH] [--atten=N]
    --no-psg : PSG を一切使わず全パートを FM6ch に割り当てる（ドラムは省略）。
    --pcm-drums: ch10 ドラムを FluidSynth+SoundFont 由来の VGM stream PCM として出力する
                 （XGM2 変換時に PCM 化）。
    FM は SFX/PCM 余地として常に 1ch 空けるため最大5ch。
    --fm6: 比較/選択用に FM6 まで BGM に使う。ドラムは PSG ノイズにするため --pcm-drums と併用しない。
    --sf2=PATH : --pcm-drums で使う SoundFont（既定: $SOUNDFONT または default-GM.sf2）。
    --atten=N: FM 可聴オペレータの TL に N を加算して音量を下げる（TL は大きいほど小音量、
               1 ステップ約0.75dB。例: 6≒-4.5dB, 8≒-6dB）。
    --pcm-shot=auto|ch,ch...|auto+ch...: 短い装飾音パートを自動/手動選択し、空きPCM chへ薄く重ねる。
                                         chはMIDIの1始まり。
"""
import math, os, shutil, struct, subprocess, sys, tempfile, wave
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psg_voice as pv     # PSG の表情（decay/ビブラート/音域）は genpsg.py と共有

argv = [a for a in sys.argv[1:] if not a.startswith("--")]
NOPSG = "--no-psg" in sys.argv
PCM_DRUMS = "--pcm-drums" in sys.argv
USE_FM6 = "--fm6" in sys.argv
BELL_PSG = "--bell-psg" in sys.argv   # bell(オルゴール)主旋律に PSG 矩形を同音ユニゾンで重ねる
ATTEN = 0
PCM_SHOT_SPEC = ""
SF2 = os.environ.get("SOUNDFONT", "/usr/share/sounds/sf2/default-GM.sf2")
for a in sys.argv:
    if a.startswith("--atten="):
        ATTEN = int(a.split("=", 1)[1])
    elif a.startswith("--sf2="):
        SF2 = a.split("=", 1)[1]
    elif a.startswith("--pcm-shot="):
        PCM_SHOT_SPEC = a.split("=", 1)[1].strip().lower() or "auto"
if len(argv) < 2:
    sys.exit("usage: genvgm.py IN.mid OUT.vgm [--no-psg] [--pcm-drums] [--fm6] [--bell-psg] [--pcm-shot=auto|midi_ch,midi_ch...|auto+midi_ch...] [--sf2=PATH] [--atten=N]")
if PCM_DRUMS and USE_FM6:
    sys.exit("--fm6 cannot be combined with --pcm-drums; FM6 shares YM2612 ch6 with DAC/PCM")
MID, OUT = argv[0], argv[1]
SONG = os.path.splitext(os.path.basename(MID))[0]
YM_CLOCK = 7670453
PSG_CLOCK = 3579545
SR = 44100
DRUM_CH = 9
PCM_RATE = 13300
PCM_DRUM_GAIN = 0.65
PCM_SHOT_GAIN = 0.42
PCM_SHOT_MAX_SEC = 0.42
HAT_NOTES = {42, 44, 46}
HAT_CLOSED_MAX_SEC = 0.075
HAT_OPEN_MAX_SEC = 0.120
PSG_ACCOMP_ATTEN = 1      # SN76489 は 1 step 約2dB。伴奏寄りの矩形パートだけ少し奥へ下げる。
BASS_BOOST = 3            # bass はキャリア TL を BASS_BOOST 下げて持ち上げる（≒2.25dB。低音を聞こえやすく）。
PITCH_BEND_RANGE = 2.0    # MIDI 標準寄りに ±2 semitone として扱う。
LFO_FREQ = 2              # YM2612 LFO 周波数インデックス（2 ≒ 6.0Hz）。FMS>0 の patch にビブラート。
MOD_DEPTH_SEMIS = 0.20
MOD_RATE_HZ = 5.5
LOOP_TAIL_FADE_SEC = 12.0

# ============ MIDI 解析 ============
data = open(MID, "rb").read()
assert data[:4] == b"MThd", "not a MIDI file"
fmt, ntrk, div = struct.unpack(">HHH", data[8:14])
assert div & 0x8000 == 0, "SMPTE division not supported"
VGM_AUTHOR = os.environ.get("VGM_AUTHOR", "midi2vgm")
VGM_GAME = os.environ.get("VGM_GAME", "")

def gd3_text(text):
    return text.encode("utf-16le") + b"\x00\x00"

def make_gd3():
    # トラック名の拡張子で音源方式を示す: FM6ch=.fm6 / それ以外(FM最大5ch)=.fm5
    track_name = os.path.splitext(os.path.basename(MID))[0] + (".fm6" if USE_FM6 else ".fm5")
    fields = [
        track_name, "",                            # Track name EN / JP
        VGM_GAME, "",                              # Game name EN / JP
        "Mega Drive", "Mega Drive",                # System name EN / JP
        VGM_AUTHOR, "",
        "", "genvgm.py", "",                      # Date / VGM creator / Notes
    ]
    payload = b"".join(gd3_text(field) for field in fields)
    return b"Gd3 " + struct.pack("<II", 0x00000100, len(payload)) + payload

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
                elif hi == 0xB0 and a in (1, 7, 11): ev.append((tick, "cc", (a, b), chn))
                elif hi == 0xE0: ev.append((tick, "pb", (((b << 7) | a) - 8192, 0), chn))
    return ev

events = []
for t in read_tracks(data):
    events += parse_track(t)
events.sort(key=lambda e: e[0])

timed = []                                    # (sec, kind, note/cc, chan, velocity/value)
prog = {}; notecnt = {}; pitchsum = {}
velsum = {}
cc_count = {1: 0, 7: 0, 11: 0}
pb_count = 0
chan_cc_count = {1: {}, 7: {}, 11: {}}
chan_pb_count = {}
last_note_sec = 0.0
note_first_sec = {}
note_last_sec = {}
note_dur_sum = {}
active_notes = {}
cur_tempo = 500000; last_tick = 0; sec = 0.0
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
            note_first_sec.setdefault(c, sec)
            note_last_sec[c] = sec
            active_notes.setdefault((c, note), []).append(sec)
            notecnt[c] = notecnt.get(c, 0) + 1
            pitchsum[c] = pitchsum.get(c, 0) + note
            velsum[c] = velsum.get(c, 0) + vel
        elif kind == "off":
            starts = active_notes.get((c, note))
            if starts:
                note_dur_sum[c] = note_dur_sum.get(c, 0.0) + max(0.0, sec - starts.pop(0))
        elif kind == "cc":
            cc_count[note] = cc_count.get(note, 0) + 1
            chan_cc_count.setdefault(note, {})[c] = chan_cc_count.setdefault(note, {}).get(c, 0) + 1
        elif kind == "pb":
            pb_count += 1
            chan_pb_count[c] = chan_pb_count.get(c, 0) + 1

mel = [c for c in notecnt if c != DRUM_CH]
avgp = {c: pitchsum[c] / notecnt[c] for c in mel}
avgv = {c: velsum.get(c, 80) / notecnt[c] for c in mel}
avgdur = {c: note_dur_sum.get(c, 0.0) / notecnt[c] for c in mel}
duty = {c: note_dur_sum.get(c, 0.0) / max(0.001, note_last_sec.get(c, 0.0) - note_first_sec.get(c, 0.0)) for c in mel}
note_on_seq = {
    c: [(sec, note, vel) for sec, kind, note, chan, vel in timed if chan == c and kind == "on"]
    for c in mel
}
uniq_notes = {c: len({note for _sec, note, _vel in note_on_seq.get(c, [])}) for c in mel}
def parse_pcm_shot_spec(spec):
    if not spec:
        return False, []
    use_auto = False
    result = []
    for part in spec.replace("+", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if part == "auto":
            use_auto = True
            continue
        try:
            ch = int(part)
        except ValueError:
            raise SystemExit(f"invalid --pcm-shot channel: {part}")
        result.append(ch - 1 if 1 <= ch <= 16 else ch)
    return use_auto, result

def pcm_shot_score(c):
    p = prog.get(c, 0)
    score = 0
    if 8 <= p <= 15:        # chromatic percussion: celesta/glockenspiel/musicbox/vibes...
        score += 80
    elif 112 <= p <= 119:   # GM sound effects
        score += 40
    else:
        score -= 80
    if avgdur.get(c, 9.0) <= 0.14:
        score += 35
    elif avgdur.get(c, 9.0) <= 0.30:
        score += 15
    else:
        score -= 60
    if uniq_notes.get(c, 99) <= 2:
        score += 35
    elif uniq_notes.get(c, 99) <= 4:
        score += 20
    elif uniq_notes.get(c, 99) <= 8:
        score += 5
    else:
        score -= 35
    if notecnt.get(c, 0) > 500:
        score -= 45
    if duty.get(c, 1.0) > 0.35:
        score -= 35
    return score

auto_pcm_shot, manual_pcm_shot_chs = parse_pcm_shot_spec(PCM_SHOT_SPEC)
if not PCM_SHOT_SPEC:
    pcm_shot_chs = []
else:
    pcm_shot_chs = [c for c in manual_pcm_shot_chs if c in mel and c != DRUM_CH]
    if auto_pcm_shot:
        pcm_shot_chs.extend([
            c for c in sorted(mel, key=lambda c: (-pcm_shot_score(c), notecnt.get(c, 0), c))
            if pcm_shot_score(c) >= 55
        ][:2])
    pcm_shot_chs = list(dict.fromkeys(pcm_shot_chs))

# ============ FM パッチ ============
# slot 0..3 = S1,S3,S2,S4。alg7は4キャリア並列、alg4/5は一部モジュレータを使って輪郭を作る。
# YM2612 拡張機能を活用: op ごとに "dt"(DT1 デチューン 0-7。1..3=+/5..7=-)・"rs"(レート
# スケーリング 0-3。高音ほど EG が速い＝実楽器的)。patch ごとに "fms"(LFO ビブラート量 0-7)。
# 持続音(笛/弦/リード/ブラス)は並行キャリアを ± デチューンして厚み/コーラスを出し、軽い FMS で
# 表情を付ける。打弦/打鍵(bell/piano/pluck)は rs を上げ高音の減衰を速める。bass は素のまま(タイト)。
PATCH = {
    "flute": {
        "alg": 7, "fb": 0, "fms": 2, "op": [
            {"mul": 1, "tl": 0x7F, "ar": 0x0C, "d1r": 0x00, "d2r": 0x00, "slrr": 0x0F},
            {"mul": 2, "tl": 0x34, "ar": 0x12, "d1r": 0x03, "d2r": 0x01, "slrr": 0xA6, "dt": 1, "rs": 1},
            {"mul": 3, "tl": 0x42, "ar": 0x10, "d1r": 0x02, "d2r": 0x01, "slrr": 0xA6, "dt": 5, "rs": 1},
            {"mul": 1, "tl": 0x08, "ar": 0x12, "d1r": 0x03, "d2r": 0x01, "slrr": 0x96, "rs": 1},
        ]},
    "clar": {
        "alg": 4, "fb": 2, "fms": 1, "op": [
            {"mul": 2, "tl": 0x24, "ar": 0x1A, "d1r": 0x06, "d2r": 0x02, "slrr": 0x84, "dt": 1},
            {"mul": 1, "tl": 0x0A, "ar": 0x1B, "d1r": 0x06, "d2r": 0x02, "slrr": 0x74, "rs": 1},
            {"mul": 3, "tl": 0x30, "ar": 0x18, "d1r": 0x05, "d2r": 0x02, "slrr": 0x84, "dt": 5},
            {"mul": 1, "tl": 0x12, "ar": 0x1A, "d1r": 0x05, "d2r": 0x02, "slrr": 0x74, "rs": 1},
        ]},
    "brass": {
        "alg": 5, "fb": 4, "fms": 1, "op": [
            {"mul": 1, "tl": 0x18, "ar": 0x1F, "d1r": 0x0B, "d2r": 0x03, "slrr": 0x65},
            {"mul": 2, "tl": 0x10, "ar": 0x1F, "d1r": 0x0A, "d2r": 0x03, "slrr": 0x65, "dt": 1, "rs": 1},
            {"mul": 3, "tl": 0x24, "ar": 0x1D, "d1r": 0x08, "d2r": 0x02, "slrr": 0x75, "dt": 5, "rs": 1},
            {"mul": 1, "tl": 0x08, "ar": 0x1F, "d1r": 0x09, "d2r": 0x03, "slrr": 0x65, "dt": 1, "rs": 1},
        ]},
    "softlead": {
        "alg": 7, "fb": 1, "fms": 3, "op": [
            {"mul": 1, "tl": 0x7F, "ar": 0x0C, "d1r": 0x00, "d2r": 0x00, "slrr": 0x0F},
            {"mul": 2, "tl": 0x34, "ar": 0x0F, "d1r": 0x01, "d2r": 0x01, "slrr": 0xB7, "dt": 1},
            {"mul": 3, "tl": 0x4A, "ar": 0x0D, "d1r": 0x01, "d2r": 0x01, "slrr": 0xB7, "dt": 5},
            {"mul": 1, "tl": 0x10, "ar": 0x0F, "d1r": 0x01, "d2r": 0x01, "slrr": 0xB7},
        ]},
    "strings": {
        "alg": 7, "fb": 1, "fms": 1, "op": [
            {"mul": 1, "tl": 0x18, "ar": 0x0D, "d1r": 0x03, "d2r": 0x02, "slrr": 0xA7, "dt": 1},
            {"mul": 2, "tl": 0x22, "ar": 0x0C, "d1r": 0x03, "d2r": 0x02, "slrr": 0xA7, "dt": 5},
            {"mul": 4, "tl": 0x34, "ar": 0x0A, "d1r": 0x02, "d2r": 0x02, "slrr": 0xB7, "dt": 2},
            {"mul": 1, "tl": 0x0C, "ar": 0x0D, "d1r": 0x03, "d2r": 0x02, "slrr": 0xA7, "dt": 6},
        ]},
    "bass": {
        "alg": 4, "fb": 3, "op": [
            {"mul": 1, "tl": 0x12, "ar": 0x1F, "d1r": 0x0E, "d2r": 0x04, "slrr": 0x54},
            {"mul": 1, "tl": 0x04, "ar": 0x1F, "d1r": 0x0E, "d2r": 0x04, "slrr": 0x54},
            {"mul": 2, "tl": 0x20, "ar": 0x1F, "d1r": 0x0C, "d2r": 0x03, "slrr": 0x64},
            {"mul": 1, "tl": 0x08, "ar": 0x1F, "d1r": 0x0D, "d2r": 0x04, "slrr": 0x54},
        ]},
    # chromatic percussion（オルゴール/グロッケン/ヴィブラフォン等, GM prog 8-15）用。
    # 2x 2-op（alg4）。倍音 3x/4x のモジュレータで金属的な明るさを出し、アタック即時・
    # 減衰早めの打鍵エンベロープでチン…と減衰する。op 順は [op1(mod),op3(mod),op2(car),op4(car)]。
    # オルゴール/鐘。明るい倍音モジュレータ(7x)を速く減衰させ「硬質な明るいアタック → 純音の余韻」に。
    # キャリアは中程度の減衰で“鳴って減衰するが即消えない”ようにする（rs なし＝高音で速くなりすぎない）。
    "bell": {
        "alg": 4, "fb": 5, "op": [
            {"mul": 7, "tl": 0x2C, "ar": 0x1F, "d1r": 0x14, "d2r": 0x08, "slrr": 0xF8, "dt": 1},
            {"mul": 4, "tl": 0x36, "ar": 0x1F, "d1r": 0x14, "d2r": 0x08, "slrr": 0xF8, "dt": 5},
            {"mul": 1, "tl": 0x06, "ar": 0x1F, "d1r": 0x0C, "d2r": 0x04, "slrr": 0x96},
            {"mul": 2, "tl": 0x18, "ar": 0x1F, "d1r": 0x0C, "d2r": 0x04, "slrr": 0x96},
        ]},
    # ピアノ/エレピ（GM prog 0-7）。DX 風エレピ: 同倍音モジュレータで温かみ＋14x モジュレータで
    # アタックの tine ピン、中程度の減衰。打鍵で減衰しつつ少し伸びる。op 順 [op1,op3,op2,op4]。
    # rs=1 で高音ほど速い減衰。
    "piano": {
        "alg": 4, "fb": 4, "op": [
            {"mul": 1,  "tl": 0x2C, "ar": 0x1F, "d1r": 0x10, "d2r": 0x05, "slrr": 0xC7, "dt": 1},
            {"mul": 14, "tl": 0x55, "ar": 0x1F, "d1r": 0x18, "d2r": 0x09, "slrr": 0xF8, "rs": 1},
            {"mul": 1,  "tl": 0x05, "ar": 0x1F, "d1r": 0x09, "d2r": 0x03, "slrr": 0x66, "rs": 1},
            {"mul": 1,  "tl": 0x20, "ar": 0x1F, "d1r": 0x0C, "d2r": 0x04, "slrr": 0x96, "rs": 1},
        ]},
    # ギター/撥弦（GM prog 24-31）。明るい倍音（3x）＋速い減衰の撥弦。pluck。op 順 [op1,op3,op2,op4]。
    # rs=2 で高音ほど速い減衰。
    "pluck": {
        "alg": 4, "fb": 4, "op": [
            {"mul": 1, "tl": 0x2A, "ar": 0x1F, "d1r": 0x12, "d2r": 0x07, "slrr": 0xC8, "dt": 1},
            {"mul": 3, "tl": 0x3C, "ar": 0x1F, "d1r": 0x14, "d2r": 0x09, "slrr": 0xD8, "dt": 5, "rs": 2},
            {"mul": 1, "tl": 0x06, "ar": 0x1F, "d1r": 0x0E, "d2r": 0x06, "slrr": 0xA7, "rs": 2},
            {"mul": 2, "tl": 0x1C, "ar": 0x1F, "d1r": 0x0E, "d2r": 0x06, "slrr": 0xA7, "rs": 2},
        ]},
}
def fm_patch_for(p):
    if 56 <= p <= 63: return "brass"
    if 64 <= p <= 71: return "clar"
    if 72 <= p <= 79: return "flute"
    if 40 <= p <= 55: return "strings"
    if 16 <= p <= 23: return "clar"
    if 8 <= p <= 15:  return "bell"     # chromatic percussion（オルゴール/グロッケン/ヴィブラフォン）
    if p <= 7:        return "piano"    # ピアノ/エレピ（GM prog 0-7）
    if 24 <= p <= 31: return "pluck"    # ギター/撥弦（GM prog 24-31）
    return "flute"

def fm_patch_for_channel(c):
    p = prog.get(c, 0)
    if 56 <= p <= 63 and avgdur.get(c, 0.0) >= 0.35 and (
        chan_cc_count.get(1, {}).get(c, 0) or chan_pb_count.get(c, 0)
    ):
        return "softlead"
    return fm_patch_for(p)

# ============ エンジン/プール割り当て ============
bass_ch = min(mel, key=lambda c: avgp[c]) if mel else None
non_bass = sorted([c for c in mel if c != bass_ch], key=lambda c: -avgp[c])  # 高音→低音

# 持続低音（パッド/ロングトーンのベース）判定: bass パッチはプラック向けの二段減衰(D2R>0)なので、
# 数十秒の超ロングトーンだと鳴り始めてすぐ減衰して土台が消える。bass チャンネルの平均ノート長が
# 閾値超なら、キャリア(S2/S4)を鳴らし切り(D2R=0/SL=0)へ差し替えて持続させる（プラック主体の曲は不変）。
SUSTAIN_BASS_SEC = 3.0
SUSTAIN_BASS = bass_ch is not None and avgdur.get(bass_ch, 0.0) >= SUSTAIN_BASS_SEC

guitar = [c for c in non_bass if 24 <= prog.get(c, 0) <= 31]
def delayed_duplicate_score(a, b):
    sa = note_on_seq.get(a, [])
    sb = note_on_seq.get(b, [])
    if len(sa) < 16 or len(sb) < 16:
        return 0.0
    ratio = min(len(sa), len(sb)) / max(len(sa), len(sb))
    if ratio < 0.75:
        return 0.0
    n = min(32, len(sa), len(sb))
    pitch_match = sum(1 for i in range(n) if sa[i][1] == sb[i][1]) / n
    delay = sb[0][0] - sa[0][0]
    if not (0.04 <= delay <= 0.18):
        return 0.0
    return pitch_match * ratio

psg_echo_chs = []
echo_main_chs = []
for a in non_bass:
    if a in psg_echo_chs or a in echo_main_chs:
        continue
    for b in non_bass:
        if a == b or b in psg_echo_chs or b in echo_main_chs:
            continue
        if prog.get(a, 0) != prog.get(b, 0):
            continue
        if note_first_sec.get(a, 0.0) > note_first_sec.get(b, 0.0):
            continue
        if abs(avgp.get(a, 0.0) - avgp.get(b, 0.0)) > 0.75:
            continue
        if delayed_duplicate_score(a, b) >= 0.70:
            echo_main_chs.append(a)
            psg_echo_chs.append(b)
            break
def psg_score(c):
    p = prog.get(c, 0)
    expressive = chan_cc_count.get(1, {}).get(c, 0) or chan_pb_count.get(c, 0)
    score = 0
    if expressive and duty.get(c, 0.0) <= 0.45:
        score += 70
    elif expressive:
        score -= 20
    if 56 <= p <= 79 and expressive and duty.get(c, 0.0) <= 0.45:
        score += 25
    elif 56 <= p <= 79:
        score -= 15
    if avgv.get(c, 127) <= 90:
        score += 15
    if avgp.get(c, 80) < 55:
        score -= 20
    if avgdur.get(c, 0.0) < 0.25:
        score += 25
    if avgdur.get(c, 0.0) > 0.55:
        score -= 5
    if avgdur.get(c, 0.0) > 0.75:
        score -= 40
    if duty.get(c, 0.0) > 0.35:
        score -= 20
    if duty.get(c, 0.0) > 0.45:
        score -= 60
    if duty.get(c, 0.0) > 0.70:
        score -= 100
    return score
if NOPSG:
    psg_chs = []                              # PSG 不使用: 全パートを FM へ
else:
    # パートが FM5ch に収まらないぶん、または平均ベロシティが小さい飾りパートを PSG へ。
    # 撥弦/ギターも専用 FM パッチ pluck を持つので FM 優先（あふれた時だけ PSG 矩形へ）。
    max_offload = min(3, max(0, len(non_bass) - 4 + len(psg_echo_chs)))
    psg_chs = psg_echo_chs[:max_offload]
    for c in sorted(non_bass, key=lambda c: (-psg_score(c), avgp.get(c, 0))):
        if len(psg_chs) >= max_offload:
            break
        if c not in psg_chs and c not in echo_main_chs and psg_score(c) >= 25:
            psg_chs.append(c)

if not NOPSG and max(0, len(non_bass) - len(psg_chs) - 6) > 0:
    # FM が極端に過密なときだけ、最も影響の少ないパートを薄く PSG へ逃がす。
    for cand in sorted(non_bass, key=lambda c: (-psg_score(c), avgp.get(c, 0))):
        if cand not in psg_chs and cand not in echo_main_chs:
            psg_chs.append(cand)
            break
fm_chs = [c for c in non_bass if c not in psg_chs]

# FM 各チャンネルにパッチ固定。bass(1)+残り5 をパッチ群へ音符数比で配分
groups = {}                                   # patch_name -> [midi channels]
for c in fm_chs:
    groups.setdefault(fm_patch_for_channel(c), []).append(c)
def alloc_group_slots(groups, total):
    """パッチグループごとのFM本数を決める。

    まず各パッチグループに1本ずつ渡し、次に複数MIDIチャンネルを含むグループの
    未カバーチャンネルを埋める。余りだけを音符数の重みで和音用に追加する。
    """
    keys = list(groups)
    if not keys or total <= 0:
        return {}
    counts = {g: 0 for g in keys}

    # 最低1本。万一グループ数がスロット数を超える場合は音符数の多いグループを優先する。
    for g in sorted(keys, key=lambda x: sum(notecnt[c] for c in groups[x]), reverse=True)[:total]:
        counts[g] = 1

    def remaining():
        return total - sum(counts.values())

    # 1チャンネルだけのグループへ余剰を与える前に、複数チャンネルグループを1ch=1FMへ近づける。
    while remaining() > 0:
        candidates = [g for g in keys if counts[g] > 0 and counts[g] < len(groups[g])]
        if not candidates:
            break
        g = max(candidates, key=lambda x: sum(notecnt[c] for c in groups[x]))
        counts[g] += 1

    # まだ余れば従来どおり音符数の多いグループへ和音用ボイスを足す。
    while remaining() > 0:
        g = max(keys, key=lambda x: sum(notecnt[c] for c in groups[x]) / max(1, counts[x]))
        counts[g] += 1

    return counts
fm_total_slots = 5
fm_slots = fm_total_slots - (1 if bass_ch is not None else 0)
gcount = alloc_group_slots(groups, fm_slots) if groups else {}

# ハードウェア FM チャンネル割付
idx = 0
FM_OF = {}                                     # patch_name -> [fm hw channels]
if bass_ch is not None:
    FM_OF["bass"] = [idx]; idx += 1
for g, cs in groups.items():
    n = gcount[g]; FM_OF[g] = list(range(idx, idx + n)); idx += n
if USE_FM6 and groups:
    def fm6_group_score(g):
        cs = groups[g]
        score = sum(notecnt[c] * (1.0 + duty.get(c, 0.0)) for c in cs)
        if any(c in echo_main_chs for c in cs):
            score -= 1000000000.0
        return score
    target = max(groups, key=fm6_group_score)
    FM_OF[target].append(5)                   # 既存5FMの後ろに低優先度の追加ボイスとして使う。
FM_PREF = {}                                  # patch_name -> {midi channel: preferred fm hw channel}
for g, cs in groups.items():
    chs = FM_OF.get(g, [])
    if len(cs) > 1 and len(chs) >= len(cs):
        FM_PREF[g] = dict(zip(cs, chs[:len(cs)]))
PSG_TONE = [0, 1, 2]

# MIDI チャンネル -> ("fm",patch) / ("psg",) / ("noise",)
route = {}
if bass_ch is not None: route[bass_ch] = ("fm", "bass")
for c in fm_chs:        route[c] = ("fm", fm_patch_for_channel(c))
for c in psg_chs:       route[c] = ("psg",)

# bell（オルゴール/鐘）の主旋律に PSG 矩形を同音ユニゾンで重ね、硬質な“ピン”でオルゴール感を足す。
# adjustments.txt で 'bell+psg' 指定の曲だけ有効（--bell-psg）。末尾の矩形 1ch をユニゾン専用に予約し、
# offload pool は残りの矩形を使う（offload が収まる場合のみ）。
bell_chs = [c for c, r in route.items() if r == ("fm", "bell")]
unison_ch = max(bell_chs, key=lambda c: notecnt.get(c, 0)) if bell_chs else None
UNISON_SQ = PSG_TONE[-1] if (BELL_PSG and unison_ch is not None and not NOPSG
                             and len(psg_chs) <= len(PSG_TONE) - 1) else None
if UNISON_SQ is None:
    unison_ch = None
PSG_OFFLOAD_TONE = [t for t in PSG_TONE if t != UNISON_SQ]   # offload はユニゾン予約を除く矩形

# ============ VGM 生成 ============
body = bytearray()
def ymP(port, reg, val): body.extend((0x52 if port == 0 else 0x53, reg & 0xFF, val & 0xFF))
def ykey(val):           body.extend((0x52, 0x28, val & 0xFF))
def psg(b):              body.extend((0x50, b & 0xFF))
def wait(samples):
    while samples > 0:
        n = min(samples, 65535)
        body.extend((0x61, n & 0xFF, (n >> 8) & 0xFF)); samples -= n

def u32(v):
    return bytes((v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF))

def clamp8(v):
    return max(0, min(255, int(round(v))))

def midi_var(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))

def drum_key(notes):
    return tuple(sorted(set(notes)))

def write_drum_midi(path, notes, velocity=112):
    notes = drum_key(notes)
    trk = bytearray()
    trk += midi_var(0) + bytes([0xFF, 0x51, 0x03, 0x07, 0xA1, 0x20])  # 120 BPM
    for i, note in enumerate(notes):
        trk += midi_var(0) + bytes([0x99, note & 0x7F, velocity & 0x7F])   # ch10 note on
    for i, note in enumerate(notes):
        trk += midi_var(120 if i == 0 else 0) + bytes([0x89, note & 0x7F, 0x00])
    trk += midi_var(1440) + bytes([0xFF, 0x2F, 0x00])
    with open(path, "wb") as f:
        f.write(b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480))
        f.write(b"MTrk" + struct.pack(">I", len(trk)) + trk)

def write_note_midi(path, program, note, velocity=104):
    trk = bytearray()
    trk += midi_var(0) + bytes([0xFF, 0x51, 0x03, 0x07, 0xA1, 0x20])  # 120 BPM
    trk += midi_var(0) + bytes([0xC0, program & 0x7F])
    trk += midi_var(0) + bytes([0x90, note & 0x7F, velocity & 0x7F])
    trk += midi_var(180) + bytes([0x80, note & 0x7F, 0x00])
    trk += midi_var(1440) + bytes([0xFF, 0x2F, 0x00])
    with open(path, "wb") as f:
        f.write(b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480))
        f.write(b"MTrk" + struct.pack(">I", len(trk)) + trk)

def read_wav_mono(path):
    with wave.open(path, "rb") as w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())

    step = nch * sw
    samples = []
    for i in range(0, len(raw), step):
        acc = 0.0
        for ch in range(nch):
            off = i + ch * sw
            if sw == 1:
                v = (raw[off] - 128) / 128.0
            elif sw == 2:
                v = int.from_bytes(raw[off:off + 2], "little", signed=True) / 32768.0
            elif sw == 3:
                b = raw[off:off + 3]
                v = int.from_bytes(b + (b"\xFF" if b[2] & 0x80 else b"\x00"), "little", signed=True) / 8388608.0
            elif sw == 4:
                v = int.from_bytes(raw[off:off + 4], "little", signed=True) / 2147483648.0
            else:
                raise SystemExit(f"unsupported wav sample width: {sw}")
            acc += v
        samples.append(acc / nch)
    return rate, samples

def trim_audio(samples, rate, notes):
    notes = drum_key(notes)
    if not samples:
        return [0.0]
    peak = max(abs(v) for v in samples)
    if peak <= 0.0001:
        return [0.0]

    threshold = max(0.003, peak * 0.01)
    first = next((i for i, v in enumerate(samples) if abs(v) >= threshold), 0)
    last = len(samples) - 1
    while last > first and abs(samples[last]) < threshold:
        last -= 1

    pre = int(0.004 * rate)
    post = int(0.025 * rate)
    first = max(0, first - pre)
    last = min(len(samples) - 1, last + post)

    max_sec = (
        max(HAT_OPEN_MAX_SEC if n == 46 else HAT_CLOSED_MAX_SEC for n in notes)
        if all(n in HAT_NOTES for n in notes) else
        0.45 if any(n in (35, 36) for n in notes) else 0.35
    )
    max_len = int(max_sec * rate)
    result = samples[first:last + 1][:max_len]

    fade_sec = 0.010 if all(n in HAT_NOTES for n in notes) else 0.006
    fade = min(int(fade_sec * rate), len(result))
    if fade:
        for i in range(fade):
            result[-fade + i] *= (fade - i) / fade
    return result or [0.0]

def trim_shot_audio(samples, rate, max_sec=PCM_SHOT_MAX_SEC):
    if not samples:
        return [0.0]
    peak = max(abs(v) for v in samples)
    if peak <= 0.0001:
        return [0.0]

    threshold = max(0.002, peak * 0.008)
    first = next((i for i, v in enumerate(samples) if abs(v) >= threshold), 0)
    last = len(samples) - 1
    while last > first and abs(samples[last]) < threshold:
        last -= 1

    first = max(0, first - int(0.004 * rate))
    last = min(len(samples) - 1, last + int(0.030 * rate))
    result = samples[first:last + 1][:int(max_sec * rate)]

    fade = min(int(0.012 * rate), len(result))
    if fade:
        for i in range(fade):
            result[-fade + i] *= (fade - i) / fade
    return result or [0.0]

def resample_linear(samples, in_rate, out_rate):
    if in_rate == out_rate:
        return samples[:]
    out_len = max(1, int(round(len(samples) * out_rate / in_rate)))
    result = []
    for i in range(out_len):
        pos = i * in_rate / out_rate
        j = int(pos)
        frac = pos - j
        if j + 1 < len(samples):
            result.append(samples[j] * (1.0 - frac) + samples[j + 1] * frac)
        else:
            result.append(samples[-1])
    return result

def render_drum_float(notes):
    notes = drum_key(notes)
    fs = shutil.which("fluidsynth")
    if fs is None:
        raise SystemExit("--pcm-drums requires fluidsynth. Install: sudo apt-get install fluidsynth fluid-soundfont-gm")
    if not os.path.exists(SF2):
        raise SystemExit(f"--pcm-drums SoundFont not found: {SF2}")

    with tempfile.TemporaryDirectory() as td:
        suffix = "_".join(str(n) for n in notes)
        mid = os.path.join(td, f"drum_{suffix}.mid")
        wav_path = os.path.join(td, f"drum_{suffix}.wav")
        write_drum_midi(mid, notes)
        cmd = [fs, "-ni", "-g", "0.8", "-F", wav_path, "-r", "44100", SF2, mid]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if r.returncode != 0:
            raise SystemExit("fluidsynth failed:\n" + r.stdout)
        rate, samples = read_wav_mono(wav_path)

    samples = trim_audio(samples, rate, notes)
    return resample_linear(samples, rate, PCM_RATE)

def render_shot_float(program, note):
    fs = shutil.which("fluidsynth")
    if fs is None:
        raise SystemExit("--pcm-shot requires fluidsynth. Install: sudo apt-get install fluidsynth fluid-soundfont-gm")
    if not os.path.exists(SF2):
        raise SystemExit(f"--pcm-shot SoundFont not found: {SF2}")

    with tempfile.TemporaryDirectory() as td:
        mid = os.path.join(td, f"shot_p{program}_n{note}.mid")
        wav_path = os.path.join(td, f"shot_p{program}_n{note}.wav")
        write_note_midi(mid, program, note)
        cmd = [fs, "-ni", "-g", "0.75", "-F", wav_path, "-r", "44100", SF2, mid]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if r.returncode != 0:
            raise SystemExit("fluidsynth failed:\n" + r.stdout)
        rate, samples = read_wav_mono(wav_path)

    samples = trim_shot_audio(samples, rate)
    return resample_linear(samples, rate, PCM_RATE)

def mix_drum_float(notes):
    notes = drum_key(notes)
    parts = [render_drum_float((n,)) for n in notes]
    if not parts:
        return [0.0]
    out_len = max(len(p) for p in parts)
    result = [0.0] * out_len
    for part in parts:
        for i, v in enumerate(part):
            result[i] += v
    return result

def mix_float_parts(parts):
    if not parts:
        return [0.0]
    out_len = max(len(p) for p in parts)
    result = [0.0] * out_len
    for part in parts:
        for i, v in enumerate(part):
            result[i] += v
    return result

PCM_VOICES = 3   # XGM2 の PCM チャンネル数。VGM stream id 0..2 → xgmtool で優先度 3..1 ＝ 3 並行ボイス。

pcm_offsets = {}      # sample key(tuple) -> data blob 内オフセット
pcm_sizes = {}        # sample key -> バイト長
drum_plays = {}       # onset(SR 単位 int) -> [(stream_id, key), ...]
shot_plays = {}       # onset(SR 単位 int) -> [(stream_id, key), ...]
pcm_shot_selected = []
pcm_shot_skipped = 0
pcm_shot_play_count = {}
pcm_shot_skip_count = {}
pcm_shot_mix_count = 0

def _render_float(key):
    if isinstance(key, tuple) and key and key[0] == "shot":
        _tag, program, note = key
        return render_shot_float(program, note)
    if isinstance(key, tuple) and key and key[0] == "shotmix":
        return mix_float_parts([_render_float(k) for k in key[1]])
    key = drum_key(key)
    return render_drum_float(key) if len(key) == 1 else mix_drum_float(key)

def setup_pcm_drums():
    """ドラムを 3 PCM チャンネルへ振り分ける。各 onset を最大 3 ユニットへ分け（4 音以上は
    3 バケツへミックスダウン＝重複 PCM を収録して 3 パートに収める）、時刻順にボイス割り当て
    （空き ch 優先・無ければ最速解放を steal）。各音は個別サンプルで、音量は全ドラム共通スケールで
    正規化（kick/hat の相対バランスを保つ）。VGM は stream id 0..2 を全て YM2612 DAC へ向け、
    xgmtool が stream id を優先度に使って 3 PCM チャンネルへ載せる。"""
    global pcm_shot_skipped, pcm_shot_mix_count
    onsets = sorted(drum_groups.items())                 # [(samp, [notes]), ...]
    onset_units = {}
    keys = set()
    for samp, notes in onsets:
        u = drum_key(notes)
        if len(u) <= PCM_VOICES:
            units = [(n,) for n in u]
        else:                                            # 4 音以上: 3 バケツへミックスダウン
            buckets = [[] for _ in range(PCM_VOICES)]
            for i, n in enumerate(u):
                buckets[i % PCM_VOICES].append(n)
            units = [tuple(b) for b in buckets if b]
        onset_units[samp] = [drum_key(x) for x in units]
        keys.update(onset_units[samp])
    shot_onsets = {}
    if PCM_DRUMS and pcm_shot_chs:
        pcm_shot_selected.extend(pcm_shot_chs)
        for c in pcm_shot_chs:
            p = prog.get(c, 0)
            for sec, note, _vel in note_on_seq.get(c, []):
                samp = int(round(sec * SR))
                key = ("shot", p, note)
                shot_onsets.setdefault(samp, [])
                if key not in shot_onsets[samp]:
                    shot_onsets[samp].append((c, key))
                keys.add(key)
        for entries in shot_onsets.values():
            for i in range(len(entries) - 1):
                mix_keys = tuple(k for _src_ch, k in entries[i:])
                if len(mix_keys) > 1:
                    keys.add(("shotmix", mix_keys))
    if not keys:
        return
    floats = {k: _render_float(k) for k in sorted(keys, key=str)}
    blob = bytearray()
    for k in sorted(keys, key=str):
        pcm_offsets[k] = len(blob)
        kscale = min(1.8, 0.88 / max((abs(v) for v in floats[k]), default=0.0001)) * (
            PCM_SHOT_GAIN if isinstance(k, tuple) and k and k[0] in ("shot", "shotmix") else PCM_DRUM_GAIN
        )
        b = bytes(clamp8(128 + v * kscale * 127.0) for v in floats[k])
        pcm_sizes[k] = len(b)
        blob.extend(b)
    free_at = [-1.0] * PCM_VOICES                        # 各 PCM ch が解放される時刻(秒)
    for samp, _notes in onsets:
        t = samp / SR
        plays = []
        for k in onset_units[samp]:
            ch = next((c for c in range(PCM_VOICES) if free_at[c] <= t), None)
            if ch is None:
                ch = min(range(PCM_VOICES), key=lambda c: free_at[c])   # 最速解放を steal
            free_at[ch] = t + pcm_sizes[k] / PCM_RATE
            plays.append((ch, k))
        drum_plays[samp] = plays
    for samp, keys_at in sorted(shot_onsets.items()):
        t = samp / SR
        plays = []
        free_chs = [c for c in range(PCM_VOICES) if free_at[c] <= t]
        if len(keys_at) > len(free_chs) and free_chs:
            keep_count = max(0, len(free_chs) - 1)
            for src_ch, k in keys_at[:keep_count]:
                ch = free_chs.pop(0)
                free_at[ch] = t + pcm_sizes[k] / PCM_RATE
                pcm_shot_play_count[src_ch] = pcm_shot_play_count.get(src_ch, 0) + 1
                plays.append((ch, k))
            mix_entries = keys_at[keep_count:]
            mix_key = ("shotmix", tuple(k for _src_ch, k in mix_entries))
            ch = free_chs.pop(0)
            free_at[ch] = t + pcm_sizes[mix_key] / PCM_RATE
            for src_ch, _k in mix_entries:
                pcm_shot_play_count[src_ch] = pcm_shot_play_count.get(src_ch, 0) + 1
            pcm_shot_mix_count += 1
            plays.append((ch, mix_key))
        else:
            for src_ch, k in keys_at:
                ch = next((c for c in range(PCM_VOICES) if free_at[c] <= t), None)
                if ch is None:
                    pcm_shot_skipped += 1
                    pcm_shot_skip_count[src_ch] = pcm_shot_skip_count.get(src_ch, 0) + 1
                    continue
                free_at[ch] = t + pcm_sizes[k] / PCM_RATE
                pcm_shot_play_count[src_ch] = pcm_shot_play_count.get(src_ch, 0) + 1
                plays.append((ch, k))
        if plays:
            shot_plays[samp] = plays
    body.extend((0x67, 0x66, 0x00)); body.extend(u32(len(blob))); body.extend(blob)
    for sid in range(PCM_VOICES):
        body.extend((0x90, sid, 0x02, 0x00, 0x2A))       # stream sid -> YM2612 DAC
        body.extend((0x91, sid, 0x00, 0x01, 0x00))       # data bank 0, step 1
        body.extend((0x92, sid)); body.extend(u32(PCM_RATE))

def pcm_drum_play(samp):
    plays = drum_plays.get(samp)
    if not plays:
        return None
    def go():
        for sid, k in plays:
            body.extend((0x93, sid)); body.extend(u32(pcm_offsets[k]))
            body.append(0x01); body.extend(u32(pcm_sizes[k]))
    return go

def pcm_shot_play(samp):
    plays = shot_plays.get(samp)
    if not plays:
        return None
    def go():
        for sid, k in plays:
            body.extend((0x93, sid)); body.extend(u32(pcm_offsets[k]))
            body.append(0x01); body.extend(u32(pcm_sizes[k]))
    return go

OPSLOT = (0x00, 0x04, 0x08, 0x0C)
def ch_port(ch): return 0 if ch < 3 else 1
def ch_off(ch):  return ch if ch < 3 else ch - 3
def ch_sel(ch):  return ch if ch < 3 else ch + 1

def patch_fm(ch, name):
    p, o = ch_port(ch), ch_off(ch)
    patch = PATCH[name]
    sustain = (name == "bass" and SUSTAIN_BASS)
    for si, off in enumerate(OPSLOT):
        op = patch["op"][si]
        mul = op["mul"]
        tl = min(127, op["tl"] + (ATTEN if op["tl"] < 0x70 else 0))
        d2r = op["d2r"] & 0x1F
        slrr = op["slrr"] & 0xFF
        if sustain and si in (2, 3):           # 持続低音: alg4 キャリア(S2/S4)を鳴らし切りに
            d2r = 0                            #   D2R=0: サステイン後は減衰しない
            slrr = slrr & 0x0F                 #   SL=0: アタックレベルのまま保持（RR は据え置き）
        ymP(p, 0x30 + off + o, ((op.get("dt", 0) & 7) << 4) | (mul & 0x0F))   # DT1 + MUL
        ymP(p, 0x40 + off + o, tl)
        ymP(p, 0x50 + off + o, ((op.get("rs", 0) & 3) << 6) | (op["ar"] & 0x1F))  # RS + AR
        ymP(p, 0x60 + off + o, op["d1r"] & 0x1F)
        ymP(p, 0x70 + off + o, d2r)
        ymP(p, 0x80 + off + o, slrr)
        ymP(p, 0x90 + off + o, 0x00)
    ymP(p, 0xB0 + o, ((patch["fb"] & 7) << 3) | (patch["alg"] & 7))
    ymP(p, 0xB4 + o, 0xC0 | ((patch.get("ams", 0) & 3) << 4) | (patch.get("fms", 0) & 7))   # L/R + AMS + FMS

# 初期化
if PCM_DRUMS:
    drum_groups = {}
    for sec, kind, note, chan, _ in timed:
        if chan == DRUM_CH and kind == "on":
            drum_groups.setdefault(int(round(sec * SR)), []).append(note)
    setup_pcm_drums()
ymP(0, 0x22, 0x08 | LFO_FREQ); ymP(0, 0x27, 0x00); ymP(0, 0x2B, 0x80 if PCM_DRUMS else 0x00)   # LFO 有効（FMS ビブラート用）
for name, chs in FM_OF.items():
    for ch in chs:
        ykey(ch_sel(ch)); patch_fm(ch, name)
for pc in range(4): psg(0x80 | (pc << 5) | 0x10 | 0x0F)

# ---- アクション列（同時/予約イベントを時刻順に） ----
actions = []; seq = 0
def emit(sec, fn):
    global seq
    actions.append((int(round(sec * SR)), seq, fn)); seq += 1
def fnum_block(freq):
    block = 0; fn = freq * (2 ** 21) * 144 / YM_CLOCK
    while fn >= 2048 and block < 7:
        block += 1; fn /= 2.0
    return int(round(fn)) & 0x7FF, block
def midi_freq(m): return 440.0 * (2.0 ** ((m - 69) / 12.0))

def velocity_tl_delta(vel):
    return max(0, min(22, int(round((127 - vel) * 22 / 127))))

ctrl_vol = [127] * 16
ctrl_expr = [127] * 16
pitch_bend = [0] * 16
mod_ctrl = [0] * 16

def ctrl_gain(chan):
    return max(0.0, min(1.0, (ctrl_vol[chan] * ctrl_expr[chan]) / (127.0 * 127.0)))

def ctrl_tl_delta(chan):
    gain = ctrl_gain(chan)
    if gain <= 0.0:
        return 60
    return max(0, min(60, int(round(-20.0 * math.log10(gain) / 0.75))))

def ctrl_psg_delta(chan):
    gain = ctrl_gain(chan)
    if gain <= 0.0:
        return 15
    return max(0, min(15, int(round(-20.0 * math.log10(gain) / 2.0))))

def pitch_offset(chan, sec):
    bend = pitch_bend[chan] * PITCH_BEND_RANGE / 8192.0
    if mod_ctrl[chan] <= 0:
        return bend
    depth = MOD_DEPTH_SEMIS * mod_ctrl[chan] / 127.0
    phase = sec * MOD_RATE_HZ * math.tau + chan * 0.73
    return bend + math.sin(phase) * depth

def fm_pitch(ch, midi, offset):
    fn, blk = fnum_block(midi_freq(midi + offset)); p, o = ch_port(ch), ch_off(ch)
    ymP(p, 0xA4 + o, ((blk & 7) << 3) | ((fn >> 8) & 7))
    ymP(p, 0xA0 + o, fn & 0xFF)

def psg_pitch(pc, midi, offset):
    per = psg_period(pv.fold_pitch(midi + offset))   # PSG 可聴域へオクターブ折り返し（低音の音痴防止）
    psg(0x80 | (pc << 5) | (per & 0x0F)); psg((per >> 4) & 0x3F)

def fm_lead_boost(chan):
    expressive = chan_cc_count.get(1, {}).get(chan, 0) or chan_pb_count.get(chan, 0)
    if expressive and duty.get(chan, 0.0) <= 0.45:
        return 1
    return 0

def fm_velocity(ch, name, vel, ctrl_delta, lead_boost):
    p, o = ch_port(ch), ch_off(ch)
    patch = PATCH[name]
    delta = velocity_tl_delta(vel) + ctrl_delta
    for si, off in enumerate(OPSLOT):
        tl = patch["op"][si]["tl"]
        if tl < 0x70:
            boost = lead_boost
            if name == "bass" and si in (2, 3):   # bass の alg4 キャリア(S2,S4)だけ持ち上げ＝純粋に音量UP
                boost += BASS_BOOST
            ymP(p, 0x40 + off + o, max(0, min(127, tl + ATTEN + delta - boost)))

def fm_on(ch, name, midi, vel, chan, sec):
    ctrl_delta = ctrl_tl_delta(chan)
    lead_boost = fm_lead_boost(chan)
    offset = pitch_offset(chan, sec)
    def go():
        fm_velocity(ch, name, vel, ctrl_delta, lead_boost)
        fm_pitch(ch, midi, offset); ykey(0xF0 | ch_sel(ch))
    return go
def fm_vol(ch, name, midi, vel, chan):
    ctrl_delta = ctrl_tl_delta(chan)
    lead_boost = fm_lead_boost(chan)
    return lambda: fm_velocity(ch, name, vel, ctrl_delta, lead_boost)
def fm_note_pitch(ch, midi, vel, chan, sec):
    offset = pitch_offset(chan, sec)
    return lambda: fm_pitch(ch, midi, offset)
def fm_off(ch): return lambda: ykey(ch_sel(ch))
def psg_period(midi): return max(1, min(1023, int(round(PSG_CLOCK / (32 * midi_freq(midi))))))
def psg_channel_atten(chan):
    extra = 0
    if avgdur.get(chan, 0.0) > 0.30:
        extra += 1
    if avgdur.get(chan, 0.0) > 0.55:
        extra += 1
    if duty.get(chan, 0.0) > 0.35:
        extra += 1
    if duty.get(chan, 0.0) > 0.70:
        extra += 1
    if psg_score(chan) < 0:
        extra += 1
    return extra
def psg_accomp_atten(chan):
    p = prog.get(chan, 0)
    expressive = chan_cc_count.get(1, {}).get(chan, 0) or chan_pb_count.get(chan, 0)
    if 24 <= p <= 31:
        return 0
    if expressive and duty.get(chan, 0.0) <= 0.45:
        return 0
    return PSG_ACCOMP_ATTEN
def psg_base_vol(midi, vel, psg_delta, chan):
    v = 2 + psg_accomp_atten(chan) + psg_channel_atten(chan) + psg_delta + int(round((127 - vel) * 5 / 127))
    if midi < 48:
        v += 1
    if chan in psg_echo_chs:
        v += 7
    return max(1, min(9, v))
def psg_on(pc, midi, vel=96, chan=0, sec=0):
    offset = pitch_offset(chan, sec)
    vol = psg_base_vol(midi, vel, ctrl_psg_delta(chan), chan)
    def go():
        psg_pitch(pc, midi, offset)
        psg(0x80 | (pc << 5) | 0x10 | (vol & 0x0F))
    return go
def psg_note_vol(pc, midi, vel, chan):
    vol = psg_base_vol(midi, vel, ctrl_psg_delta(chan), chan)
    return psg_vol(pc, vol)
def psg_note_pitch(pc, midi, vel, chan, sec):
    offset = pitch_offset(chan, sec)
    return lambda: psg_pitch(pc, midi, offset)
def psg_off(pc): return lambda: psg(0x80 | (pc << 5) | 0x10 | 0x0F)
def psg_vol(pc, vol): return lambda: psg(0x80 | (pc << 5) | 0x10 | (vol & 0x0F))
def noise_hit(note):
    # PSG ノイズ音量（0=最大, 15=無音）。PCMドラムと同じく奥へ下げる。
    if note <= 37:   rate, vol = 0b10, 0x07   # キック
    elif note >= 48: rate, vol = 0b00, 0x09   # ハイハット/シンバル
    else:            rate, vol = 0b01, 0x07   # スネア
    return (lambda: (psg(0xE0 | (1 << 2) | rate), psg(0xF0 | vol))), vol
def noise_vol(v): return lambda: psg(0xF0 | (v & 0x0F))

class Pool:
    def __init__(self, chans, on_fn, off_fn, decay_fn=None, vol_fn=None, pitch_fn=None,
                 preferred=None, retrigger_same=False):
        self.chans = list(chans); self.voice = {c: None for c in self.chans}
        self.on_fn = on_fn; self.off_fn = off_fn; self.decay_fn = decay_fn; self.vol_fn = vol_fn; self.pitch_fn = pitch_fn
        self.preferred = dict(preferred or {})      # midi channel -> preferred hw channel
        self.reserved = set(self.preferred.values())
        self.retrigger_same = retrigger_same
        self.ignore_off_until = {}
        # 世代カウンタ: ch にノートを割り当て/解放するたび +1。PSG の decay/ビブラートで予約した
        # 未来の書き込みは、発火時に世代が進んでいたら no-op にする（スティールや早い note-off で
        # 別ノートに化けた ch を、古い予約が壊して鳴りっぱなしにするのを防ぐ）。
        self.gen = {c: 0 for c in self.chans}
    def note_on(self, sec, midi, chan, vel=96):
        # 同じ (chan,midi) が既に鳴っていれば新ボイスを取らずそのボイスを再発音する。
        # 重複ボイス（同一 chan,midi が複数ボイスに乗る）を作らないことで、後続の note_off が
        # 確実に一致して消音できる＝取りこぼしで鳴りっぱなしになるのを防ぐ。
        f = next((c for c in self.chans if self.voice[c] is not None
                  and self.voice[c][0] == midi and self.voice[c][2] == chan), None)
        same_voice = f is not None
        pref = self.preferred.get(chan)
        steal = False
        if f is None:
            if pref is not None and self.voice.get(pref) is None:
                f = pref
            else:
                # 別MIDIチャンネルへ予約したFMは、通常の空きボイス探索では横取りしない。
                f = next((c for c in self.chans if self.voice[c] is None and c not in self.reserved), None)
        if f is None and pref is not None:
            # 専用FMが埋まっている単音パートは、その専用FMを再発音する。別パートの専用FMへ
            # はみ出すと、旋律と和音が同じ動きに聞こえる原因になる。
            f = pref; steal = True
        if f is None:
            f = min(self.chans, key=lambda c: self.voice[c][1]); steal = True
        if steal:
            emit(sec, self.off_fn(f))
        elif same_voice and self.retrigger_same:
            # PSG は同じ音程への note-on だけでは発音境界が出にくいので、同音連打では短い隙間を作る。
            emit(sec, self.off_fn(f))
            self.ignore_off_until[(chan, midi)] = sec + 0.012
        self.gen[f] += 1                          # 新しい発音＝この ch の旧予約を無効化
        self.voice[f] = [midi, sec, chan, vel]; emit(sec + (0.008 if same_voice and self.retrigger_same else 0.0), self.on_fn(f, midi, vel, chan, sec))
        if self.decay_fn is not None:
            self.decay_fn(f, sec + (0.008 if same_voice and self.retrigger_same else 0.0), midi, vel, chan)
    def note_off(self, sec, midi, chan):
        if sec <= self.ignore_off_until.get((chan, midi), -1.0):
            return
        ch = next((c for c in reversed(self.chans)
                   if self.voice[c] is not None and self.voice[c][0] == midi and self.voice[c][2] == chan), None)
        if ch is not None:
            self.gen[ch] += 1                     # 消音＝以降の予約を無効化
            emit(sec, self.off_fn(ch)); self.voice[ch] = None
    def controller_change(self, sec, chan):
        if self.vol_fn is None:
            return
        for hw, v in self.voice.items():
            if v is not None and v[2] == chan:
                emit(sec, self.vol_fn(hw, v[0], v[3], chan))
    def pitch_change(self, sec, chan):
        if self.pitch_fn is None:
            return
        for hw, v in self.voice.items():
            if v is not None and v[2] == chan:
                emit(sec, self.pitch_fn(hw, v[0], v[3], chan, sec))

# 各ノートの実音長（matching note-off まで）。psg_decay が note-off 後に音量を上げ直して
# PSG ボイスを鳴らしっぱなしにするのを防ぐためのガードに使う（(chan,midi,onset)->dur 秒）。
note_durs = {}
_open_dur = {}
for _sec, _kind, _note, _chan, _vel in timed:
    if _chan == DRUM_CH or _kind not in ("on", "off"):
        continue
    key = (_chan, _note)
    if _kind == "on":
        _open_dur.setdefault(key, []).append(_sec)
    else:
        st = _open_dur.get(key)
        if st:
            on_sec = st.pop(0)
            note_durs[(_chan, _note, round(on_sec, 4))] = _sec - on_sec

def psg_style_for(chan):
    if chan in psg_echo_chs:
        return "echo"                 # 遅延複製＝速く消えるエコータップ
    return pv.pick_decay_style(prog.get(chan, 0), duty.get(chan, 0.0), avgdur.get(chan, 0.0))

def psg_guard_emit(pc, at_sec, gen_at, fn):
    # 発火時に ch の世代が変わっていたら no-op（スティール/早い note-off で別ノートに化けた ch を守る）
    def g():
        if psg_pool is not None and psg_pool.gen.get(pc, -1) == gen_at:
            fn()
    emit(at_sec, g)

def psg_decay(pc, sec, midi, vel, chan):
    # genpsg.py（GG 版）と同じ表情を MD の PSG 逃がしへ: 多段 decay ＋ 控えめな常時ビブラート。
    # スタイルは GM プログラム/duty/平均音長から自動判定（pluck/soft/sustain/echo）。
    v = psg_base_vol(midi, vel, ctrl_psg_delta(chan), chan)
    dur = note_durs.get((chan, midi, round(sec, 4)), 1e9)
    gen_at = psg_pool.gen[pc]
    style = psg_style_for(chan)
    for off, a in pv.decay_schedule(style, v, dur):   # 多段ボリュームエンベロープ
        psg_guard_emit(pc, sec + off, gen_at, psg_vol(pc, a))
    # ビブラートは MIDI 側に CC1/PB の表情が無い持続/ソフト音だけに薄く足す（二重がけ回避）。
    expressive = chan_cc_count.get(1, {}).get(chan, 0) or chan_pb_count.get(chan, 0)
    if not expressive and style in ("soft", "sustain"):
        for off, mf in pv.vibrato_schedule(midi, dur, depth=0.15, step=0.06, phase=pc * 0.7):
            psg_guard_emit(pc, sec + off, gen_at, lambda pc=pc, mf=mf: psg_pitch(pc, mf, 0))

fm_pools = {name: Pool(chs, lambda ch, m, v, c, s, name=name: fm_on(ch, name, m, v, c, s), fm_off,
                       preferred=FM_PREF.get(name))
            for name, chs in FM_OF.items()}
for name, pool in fm_pools.items():
    pool.vol_fn = lambda ch, m, v, c, name=name: fm_vol(ch, name, m, v, c)
    pool.pitch_fn = lambda ch, m, v, c, s: fm_note_pitch(ch, m, v, c, s)
psg_pool = Pool(PSG_OFFLOAD_TONE, lambda pc, m, v, c, s: psg_on(pc, m, v, c, s), psg_off, psg_decay,
                lambda pc, m, v, c: psg_note_vol(pc, m, v, c),
                lambda pc, m, v, c, s: psg_note_pitch(pc, m, v, c, s),
                retrigger_same=True) if (psg_chs and PSG_OFFLOAD_TONE) else None

def bell_unison_on(sec, midi, vel):
    # bell 主旋律に重ねる PSG 矩形の“ピン”（同音・短い明るいアタック→速い減衰。余韻は FM bell が担う）。
    if UNISON_SQ is None:
        return
    pc = UNISON_SQ
    v0 = max(4, 8 - vel // 32)              # 控えめ（FM bell を主役に）。強い音ほど少し明るく
    def on():
        psg_pitch(pc, midi, 0)
        psg(0x80 | (pc << 5) | 0x10 | (v0 & 0x0F))
    emit(sec, on)
    emit(sec + 0.05, psg_vol(pc, min(15, v0 + 3)))
    emit(sec + 0.11, psg_vol(pc, min(15, v0 + 6)))
    emit(sec + 0.18, psg_vol(pc, 15))
def pool_of(chan):
    r = route.get(chan)
    if r is None: return None
    if r[0] == "fm":  return fm_pools.get(r[1])
    if r[0] == "psg": return psg_pool
    return None

emitted_drum_groups = set()
emitted_shot_groups = set()
for sec, kind, note, chan, vel in timed:
    if kind == "cc":
        if note in (7, 11) and sec >= last_note_sec - LOOP_TAIL_FADE_SEC:
            continue
        if note == 7:
            ctrl_vol[chan] = vel
        elif note == 11:
            ctrl_expr[chan] = vel
        elif note == 1:
            mod_ctrl[chan] = vel
        pool = pool_of(chan)
        if pool is not None and note in (7, 11):
            pool.controller_change(sec, chan)
        elif pool is not None and note == 1:
            pool.pitch_change(sec, chan)
        continue
    if kind == "pb":
        pitch_bend[chan] = note
        pool = pool_of(chan)
        if pool is not None:
            pool.pitch_change(sec, chan)
        continue
    if chan == DRUM_CH:
        if PCM_DRUMS and kind == "on":
            samp = int(round(sec * SR))
            if samp not in emitted_drum_groups:
                emitted_drum_groups.add(samp)
                go = pcm_drum_play(samp)
                if go is not None:
                    emit(sec, go)
        elif not NOPSG and kind == "on":       # PSG 不使用時はドラムを省略
            go, v0 = noise_hit(note); emit(sec, go)
            emit(sec + 0.05, noise_vol(min(15, v0 + 5))); emit(sec + 0.12, noise_vol(15))
        continue
    pool = pool_of(chan)
    if pool is None: continue
    if kind == "on":
        pool.note_on(sec, note, chan, vel)
        if chan == unison_ch:
            bell_unison_on(sec, note, vel)   # bell 主旋律に PSG 矩形ユニゾンを重ねる
        if chan in pcm_shot_chs:
            samp = int(round(sec * SR))
            key = (samp, prog.get(chan, 0), note)
            if key not in emitted_shot_groups:
                emitted_shot_groups.add(key)
                go = pcm_shot_play(samp)
                if go is not None:
                    emit(sec, go)
    else:
        pool.note_off(sec, note, chan)

loop_pos = len(body)
actions.sort(key=lambda a: (a[0], a[1]))
t0 = actions[0][0] if actions else 0       # 曲頭の無音を削る（先頭イベントを 0 に寄せる）
cur = 0
for samp, _, fn in actions:
    samp -= t0
    if samp > cur: wait(samp - cur); cur = samp
    fn()
total_samples = cur; loop_samples = total_samples
body.append(0x66)

# ============ VGM ヘッダ ============
DATA_OFF = 0x40
gd3 = make_gd3()
hdr = bytearray(DATA_OFF)
hdr[0x00:0x04] = b"Vgm "
gd3_pos = DATA_OFF + len(body)
total_len = gd3_pos + len(gd3)
struct.pack_into("<I", hdr, 0x04, total_len - 4)
struct.pack_into("<I", hdr, 0x08, 0x00000150)
struct.pack_into("<I", hdr, 0x0C, PSG_CLOCK)
struct.pack_into("<I", hdr, 0x18, total_samples)
struct.pack_into("<I", hdr, 0x1C, (DATA_OFF + loop_pos) - 0x1C)
struct.pack_into("<I", hdr, 0x20, loop_samples)
struct.pack_into("<I", hdr, 0x24, 60)
struct.pack_into("<H", hdr, 0x28, 0x0009)
hdr[0x2A] = 16
struct.pack_into("<I", hdr, 0x2C, YM_CLOCK)
struct.pack_into("<I", hdr, 0x14, gd3_pos - 0x14)
struct.pack_into("<I", hdr, 0x34, DATA_OFF - 0x34)

open(OUT, "wb").write(bytes(hdr) + bytes(body) + gd3)
print(f"{OUT}: dur={total_samples/SR:.1f}s bytes={total_len}")
print(f"  bass=ch{bass_ch}{' [SUSTAIN]' if SUSTAIN_BASS else ''} | FM={ {g: [ (c) for c in cs ] for g,cs in groups.items()} } "
      f"slots={ {g:FM_OF.get(g) for g in FM_OF} }")
print(f"  PSG(square)=ch{psg_chs} {'(guitar)' if guitar else '(lead offload)'} | "
      f"drums->{'PCM(%dch) ' % PCM_VOICES + str(sorted(pcm_offsets, key=str)) if PCM_DRUMS else 'noise'}")
if PCM_SHOT_SPEC:
    print(f"  PCM shot=ch{pcm_shot_selected} plays={sum(len(v) for v in shot_plays.values())} skipped={pcm_shot_skipped}")
    print(f"    by ch play={pcm_shot_play_count} skip={pcm_shot_skip_count} mixed={pcm_shot_mix_count}")
if psg_echo_chs:
    print(f"  PSG echo={list(zip(echo_main_chs, psg_echo_chs))}")
print(f"  CC/PB: CC1={cc_count.get(1, 0)} CC7={cc_count.get(7, 0)} CC11={cc_count.get(11, 0)} PB={pb_count}")
