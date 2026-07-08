# MOVIN Automation Video — Fresh Context-Aligned Voiceover

This repo builds a MOVIN automation video from a compressed source screen recording and a newly generated narration track.

The build no longer reuses, transcribes, slows, or preserves the source video's original narration. Instead, `scripts/build_video.py` treats the source video as the visual timeline, reads the business context in `narration/curated_2_3_min.md`, creates a fresh Microsoft neural voiceover beat-by-beat, pads or lightly fits each beat into its own time slot, exports a new MP3, and muxes that sound track into the final MP4.

## What is inside

- `colab/MOVIN_Compress_Video_For_GitHub_Upload.ipynb` — Google Colab notebook to compress the large input video zip.
- `scripts/compress_video_for_github.py` — the same compression logic as a standalone Python script.
- `.github/workflows/build-video.yml` — GitHub Actions workflow to generate the final fresh-voiceover video.
- `scripts/build_video.py` — extracts the source video, builds a brand-new context-aligned voiceover from the curated narration, exports `fresh_movin_voiceover.mp3`, and produces the final MP4.
- `narration/curated_2_3_min.md` — MOVIN automation context used as the source of the fresh narration.

## Step 1 — Compress the source video in Colab

1. Open Google Colab.
2. Upload `colab/MOVIN_Compress_Video_For_GitHub_Upload.ipynb`.
3. Run the cells.
4. Upload the large video zip when prompted.
5. Download the generated file:

```text
/content/movin_compressed/source_video.zip
```

Recommended Colab settings:

```text
TARGET_MB = 22
HEIGHT = 720
FPS = 24
AUDIO_KBPS = 48
SPEED_TO_SECONDS = 0
```

`SPEED_TO_SECONDS = 0` preserves the original source timing before upload. The GitHub workflow now handles a completely new voiceover and aligns the narration bed to the source video's duration.

## Step 2 — Upload compressed input to GitHub

In the GitHub web UI, upload the Colab output here:

```text
input/source_video.zip
```

This file should be under ~22 MB by default, so GitHub web upload should accept it.

## Step 3 — Run the GitHub workflow

1. Go to **Actions**.
2. Select **Build Fresh MOVIN Voiceover Video**.
3. Click **Run workflow**.
4. Keep defaults to generate a new Ryan neural narration:

```text
voice = en-GB-RyanNeural
tts_rate = -2%
tts_pitch = -1Hz
```

The workflow ignores any spoken source narration, creates fresh audio from `narration/curated_2_3_min.md`, times each narration beat against the video duration, and exports a synchronized final video.

5. Download the artifact named `movin-fresh-voiceover-final-video`.

## Workflow outputs

The action uploads:

- `final_movin_fresh_voiceover.mp4` — final video with the new context-aligned voiceover
- `fresh_movin_voiceover.mp3` — delivered MP3 built from the fresh narration bed
- `narration_text_used.txt` — script generated from the curated MOVIN context
- `build_manifest.json` — voice, timing, beat alignment, and output details

## Local build

```bash
python scripts/build_video.py \
  --voice en-GB-RyanNeural \
  --tts-rate=-2% \
  --tts-pitch=-1Hz
```

## Local compression alternative

```bash
python scripts/compress_video_for_github.py \
  --input "Screen Recording 2026-07-06 142038.zip" \
  --target-mb 22 \
  --height 720 \
  --output-dir movin_compressed
```

Upload `movin_compressed/source_video.zip` to GitHub at `input/source_video.zip`.
