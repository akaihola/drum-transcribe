# Open-source Automatic Drum Transcription (ADT) landscape, as of September 2026

Research summary gathered 2026-09-20 (web survey by research agent).

## Ranked shortlist: most promising "audio → drum sheet music" pipelines

**1. drum2midi (miraer) — best current all-in-one open-source drum-audio→MIDI engine**
[github.com/miraer/drum2midi](https://github.com/miraer/drum2midi) — MIT, new in 2025-2026 (v0.1.0), actively benchmarked. Wraps exactly the state-of-the-art recipe from Riley & Dixon's Sept 2025 paper ([arXiv:2509.24853](https://arxiv.org/abs/2509.24853)): htdemucs for drum-stem extraction from a full mix → ADTOF onset detection (5 classes) → MDX23C DrumSep 6-stem separation for loudness/velocity and articulation (tom pitch splitting, hi-hat open/closed/pedal, ride-vs-crash) → General MIDI ch.10 at 960 PPQ with velocities. Benchmarks: F1 0.882 on MDB-Drums, 0.935 on IDMT-SMT-Drums; beat the commercial ReStem 2 Pro (0.820) on the same tracks. Install: clone + `setup_env.py` venv (417 MB model auto-downloads). GPU optional — separation is ~12× faster on GPU but ADTOF inference is actually faster on CPU. Caveat: ADTOF weights are CC BY-NC (non-commercial). Pair with beat_this + MuseScore 4.5 for the notation half.
- Pros: highest measured accuracy in open source, velocity + 7-class output, honest benchmarks. Cons: young project, single maintainer, no notation stage built in.

**2. DrumLab (DomekRomek) — turnkey local GUI, audio → MIDI + sheet music**
[github.com/DomekRomek/DrumLab](https://github.com/DomekRomek/DrumLab) — AGPL-3.0, local/offline FastAPI web GUI wrapping Demucs + ADTOF-pytorch + music21. Outputs stems, standard and quantized MIDI, and MusicXML sheet music, plus slow-down playback for practice. Python 3.10+, CUDA PyTorch optional (CPU works, slower). Tiny community (2 stars) but functional and exactly the requested end-to-end workflow.

**3. DIY pipeline: python-audio-separator → ADTOF-pytorch → beat_this → music21 → MuseScore 4.5** — most controllable
- Separation: [nomadkaraoke/python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator) (`pip/uv install audio-separator`, actively maintained, runs UVR's MDX-Net/MDXC/Demucs models incl. the community MDX23C 6-stem drumsep model); or plain `demucs` (htdemucs drums stem).
- Transcription: [xavriley/ADTOF-pytorch](https://github.com/xavriley/ADTOF-pytorch) — PyTorch port of ADTOF's pretrained weights (Xavier Riley, same author as the arXiv paper above), deps only torch/librosa/pretty_midi — no TensorFlow/madmom, `pip install -e .` from clone; ~-0.2% F-measure vs original. Also has [cptx032/adtof-gui](https://github.com/cptx032/adtof-gui).
- Tempo map/quantization: [CPJKU/beat_this](https://github.com/CPJKU/beat_this) (ISMIR 2024, MIT, `pip install beat-this`, beats+downbeats, madmom optional).
- Engraving: music21 → MusicXML → MuseScore Studio 4.5.
- Pros: each piece is the best-in-class, all pip-installable in 2026. Cons: you write the glue (onset→grid quantization, GM percussion→notation mapping).

**4. YourMT3+ (mimbres) — if you want the whole band, not just drums**
[github.com/mimbres/YourMT3](https://github.com/mimbres/YourMT3) — multi-instrument transformer transcription (MLSP 2024), HuggingFace Spaces demo with free GPU. Includes drums but drum-specific accuracy is below dedicated ADT models; useful for context tracks. The original [magenta/mt3](https://github.com/magenta/mt3) is stale with a chronically broken Colab.

**5. Gary-nope/AI-Drum-Transcriber-Workflow** — [documented zero-cost workflow](https://github.com/Gary-nope/AI-Drum-Transcriber-Workflow) (Demucs v4 on free Colab GPU / UVR5 locally, then DAW drum-trigger transcription); bilingual CN/EN docs; more a recipe than a tool.

## Full inventory

### 1. Dedicated ADT models/tools
| Project | Status | Notes |
|---|---|---|
| [ADTOF](https://github.com/MZehren/ADTOF) (MZehren) | Original: low activity (8 commits), TF/Keras, Python 3.10 tested | The reference model for full-mix ADT; pretrained 5-class models; CC BY-NC-SA 4.0; dataset (359 h) on [Zenodo](https://zenodo.org/records/10084511) by request. Use the PyTorch port instead. |
| [ADTOF-pytorch](https://github.com/xavriley/ADTOF-pytorch) | Active 2025 | Converted weights, minimal deps; the practical way to run ADTOF today. |
| [Omnizart](https://github.com/Music-and-Culture-Technology-Lab/omnizart) | PyPI 0.6.3 released May 31, 2026 (packaging revived after years of bit-rot) | But the drum model itself has acknowledged "unknown bugs" (training doesn't converge; inference-only checkpoints), 25 open issues; drum quality reputation mediocre. MIT. |
| [ADTLib](https://github.com/CarlSouthall/ADTLib) (Southall) | **Dead** — last release Jan 2018; depends on old TF + madmom | Historic; outputs onsets + auto drum tab (PDF). BSD. |
| Magenta OaF Drums / [E-GMD](https://magenta.tensorflow.org/oaf-drums) | **Archived** — magenta/magenta repo archived Jan 6, 2026, read-only; TF1-era code hard to run | E-GMD checkpoint still downloadable; velocity estimation was its strength. |
| [DrummerScore](https://github.com/skittree/DrummerScore) | Modest (MIT, 31 stars, notebook-driven) | Demucs + custom PyTorch model → labeled MIDI; FastAPI UI. |
| [AnNOTEator](https://github.com/cb-42/AnNOTEator) | 2022 capstone, unmaintained | Demucs + CNN → sheet music; write-up on [Medium](https://medium.com/@stanley_hung/the-annoteators-transcribe-drum-parts-to-sheet-music-with-python-b0fce4bb3200). |
| Newer research (2025-2026, watch for code) | — | [Noise-to-Notes diffusion ADT](https://arxiv.org/html/2509.21739v1); [STAR Drums dataset (TISMIR)](https://transactions.ismir.net/articles/10.5334/tismir.244); [synthetic-data ADT, arXiv 2601.09520](https://arxiv.org/html/2601.09520); [ADT_STR](https://github.com/pier-maker92/ADT_STR); [2025 AMT Challenge](https://arxiv.org/html/2603.27528v1). |
| DrumScript ([repo](https://github.com/DrumScript/DrumScript), [PyPI](https://libraries.io/pypi/drumscript)) | **Caution** | Claims Demucs wrapper + PDF/MIDI/MusicXML export, but exists as near-identical repos under multiple accounts with marketing-heavy READMEs — looks AI-generated/unverified; treat skeptically until tested. |

### 2. Source separation (preprocessing)
- **Demucs/htdemucs**: [facebookresearch/demucs](https://github.com/facebookresearch/demucs) **archived Jan 1, 2025**; successor fork [adefossez/demucs](https://github.com/adefossez/demucs) is bugfix-only. Still the default drums-stem extractor; pip-installable.
- **[python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator)**: actively maintained, `pip install audio-separator[gpu]`, CLI + library, auto-downloads UVR-family models (MDX-Net, VR, MDXC, Demucs). The practical replacement for the UVR GUI in scripts.
- **[drumsep (inagoy)](https://github.com/inagoy/drumsep)**: hybrid-Demucs model splitting a drum stem into kick/snare/toms/cymbals (4 stems). MIT, Colab + Linux script, 2022 thesis model; mirrored at [HF vincewin/drumsep](https://huggingface.co/vincewin/drumsep). Note the unrelated [cukas/drumsep](https://github.com/cukas/drumsep) (non-ML DSP, 5 groups).
- **MDX23C DrumSep 6-stem** (kick/snare/toms/hh/ride/crash): community UVR-format model, usable via python-audio-separator or [MVSEP](https://mvsep.com/algorithms/31); the one drum2midi uses for ride/crash and velocity.
- **[LarsNet](https://github.com/polimi-ispl/larsnet)** (Politecnico di Milano): 5-stem drum demixing U-Nets trained on **StemGMD** (1224 h); checkpoints CC BY-NC 4.0; also a LARS VST3 plug-in. Research-grade; community consensus is MDX23C drumsep sounds cleaner.

### 3. Beat/downbeat tracking for quantization
- **[beat_this](https://github.com/CPJKU/beat_this)** (ISMIR 2024, CPJKU): current best; MIT incl. weights; `pip install beat-this`; DBN post-processing optional (needs madmom). A [C++ port](https://github.com/mosynthkey/beat_this_cpp) exists.
- **[madmom](https://github.com/CPJKU/madmom)**: effectively unmaintained — PyPI stuck at 0.16.1 (Nov 2018), broken on Python ≥3.10 without source-install patches ([beat_this issue #9](https://github.com/CPJKU/beat_this/issues/9)); community compat forks exist. Its DBNBeatTracker is still a common fallback.
- **[BeatNet](https://github.com/mjhydri/BeatNet)** (ISMIR 2021): real-time beat/downbeat/tempo/meter; drags in madmom/pyaudio; use if you need streaming.
- **librosa**: fine for rough tempo, not competitive for downbeats.

### 4. MIDI → drum sheet music
- **MuseScore Studio 4.5 (2025)**: percussion system fully revamped (new percussion panel, "Customize Kit", better input) — see [Scoring Notes](https://www.scoringnotes.com/news/musescore-studio-4-5/). But **raw drum-MIDI import remains weak**: files import as piano/grand staff, noteheads/positions wrong, open/closed hi-hat both exported as note 42 in some versions ([forum reports](https://musescore.org/en/node/364023), [node/366882](https://musescore.org/en/node/366882)). The reliable route is generating **MusicXML with explicit percussion mapping (music21)** rather than importing MIDI.
- **music21**: MIT, can build percussion staves/unpitched notes and export MusicXML — what DrumLab uses.
- **LilyPond**: `\drummode` + `DrumStaff` gives excellent engraving ([docs](https://lilypond.org/doc/v2.26/Documentation/notation/common-notation-for-percussion)); but no good automatic drum-MIDI→drummode converter (midi2ly doesn't handle drum staffs well) — you'd generate `.ly` yourself; Frescobaldi is just the editor.
- **[GrooveScribe](https://github.com/montulli/GrooveScribe)**: browser drum-notation authoring/practice tool (ABC-based rendering, MIDI playback); the montulli fork is actively maintained; hosted at [mikeslessons.com/gscribe](http://www.mikeslessons.com/gscribe/). Great for editing/sharing grooves, but it's an authoring tool, not a MIDI importer.

### 5. Commercial references (brief)
[Francis' Drumming Blog comparison, updated June 2026](https://francisdrummingblog.com/2024/01/23/ai-generative-drum-transcriptions/): **Drumscrib** (~€2-3/song) best of the paid crop — OK for beginner/intermediate songs, fails on advanced/odd meters; **PlayDrumsOnline** acceptable for easy songs, hallucinates; **Klangio Drum2Notes** rated "totally inaccurate" there despite a 2025 model update; **Moises** used mainly as a stem-isolator front end; ReStem 2 Pro was outscored by open-source drum2midi. Takeaway: commercial tools hold no clear accuracy lead over the open ADTOF+drumsep stack.

### 6. Known accuracy limitations (community + ISMIR 2025)
Per the [ISMIR 2025 study on ADT performance limits](https://ismir2025program.ismir.net/poster_130.html) and drum2midi's benchmarks: simultaneous onsets are the dominant error source (near-perfect transcription when they're removed); cymbal classes are weakest (hi-hat vs ride confusion, open vs closed hi-hat); toms are the worst class in practice (drum2midi toms F1 0.589 vs kick 0.960); ghost notes/velocity need stem-based loudness estimation; cymbal chokes, flams/drags, and odd meters are essentially untranscribed. Expect every output to need manual cleanup in MuseScore.

### yt-dlp in 2026
Still works for most public YouTube content, but 2025-2026 YouTube changes (SABR-only formats, PoToken requirements) cause periodic breakage; you now often need a current release, a PoToken provider plugin, and browser cookies.

**Bottom line**: the 2026 sweet spot is **drum2midi** (or its components: htdemucs/audio-separator → ADTOF-pytorch → MDX23C drumsep for velocity/articulation) plus **beat_this** for the tempo grid, then **music21 → MusicXML → MuseScore 4.5** for engraving — with DrumLab as the ready-made GUI version of the same stack. Omnizart, ADTLib, Magenta OaF, and MT3 are legacy/archived paths not worth building on.
