# MOVIN Automation Video — Colab Compression + Nice 2.6x Slowed Neural Narration

This repo is designed for the issue we hit: the source screen-recording zip is too large for GitHub web upload.

Use the included Colab notebook first to compress the source screen recording into a small `source_video.zip`, then upload that small file to GitHub and run the workflow to create the final MOVIN video. The workflow now generates a warmer Microsoft Aria neural voice narration, gently lifts the pitch without changing speed, slows the final narration by 2.6x, and paces the entire video to that newly regenerated slower MP3 so the visuals and voice stay aligned at the smoother pace.

## What is inside

- `colab/MOVIN_Compress_Video_For_GitHub_Upload.ipynb` — Google Colab notebook to compress the large input video zip.
- `scripts/compress_video_for_github.py` — the same compression logic as a standalone Python script.
- `.github/workflows/build-video.yml` — GitHub Actions workflow to generate the final 2.6x-slowed MP4 with a warmer neural voice.
- `scripts/build_video.py` — extracts/transcribes narration or uses the curated script, creates a warmer neural voice MP3, regenerates the slowed narration MP3 at the requested factor, paces the video to that slowed audio, and exports the final MP4.
- `narration/curated_2_3_min.md` — fallback executive narration for MOVIN automation.

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

`SPEED_TO_SECONDS = 0` preserves the original source timing before upload. This is recommended because the GitHub workflow handles the narration, final 2.6x slowdown, regenerated slower MP3, and final video pacing.

Use `SPEED_TO_SECONDS = 150` only when you want Colab to also create a short visual preview. For source transcription, keep it at `0`.

## Step 2 — Upload compressed input to GitHub

In the GitHub web UI, upload the Colab output here:

```text
input/source_video.zip
```

This file should be under ~22 MB by default, so GitHub web upload should accept it.

## Step 3 — Run the GitHub workflow

1. Go to **Actions**.
2. Select **Build Nice Slowed MOVIN Video**.
3. Click **Run workflow**.
4. Keep defaults to generate a warmer, friendlier neural voice and slow both the voice narration and final video by 2.6x:

```text
narration_mode = source_transcript
voice = en-US-AriaNeural
tts_rate = -5%
tts_pitch = +2Hz
target_seconds = 150
slowdown_factor = 2.6
whisper_model = base
```

With these defaults, the narration keeps the same rate and slowdown settings, uses a warmer Aria voice with a slight pitch lift, and is first fitted around the 150-second target and then slowed by 2.6x, so the final MP4 is approximately 390 seconds while the full video and newly regenerated MP3 narration remain synchronized.

5. Download the artifact named `movin-nice-slowed-final-video`.

## Workflow outputs

The action uploads:

- `final_movin_nice_neural_voice.mp4` — final video paced to the 2.6x-slowed neural narration
- `narration_nice_neural_voice.mp3` — delivered neural narration audio regenerated at the 2.6x slower pace
- `narration_text_used.txt` — transcript/script used
- `build_manifest.json` — duration, speed, mode, voice and configuration details

## Local compression alternative

```bash
python scripts/compress_video_for_github.py \
  --input "Screen Recording 2026-07-06 142038.zip" \
  --target-mb 22 \
  --height 720 \
  --output-dir movin_compressed
```

Upload `movin_compressed/source_video.zip` to GitHub at `input/source_video.zip`.
