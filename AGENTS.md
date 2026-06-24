# AGENTS.md

This repository contains standalone MIDI to VGM conversion tools for Sega Mega
Drive / Genesis style music.

## Scope

- Keep the repository public-safe. Do not commit copyrighted MIDI files,
  generated VGM dumps, SoundFonts, ROMs, or project-specific game harnesses.
- The tracked files should be conversion code, presets, mapping notes,
  documentation, and small text examples only.
- `CLAUDE.md` is an alias to this file.

## Tooling

- Main converter: `python3 scripts/genvgm.py IN.mid OUT.vgm`.
- Multi-file wrapper: `python3 scripts/genallbgm.py -o OUT_DIR IN.mid [...]`.
- PSG-only converter: `python3 scripts/genpsg.py IN.mid OUT.vgm`.
- PSG multi-file wrapper: `python3 scripts/genallpsg.py -o OUT_DIR IN.mid [...]`.
- Shared PSG expression helpers live in `scripts/psg_voice.py`.

## Dependencies

- Python 3.10+ is enough for non-PCM conversion.
- `--pcm-drums` and `--pcm-shot` require FluidSynth and a GM SoundFont.
- SGDK `rescomp` / `xgmtool` are optional downstream tools for VGM to XGM/XGM2
  integration.

## Checks

Before publishing changes, at minimum run:

```sh
python3 -m py_compile scripts/*.py
```

If local MIDI files are available, also test one direct conversion and one
multi-file wrapper conversion. Do not add those MIDI/VGM files to git.
