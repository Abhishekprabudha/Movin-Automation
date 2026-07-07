#!/usr/bin/env python3
"""Build a slowed MOVIN narrated video with a natural Microsoft neural voice.

Modes:
- source_transcript: transcribe the source video's existing audio with Whisper, then revoice it.
- curated_script: use narration/curated_2_3_min.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "input"
WORK = ROOT / "work"
OUTPUT = ROOT / "output"
NARRATION = ROOT / "narration"


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print("\n$", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, check=check)


def capture(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def probe_duration(path: Path) -> float:
    out = capture([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ])
    return float(out)


def find_or_extract_video() -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    candidates = sorted(INPUT.glob("*.mp4")) + sorted(INPUT.glob("*.mov"))
    if candidates:
        print(f"Using video file: {candidates[0]}")
        return candidates[0]

    zips = sorted(INPUT.glob("*.zip"))
    if not zips:
        raise FileNotFoundError("No .mp4/.mov or .zip file found in input/. Add input/source_video.zip or provide source_video_url in GitHub Actions.")

    zip_path = zips[0]
    extract_dir = WORK / "source_video"
    extract_dir.mkdir(parents=True, exist_ok=True)
    print(f"Extracting {zip_path} to {extract_dir}")
    with zipfile.ZipFile(zip_path) as zf:
        video_members = [m for m in zf.namelist() if m.lower().endswith((".mp4", ".mov")) and not m.endswith("/")]
        if not video_members:
            raise FileNotFoundError(f"No MP4/MOV found inside {zip_path}")
        member = video_members[0]
        zf.extract(member, extract_dir)
        video_path = extract_dir / member
        print(f"Extracted video: {video_path}")
        return video_path


def clean_markdown_text(raw: str) -> str:
    text = raw.replace("\r", "\n")
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_audio_for_transcription(video: Path) -> Path:
    audio = WORK / "source_audio_16k.wav"
    run(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(audio)])
    return audio


def transcribe_with_whisper(audio: Path, model_name: str) -> str:
    try:
        import whisper  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Whisper is not installed. Run `pip install openai-whisper` or use --narration-mode curated_script.") from exc

    print(f"Loading Whisper model: {model_name}")
    model = whisper.load_model(model_name)
    print("Transcribing source narration...")
    result = model.transcribe(str(audio), fp16=False, language="en")
    segments = result.get("segments", []) or []
    if segments:
        lines = []
        for seg in segments:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", 0.0))
            txt = str(seg.get("text", "")).strip()
            if txt:
                lines.append(f"[{start:0.1f}-{end:0.1f}] {txt}")
        (OUTPUT / "source_transcript_segments.txt").write_text("\n".join(lines), encoding="utf-8")
    text = str(result.get("text", "")).strip()
    if len(text) < 30:
        raise RuntimeError("Whisper produced too little text. Use curated_script mode or add narration text manually.")
    return text


def get_narration_text(mode: str, video: Path, whisper_model: str) -> str:
    if mode == "curated_script":
        script_path = NARRATION / "curated_2_3_min.md"
        return clean_markdown_text(script_path.read_text(encoding="utf-8"))

    if mode == "source_transcript":
        audio = extract_audio_for_transcription(video)
        text = transcribe_with_whisper(audio, whisper_model)
        return clean_markdown_text(text)

    raise ValueError(f"Unsupported narration mode: {mode}")


def split_text(text: str, max_chars: int = 3600) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    buf = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(buf) + len(sentence) + 1 > max_chars and buf:
            chunks.append(buf.strip())
            buf = sentence
        else:
            buf = f"{buf} {sentence}".strip()
    if buf:
        chunks.append(buf.strip())
    return chunks or [text]


async def synthesize_chunk(text: str, path: Path, voice: str, rate: str) -> None:
    import edge_tts  # type: ignore
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(str(path))


def concat_audio(chunks: list[Path], out: Path) -> None:
    if len(chunks) == 1:
        shutil.copyfile(chunks[0], out)
        return
    concat_file = WORK / "audio_concat.txt"
    concat_file.write_text("\n".join(f"file '{p.as_posix()}'" for p in chunks), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(out)])


def normalize_voice_name(voice: str) -> str:
    """Accept common Ryan voice spellings but send Edge TTS the canonical ID."""
    compact = re.sub(r"[^a-z0-9]", "", voice.lower())
    if compact == "engbryanneural":
        return "en-GB-RyanNeural"
    return voice


def synthesize_tts(text: str, voice: str, rate: str) -> tuple[Path, str]:
    voice = normalize_voice_name(voice)
    print(f"Synthesising narration with {voice}, rate {rate}")
    chunks = split_text(text)
    audio_parts: list[Path] = []
    for i, chunk in enumerate(chunks, start=1):
        out = WORK / f"tts_part_{i:02d}.mp3"
        asyncio.run(synthesize_chunk(chunk, out, voice, rate))
        audio_parts.append(out)
    tts_out = WORK / "narration_neural_voice_raw.mp3"
    concat_audio(audio_parts, tts_out)
    return tts_out, voice


def atempo_filter(factor: float) -> str:
    """FFmpeg atempo high-quality chain. Factors between 0.5 and 2.0 are safest."""
    if factor <= 0:
        raise ValueError("Audio tempo factor must be positive")
    parts = []
    remaining = factor
    while remaining > 2.0:
        parts.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        parts.append(0.5)
        remaining /= 0.5
    parts.append(remaining)
    return ",".join(f"atempo={p:.6f}" for p in parts)


def fit_audio_to_window(audio: Path, target_seconds: float, min_seconds: float = 120.0, max_seconds: float = 180.0) -> tuple[Path, float, float]:
    duration = probe_duration(audio)
    desired = max(min_seconds, min(max_seconds, float(target_seconds)))
    final_audio = WORK / "narration_fitted.m4a"

    if duration > max_seconds:
        factor = duration / desired
        filt = atempo_filter(factor)
        print(f"Audio is {duration:.2f}s; compressing by {factor:.3f}x to ~{desired:.2f}s")
        run(["ffmpeg", "-y", "-i", str(audio), "-filter:a", filt, "-c:a", "aac", "-b:a", "160k", str(final_audio)])
        return final_audio, probe_duration(final_audio), factor

    if duration < min_seconds:
        pad = min_seconds - duration
        print(f"Audio is {duration:.2f}s; padding {pad:.2f}s silence to reach 120s")
        run(["ffmpeg", "-y", "-i", str(audio), "-af", f"apad=pad_dur={pad:.3f}", "-t", f"{min_seconds:.3f}", "-c:a", "aac", "-b:a", "160k", str(final_audio)])
        return final_audio, probe_duration(final_audio), 1.0

    shutil.copyfile(audio, final_audio)
    return final_audio, duration, 1.0


def slow_audio(audio: Path, slowdown_factor: float) -> tuple[Path, float]:
    """Create the delivered MP3 slowed by slowdown_factor while preserving pitch."""
    if slowdown_factor <= 0:
        raise ValueError("Slowdown factor must be positive")

    slowed_audio = OUTPUT / "narration_nice_neural_voice.mp3"
    if math.isclose(slowdown_factor, 1.0):
        shutil.copyfile(audio, slowed_audio)
    else:
        tempo = 1.0 / slowdown_factor
        filt = atempo_filter(tempo)
        print(f"Slowing final narration audio by {slowdown_factor:.3f}x with tempo factor {tempo:.3f}")
        run(["ffmpeg", "-y", "-i", str(audio), "-filter:a", filt, "-c:a", "libmp3lame", "-b:a", "192k", str(slowed_audio)])
    return slowed_audio, probe_duration(slowed_audio)


def build_video(video: Path, audio: Path, final_duration: float, crf: int) -> Path:
    source_duration = probe_duration(video)
    speed = source_duration / final_duration
    out = OUTPUT / "final_movin_nice_neural_voice.mp4"
    # Keep dimensions even; preserve aspect ratio; make it web-friendly.
    vf = f"setpts=PTS/{speed:.8f},fps=30,scale='if(gt(iw,1920),1920,iw)':'-2',format=yuv420p"
    run([
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(audio),
        "-filter_complex", f"[0:v]{vf}[v]",
        "-map", "[v]",
        "-map", "1:a:0",
        "-t", f"{final_duration:.3f}",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", str(crf),
        "-c:a", "aac",
        "-b:a", "160k",
        "-movflags", "+faststart",
        str(out),
    ])
    return out


def write_manifest(args, video: Path, text: str, source_duration: float, raw_audio_duration: float, fitted_audio_duration: float, final_audio_duration: float, audio_speed_factor: float, final_video: Path) -> None:
    manifest = {
        "narration_mode": args.narration_mode,
        "voice": args.voice,
        "tts_rate": args.tts_rate,
        "target_seconds": args.target_seconds,
        "source_video": str(video),
        "source_video_duration_seconds": round(source_duration, 3),
        "raw_tts_duration_seconds": round(raw_audio_duration, 3),
        "fitted_audio_duration_seconds": round(fitted_audio_duration, 3),
        "final_audio_duration_seconds": round(final_audio_duration, 3),
        "audio_fit_speed_factor": round(audio_speed_factor, 4),
        "audio_slowdown_factor": round(args.slowdown_factor, 4),
        "video_speed_factor": round(source_duration / final_audio_duration, 4),
        "final_video": str(final_video),
        "narration_character_count": len(text),
        "narration_word_count": len(text.split()),
    }
    (OUTPUT / "build_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def normalize_argv(argv: list[str]) -> list[str]:
    """Allow negative-looking --tts-rate values such as -5% without requiring equals syntax."""
    normalized: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--tts-rate" and i + 1 < len(argv):
            normalized.append(f"--tts-rate={argv[i + 1]}")
            i += 2
            continue
        normalized.append(arg)
        i += 1
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--narration-mode", choices=["source_transcript", "curated_script"], default="source_transcript")
    parser.add_argument("--target-seconds", type=float, default=150.0)
    parser.add_argument("--voice", default="en-US-JennyNeural")
    parser.add_argument("--whisper-model", default="base")
    parser.add_argument("--tts-rate", default="-5%", help="Edge TTS prosody rate, e.g. +0%%, +10%%, -5%%")
    parser.add_argument("--crf", type=int, default=23)
    parser.add_argument("--slowdown-factor", type=float, default=2.0, help="Slow both the delivered narration and paced video by this factor. 2.0 halves the speed.")
    args = parser.parse_args(normalize_argv(sys.argv[1:]))

    WORK.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    video = find_or_extract_video()
    source_duration = probe_duration(video)
    print(f"Source video duration: {source_duration:.2f}s")

    text = get_narration_text(args.narration_mode, video, args.whisper_model)
    (OUTPUT / "narration_text_used.txt").write_text(text + "\n", encoding="utf-8")
    print(f"Narration: {len(text.split())} words / {len(text)} chars")

    raw_audio, resolved_voice = synthesize_tts(text, args.voice, args.tts_rate)
    args.voice = resolved_voice
    raw_audio_duration = probe_duration(raw_audio)
    fitted_audio, fitted_audio_duration, audio_speed_factor = fit_audio_to_window(raw_audio, args.target_seconds)
    final_audio, final_audio_duration = slow_audio(fitted_audio, args.slowdown_factor)

    final_video = build_video(video, final_audio, final_audio_duration, args.crf)
    write_manifest(args, video, text, source_duration, raw_audio_duration, fitted_audio_duration, final_audio_duration, audio_speed_factor, final_video)

    print("\nDone.")
    print(f"Final video: {final_video}")
    print(f"Final duration: {probe_duration(final_video):.2f}s")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
