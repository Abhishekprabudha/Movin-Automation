# MOVIN Automation Video — Colab Compression + en-GB-RyanNeural GitHub Workflow

This repo is designed for the issue we hit: the source screen-recording zip is too large for GitHub web upload.

Use the included Colab notebook first to compress the source screen recording into a small `source_video.zip`, then upload that small file to GitHub and run the workflow to create the final 2–3 minute Ryan Neural narrated video.

## What is inside

- `colab/MOVIN_Compress_Video_For_GitHub_Upload.ipynb` — Google Colab notebook to compress the large input video zip.
- `scripts/compress_video_for_github.py` — the same compression logic as a standalone Python script.
- `.github/workflows/build-video.yml` — GitHub Actions workflow to generate the final MP4 with `en-GB-RyanNeural`.
- `scripts/build_video.py` — extracts/transcribes narration or uses the curated script, creates Ryan Neural MP3, paces the video, and exports final MP4.
- `narration/curated_2_3_min.md` — fallback 2–3 minute executive narration for MOVIN automation.

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

`SPEED_TO_SECONDS = 0` preserves the original narration timing. This is recommended because the GitHub workflow can then transcribe and revoice the same narration in `en-GB-RyanNeural` and pace the final output to 2–3 minutes.

Use `SPEED_TO_SECONDS = 150` only when you want Colab to also create a short visual preview. For source transcription, keep it at `0`.

## Step 2 — Upload compressed input to GitHub

In the GitHub web UI, upload the Colab output here:

```text
input/source_video.zip
```

This file should be under ~22 MB by default, so GitHub web upload should accept it.

## Step 3 — Run the GitHub workflow

1. Go to **Actions**.
2. Select **Build Ryan Narrated MOVIN Video**.
3. Click **Run workflow**.
4. Keep defaults for a 150-second executive cut:

```text
narration_mode = source_transcript
voice = en-GB-RyanNeural
target_seconds = 150
whisper_model = base
video_speed = 1.0
```

Set `video_speed` below `1.0` to slow the finished video down, or above `1.0` to speed it up. For example, `0.5` creates a half-speed output and `2.0` creates a double-speed output.

5. Download the artifact named `movin-ryan-neural-final-video`.

## Workflow outputs

The action uploads:

- `final_movin_ryan_neural.mp4` — final paced 2–3 minute video
- `narration_en_gb_ryan.mp3` — Ryan Neural narration audio
- `narration_text_used.txt` — transcript/script used
- `build_manifest.json` — duration, speed, mode and configuration details

## Local compression alternative

```bash
python scripts/compress_video_for_github.py \
  --input "Screen Recording 2026-07-06 142038.zip" \
  --target-mb 22 \
  --height 720 \
  --output-dir movin_compressed
```

Upload `movin_compressed/source_video.zip` to GitHub at `input/source_video.zip`.
