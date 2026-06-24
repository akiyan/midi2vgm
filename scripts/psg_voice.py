#!/usr/bin/env python3
"""PSG(SN76489) の「表情」を作る共有ヘルパ。

genpsg.py（GG 専用 PSG VGM）と genvgm.py（MD の FM+PSG。PSG 逃がしパート）が同じ
エンベロープ／ビブラート／音域処理を使うための一元定義。PSG はハードのエンベロープを
持たないので、ソフトで音量レジスタ(0=最大,15=無音)を段階制御して decay を作り、ピッチを
細かく書き換えてビブラートを作る。スタイルは MIDI 特徴（GM プログラム/duty/平均音長）から導出する。

返すのは「(オフセット秒, 値)」のリストだけで、実際のレジスタ書き込みは呼び出し側に任せる
（genpsg は専用 ch、genvgm はスティールするプール、と発火方法が違うため）。
"""
import math

PSG_CLOCK = 3579545
PITCH_FLOOR = 45            # PSG 下限の目安（A2≒110Hz）。これ未満はオクターブ上げ。
PITCH_CEIL = 96             # これ超はオクターブ下げ（極端な高音の暴れ防止）。

VIB_DEPTH_SEMIS = 0.18
VIB_RATE_HZ = 5.5
VIB_STEP_SEC = 0.04
VIB_MIN_DUR = 0.25


def fold_pitch(m, floor=PITCH_FLOOR, ceil=PITCH_CEIL):
    """PSG の可聴域へオクターブ折り返し（float 可）。"""
    while m < floor:
        m += 12
    while m > ceil:
        m -= 12
    return m


def pick_decay_style(prog, duty, avgdur):
    """GM プログラムと duty/平均音長から decay スタイルを推定する。
    pluck=撥弦/打鍵で粒立つ音、sustain=長い持続音(パッド/弦/ベース)、soft=その他(既定)。"""
    if 24 <= prog <= 31:                 # ギター/撥弦
        return "pluck"
    if prog <= 15:                        # ピアノ/エレピ(0-7)・クロマパーカッション(8-15)
        return "pluck"
    if avgdur >= 0.7 or duty >= 0.6:      # 長い持続
        return "sustain"
    return "soft"


def decay_schedule(style, a0, dur):
    """(offset_sec, atten) のリスト。atten は PSG 音量(0=最大,15=無音)。dur 内のステップのみ。
    'echo' は genvgm のエコータップ専用（速く消える）。"""
    def steps(seq):
        return [(o, min(15, a0 + d)) for o, d in seq if o < dur]
    if style == "pluck":
        return steps([(0.04, 2), (0.10, 4), (0.22, 7)])
    if style == "echo":
        return [(o, v) for o, v in [(0.060, min(15, a0 + 2)), (0.140, 15)] if o < dur]
    if style == "sustain":
        return []                              # ベース/パッドは保持（減衰なし）
    # soft（既定）: 立ち上がりは軽く減衰してプラトー a0+2 へ。ただし PSG はそのまま伸ばすと
    # 一定音量の矩形ドローンが耳につくので、長い音符は後半をゆっくり追加減衰させる（消え切らない程度）。
    out = steps([(0.12, 1), (0.45, 2)])
    off, extra = 0.9, 3
    while off < dur and extra <= 6:
        out.append((off, min(15, a0 + extra)))
        off += 0.55; extra += 1
    return out


def vibrato_schedule(midi, dur, depth=VIB_DEPTH_SEMIS, rate=VIB_RATE_HZ,
                     step=VIB_STEP_SEC, phase=0.0):
    """(offset_sec, midi_float) のリスト。dur が短ければ空。ソフトでピッチを揺らす。"""
    if dur < VIB_MIN_DUR:
        return []
    out = []
    n = int(dur / step)
    for i in range(1, n):
        off = i * step
        m = midi + math.sin(off * rate * math.tau + phase) * depth
        out.append((off, m))
    return out
