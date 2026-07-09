#!/usr/bin/env python3
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
required = [
    '.github/workflows/build-video.yml',
    'scripts/build_video.py',
    'scripts/compress_video_for_github.py',
    'colab/MOVIN_Compress_Video_For_GitHub_Upload.ipynb',
    'requirements.txt',
    'narration/curated_2_3_min.md',
    'narration/narration_text.md',
    'input/README.md',
]
missing = [p for p in required if not (root / p).exists()]
if missing:
    raise SystemExit('Missing files: ' + ', '.join(missing))

for z in root.glob('input/*.zip'):
    with zipfile.ZipFile(z) as zf:
        videos = [n for n in zf.namelist() if n.lower().endswith(('.mp4', '.mov', '.mkv', '.webm'))]
        if not videos:
            raise SystemExit(f'{z} does not contain a video file')
        print('OK: input zip contains', videos[0])

print('OK: repo validation passed')
