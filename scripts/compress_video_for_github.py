#!/usr/bin/env python3
"""Compress a large screen-recording zip/video into a GitHub-web-upload-friendly source_video.zip.

Designed for Google Colab, but also works locally anywhere FFmpeg is installed.

Typical use in Colab:
    python scripts/compress_video_for_github.py \
        --input "/content/Screen Recording 2026-07-06 142038.zip" \
        --target-mb 22 \
        --height 720 \
        --output-dir /content/movin_compressed

Outputs:
    /content/movin_compressed/source_video.mp4
    /content/movin_compressed/source_video.zip
    /content/movin_compressed/compression_manifest.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print("\n$", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, check=check)


def capture(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def ensure_ffmpeg() -> None:
    for binary in ("ffmpeg", "ffprobe"):
        if not shutil.which(binary):
            raise RuntimeError(f"{binary} not found. In Colab, run: !apt-get update -qq && !apt-get install -y -qq ffmpeg")


def ffprobe_duration(path: Path) -> float:
    out = capture([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ])
    return float(out)


def has_audio(path: Path) -> bool:
    try:
        out = capture([
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            str(path),
        ])
        return bool(out.strip())
    except Exception:
        return False


def atempo_chain(factor: float) -> str:
    if factor <= 0:
        raise ValueError("Tempo factor must be positive")
    parts: list[float] = []
    remaining = factor
    while remaining > 2.0:
        parts.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        parts.append(0.5)
        remaining /= 0.5
    parts.append(remaining)
    return ",".join(f"atempo={p:.6f}" for p in parts)


def extract_video(input_path: Path, work_dir: Path) -> Path:
    if input_path.suffix.lower() in VIDEO_EXTS:
        return input_path
    if input_path.suffix.lower() != ".zip":
        raise ValueError(f"Unsupported input type: {input_path.suffix}. Provide a video file or .zip containing a video.")

    extract_dir = work_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(input_path) as zf:
        members = [m for m in zf.namelist() if m.lower().endswith(VIDEO_EXTS) and not m.endswith("/")]
        if not members:
            raise FileNotFoundError(f"No video file found inside {input_path}")
        # Prefer the largest video if there are multiple clips.
        member = sorted(members, key=lambda m: zf.getinfo(m).file_size, reverse=True)[0]
        print(f"Extracting video from zip: {member}")
        zf.extract(member, extract_dir)
        return extract_dir / member


def calculate_video_kbps(duration_s: float, target_mb: float, audio_kbps: int, safety: float = 0.90) -> int:
    target_total_kbits = target_mb * 8192 * safety
    total_kbps = target_total_kbits / max(duration_s, 1)
    video_kbps = int(total_kbps - audio_kbps)
    return max(video_kbps, 80)


def zip_output(mp4_path: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.write(mp4_path, arcname="source_video.mp4")


def compress_once(
    source: Path,
    out_mp4: Path,
    *,
    height: int,
    fps: int,
    video_kbps: int,
    audio_kbps: int,
    speed_to_seconds: float | None,
) -> None:
    duration = ffprobe_duration(source)
    video_filters = [f"scale=-2:min({height}\\,ih)", f"fps={fps}", "format=yuv420p"]
    audio_filters: list[str] = []

    if speed_to_seconds and speed_to_seconds > 0 and abs(duration - speed_to_seconds) > 1:
        speed = duration / speed_to_seconds
        video_filters.insert(0, f"setpts=PTS/{speed:.8f}")
        if has_audio(source):
            audio_filters.append(atempo_chain(speed))
        print(f"Speed mode ON: {duration:.1f}s -> {speed_to_seconds:.1f}s, speed factor {speed:.3f}x")

    vf = ",".join(video_filters)
    af = ",".join(audio_filters) if audio_filters else None

    passlog = str(out_mp4.with_suffix(".ffmpeg2pass"))
    null_target = "NUL" if os.name == "nt" else "/dev/null"

    # Pass 1: video only.
    run([
        "ffmpeg", "-y",
        "-i", str(source),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "slow",
        "-b:v", f"{video_kbps}k",
        "-pass", "1",
        "-passlogfile", passlog,
        "-an",
        "-f", "mp4",
        null_target,
    ])

    # Pass 2: video + audio if present.
    cmd = [
        "ffmpeg", "-y",
        "-i", str(source),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "slow",
        "-b:v", f"{video_kbps}k",
        "-pass", "2",
        "-passlogfile", passlog,
    ]
    if has_audio(source):
        if af:
            cmd += ["-af", af]
        cmd += ["-c:a", "aac", "-b:a", f"{audio_kbps}k"]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", str(out_mp4)]
    run(cmd)

    # Clean two-pass logs.
    for p in out_mp4.parent.glob(out_mp4.with_suffix(".ffmpeg2pass").name + "*"):
        try:
            p.unlink()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Compress MOVIN video for GitHub web upload")
    parser.add_argument("--input", required=True, help="Path to .zip or video file")
    parser.add_argument("--output-dir", default="movin_compressed", help="Folder for compressed outputs")
    parser.add_argument("--target-mb", type=float, default=22.0, help="Target size for source_video.zip; keep <= 24 MB for GitHub web upload")
    parser.add_argument("--height", type=int, default=720, help="Max output height, e.g. 720, 540, 480")
    parser.add_argument("--fps", type=int, default=24, help="Output FPS")
    parser.add_argument("--audio-kbps", type=int, default=48, help="Audio bitrate; 48 is enough for speech")
    parser.add_argument("--speed-to-seconds", type=float, default=0, help="Optional: speed video to this duration. Use 0 to preserve original narration timing.")
    args = parser.parse_args()

    ensure_ffmpeg()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    source = extract_video(input_path, work_dir)
    source_duration = ffprobe_duration(source)
    source_size_mb = source.stat().st_size / 1024 / 1024
    print(f"Source: {source}")
    print(f"Source duration: {source_duration:.2f}s")
    print(f"Source size: {source_size_mb:.2f} MB")

    # If speed mode is on, bitrate should be calculated against the shorter final duration.
    bitrate_duration = args.speed_to_seconds if args.speed_to_seconds and args.speed_to_seconds > 0 else source_duration

    attempts = []
    current_height = args.height
    target_mb = args.target_mb
    final_mp4 = out_dir / "source_video.mp4"
    final_zip = out_dir / "source_video.zip"

    for attempt in range(1, 5):
        video_kbps = calculate_video_kbps(bitrate_duration, target_mb, args.audio_kbps, safety=0.86 - (attempt - 1) * 0.04)
        print(f"\nAttempt {attempt}: height={current_height}, fps={args.fps}, video={video_kbps} kbps, audio={args.audio_kbps} kbps")
        compress_once(
            source,
            final_mp4,
            height=current_height,
            fps=args.fps,
            video_kbps=video_kbps,
            audio_kbps=args.audio_kbps,
            speed_to_seconds=args.speed_to_seconds if args.speed_to_seconds > 0 else None,
        )
        zip_output(final_mp4, final_zip)
        mp4_mb = final_mp4.stat().st_size / 1024 / 1024
        zip_mb = final_zip.stat().st_size / 1024 / 1024
        attempts.append({"attempt": attempt, "height": current_height, "video_kbps": video_kbps, "mp4_mb": round(mp4_mb, 3), "zip_mb": round(zip_mb, 3)})
        print(f"Compressed MP4: {mp4_mb:.2f} MB")
        print(f"Compressed ZIP: {zip_mb:.2f} MB")
        if zip_mb <= target_mb:
            break
        current_height = max(360, int(current_height * 0.75) // 2 * 2)

    manifest = {
        "input": str(input_path),
        "source_duration_seconds": round(source_duration, 3),
        "source_size_mb": round(source_size_mb, 3),
        "target_zip_mb": target_mb,
        "final_mp4": str(final_mp4),
        "final_zip": str(final_zip),
        "final_mp4_mb": round(final_mp4.stat().st_size / 1024 / 1024, 3),
        "final_zip_mb": round(final_zip.stat().st_size / 1024 / 1024, 3),
        "speed_to_seconds": args.speed_to_seconds if args.speed_to_seconds > 0 else None,
        "attempts": attempts,
        "github_next_step": "Upload source_video.zip to input/source_video.zip in the GitHub repo, then run the Build Ryan Narrated MOVIN Video workflow.",
    }
    (out_dir / "compression_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("\nDONE")
    print(f"Upload this file to GitHub: {final_zip}")
    print(f"Manifest: {out_dir / 'compression_manifest.json'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
