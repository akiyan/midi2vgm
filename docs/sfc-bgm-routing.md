# SFC BGM MIDI Routing

This document maps the SFC/knulp-used MIDI parts to Mega Drive sound resources.
It is a human/AI-readable snapshot of the current `scripts/genvgm.py` routing rules
and `assets/midi/adjustments.txt`.

- MIDI channels are 1-based (`ch1`..`ch16`).
- FM names are YM2612 hardware channels (`FM1`..`FM6`).
- `pool` means multiple MIDI parts share the listed FM hardware channels at runtime.
- `preferred` means the pool reserves that FM channel for the MIDI part when possible.
- `PCM drums` means MIDI ch10 drums are rendered to XGM2 PCM streams.
- `PCM shot` means an extra one-shot PCM layer, not a replacement for the FM/PSG route.
- `PSG unison` means `bell+PSG` transient doubling; the MIDI part still routes to FM.

## 01_kamaitachi_no_yoru

- Adjustments: none
- Drums: PCM drums
- PCM shot: none

| FM ch | Patch/pool | MIDI source |
|---|---|---|
| FM1 | bass | preferred ch8 `Strings` |
| FM2 | strings pool | ch1/ch2/ch3 `Synth Voice`, ch9 `Contrabass` |
| FM3 | strings pool | ch1/ch2/ch3 `Synth Voice`, ch9 `Contrabass` |
| FM4 | strings pool | ch1/ch2/ch3 `Synth Voice`, ch9 `Contrabass` |
| FM5 | piano pool | ch7 `Electric Piano 1` |

| Route | MIDI source |
|---|---|
| PSG square | ch4/ch5/ch6 `Synth Voice` |
| PCM drums | ch10 |

## 02_introduction

- Adjustments: `bell+PSG pcm-shot=auto+4`
- Drums: PCM drums
- PSG unison: PSG3 doubles ch1 bell attacks
- PCM shot: ch4 manual + auto ch3/ch5. ch4/ch5 same-time hits are mixed into one PCM shot.

| FM ch | Patch/pool | MIDI source |
|---|---|---|
| FM1 | bass | preferred ch6 `Slow Strings` |
| FM2 | bell pool | preferred ch1 `Music Box` |
| FM3 | bell pool | preferred ch3 `Vibraphone` |
| FM4 | bell pool | preferred ch5 `Vibraphone` |
| FM5 | strings pool | ch4 `Slow Strings` |

| Route | MIDI source |
|---|---|
| FM bell | ch1/ch3/ch5 |
| FM strings | ch4 |
| FM bass | ch6 |
| PSG square | ch2 `Slow Strings` |
| PSG unison | ch1 on PSG3 |
| PCM shot | ch3 `Vibraphone`, ch4 `Slow Strings`, ch5 `Vibraphone` |
| PCM drums | ch10 |

## 03_gerende_no_koibitotachi

- Adjustments: none
- Drums: PCM drums
- PCM shot: none

| FM ch | Patch/pool | MIDI source |
|---|---|---|
| FM1 | bass | preferred ch8 `Strings` |
| FM2 | strings pool | ch5/ch6/ch7/ch9 `Strings` |
| FM3 | strings pool | ch5/ch6/ch7/ch9 `Strings` |
| FM4 | strings pool | ch5/ch6/ch7/ch9 `Strings` |
| FM5 | clar pool | ch1 `Harmonica` |

| Route | MIDI source |
|---|---|
| PSG square | ch2 `Harmonica`, ch3/ch4 `Trumpet` |
| PCM drums | ch10 |

## 04_hana_no_ol_sanningumi

- Adjustments: none
- Drums: PCM drums
- PCM shot: none

| FM ch | Patch/pool | MIDI source |
|---|---|---|
| FM1 | bass | preferred ch3 `Finger Bass` |
| FM2 | clar pool | ch1 `Alto Sax` |
| FM3 | clar pool | ch1 `Alto Sax` |
| FM4 | piano pool | ch2 `Electric Piano 1` |
| FM5 | piano pool | ch2 `Electric Piano 1` |

| Route | MIDI source |
|---|---|
| PCM drums | ch10 |

## 05_washi_ga_kayama_ya_otoko_no_daioujou

- Adjustments: none
- Drums: PCM drums
- PCM shot: none

| FM ch | Patch/pool | MIDI source |
|---|---|---|
| FM1 | bass | preferred ch8 `Finger Bass` |
| FM2 | piano pool | ch7 `Electric Piano 2` |
| FM3 | strings pool | preferred ch4 `Strings` |
| FM4 | strings pool | preferred ch5 `Strings` |
| FM5 | clar pool | ch3 `Tenor Sax` |

| Route | MIDI source |
|---|---|
| PSG square | ch1 `Piccolo`, ch2 `Recorder`, ch6 `Nylon Guitar` |
| PCM drums | ch10 |

## 07_pension_shupuru

- Adjustments: none
- Drums: PCM drums
- PCM shot: none

| FM ch | Patch/pool | MIDI source |
|---|---|---|
| FM1 | bass | preferred ch5 `Finger Bass` |
| FM2 | flute pool | preferred ch1 `Piccolo` |
| FM3 | flute pool | preferred ch2 `Recorder` |
| FM4 | pluck pool | ch4 `Nylon Guitar` |
| FM5 | clar pool | ch3 `Clarinet` |

| Route | MIDI source |
|---|---|
| PCM drums | ch10 |

## 09_okuretekita_kyaku_mikimoto

- Adjustments: none
- Drums: PCM drums
- PCM shot: none

| FM ch | Patch/pool | MIDI source |
|---|---|---|
| FM1 | bass | preferred ch5 `Finger Bass` |
| FM2 | brass pool | preferred ch2 `Trumpet` |
| FM3 | brass pool | preferred ch3 `Brass Section` |
| FM4 | piano pool | ch4 `Electric Piano 1` |
| FM5 | clar pool | ch1 `Alto Sax` |

| Route | MIDI source |
|---|---|
| PCM drums | ch10 |

## 10_akumu

- Adjustments: none
- Drums: PCM drums
- PCM shot: none

| FM ch | Patch/pool | MIDI source |
|---|---|---|
| FM1 | bass | preferred ch6 `Slap Bass 1` |
| FM2 | bell pool | preferred ch1 `Xylophone` |
| FM3 | bell pool | preferred ch2 `Xylophone` |
| FM4 | strings pool | ch3/ch4/ch5 `Synth Voice`, ch8 `Strings` |
| FM5 | strings pool | ch3/ch4/ch5 `Synth Voice`, ch8 `Strings` |

| Route | MIDI source |
|---|---|
| PSG square | ch7 `Synth Bass 2` |
| PCM drums | ch10 |

## 12_hen_na_bamen

- Adjustments: none
- Drums: PCM drums
- PCM shot: none

| FM ch | Patch/pool | MIDI source |
|---|---|---|
| FM1 | bass | preferred ch5 `Overdriven Guitar` |
| FM2 | bell pool | preferred ch3 `Music Box` |
| FM3 | bell pool | preferred ch4 `Vibraphone` |
| FM4 | bell pool | preferred ch1 `Marimba` |
| FM5 | bell pool | preferred ch2 `Marimba` |

| Route | MIDI source |
|---|---|
| PCM drums | ch10 |

## 14_gishin_anki

- Adjustments: none
- Drums: PCM drums
- PCM shot: none

| FM ch | Patch/pool | MIDI source |
|---|---|---|
| FM1 | bass | preferred ch3 `Strings` |
| FM2 | bell pool | preferred ch1 `Glockenspiel` |
| FM3 | bell pool | preferred ch2 `Music Box` |
| FM4 | flute pool | ch5 `prog122` |
| FM5 | strings pool | ch4 `Strings` |

| Route | MIDI source |
|---|---|
| PCM drums | ch10 |

## 17_hitotsu_no_suiri

- Adjustments: none
- Drums: PCM drums
- PCM shot: none

| FM ch | Patch/pool | MIDI source |
|---|---|---|
| FM1 | bass | preferred ch9 `Reverse Cymbal` |
| FM2 | bell pool | ch1 `Music Box`, ch2 `Xylophone` |
| FM3 | strings pool | ch3 `Strings`, ch4 `Synth Voice` |
| FM4 | flute pool | ch5 `Slap Bass 1` |
| FM5 | brass pool | ch6 `Synth Brass 2` |

| Route | MIDI source |
|---|---|
| PCM drums | ch10 |

## 22_kaiketsu

- Adjustments: none
- Drums: PCM drums
- PCM shot: none

| FM ch | Patch/pool | MIDI source |
|---|---|---|
| FM1 | bass | preferred ch6 `Orchestral Harp` |
| FM2 | flute pool | ch1 `prog88` |
| FM3 | bell pool | ch2 `Vibraphone` |
| FM4 | strings pool | ch3 `Synth Voice` |
| FM5 | piano pool | ch5 `Electric Piano 1` |

| Route | MIDI source |
|---|---|
| PSG square | ch4 `Synth Voice` |
| PCM drums | ch10 |

## 28_tooi_hi_no_genei

- Adjustments: none
- Drums: PCM drums
- PCM shot: none

| FM ch | Patch/pool | MIDI source |
|---|---|---|
| FM1 | bass | preferred ch7 `Slow Strings` |
| FM2 | bell pool | ch4/ch5/ch6 `Music Box` |
| FM3 | bell pool | ch4/ch5/ch6 `Music Box` |
| FM4 | flute pool | ch1 `Piccolo`, ch2 `Recorder` |
| FM5 | strings pool | ch9 `Strings` |

| Route | MIDI source |
|---|---|
| PSG square | ch3 `Piccolo`, ch8 `Strings`, ch11 `prog82` |
| PCM drums | ch10 |

## 29_kohakuiro_no_mikazuki

- Adjustments: none
- Drums: PCM drums
- PCM shot: none

| FM ch | Patch/pool | MIDI source |
|---|---|---|
| FM1 | bass | preferred ch6 `Finger Bass` |
| FM2 | piano pool | preferred ch2 `Electric Piano 2` |
| FM3 | piano pool | preferred ch3 `Electric Piano 1` |
| FM4 | piano pool | preferred ch4 `Electric Piano 1` |
| FM5 | piano pool | preferred ch5 `Electric Piano 1` |

| Route | MIDI source |
|---|---|
| PSG square | ch1 `Muted Trumpet` |
| PCM drums | ch10 |
