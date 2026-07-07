#!/usr/bin/env python3
"""Build a fresh MOVIN voiceover from the narration context and align it to the video.

This builder intentionally does not reuse, transcribe, stretch, or preserve the
source video's spoken narration. It treats the source video as silent visual
context, creates a new structured voiceover from narration/curated_2_3_min.md,
places each narration beat on a timed audio bed, exports a standalone MP3, and
muxes that fresh sound track with the video.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "input"
WORK = ROOT / "work"
OUTPUT = ROOT / "output"
NARRATION = ROOT / "narration"


@dataclass(frozen=True)
class NarrationBeat:
    index: int
    title: str
    text: str
    weight: float


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
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def load_fresh_narration(script_path: Path) -> tuple[str, list[NarrationBeat]]:
    context = clean_markdown_text(script_path.read_text(encoding="utf-8"))
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", context) if p.strip()]
    if not paragraphs:
        raise RuntimeError(f"Narration context is empty: {script_path}")

    titles = [
        "Opportunity and objective",
        "Partnership-led approach",
        "Shipsy-connected automation",
        "Flexible AI agent layer",
        "Customer and operations experience",
        "Measurable outcome",
        "Recommended pilot path",
    ]
    beats: list[NarrationBeat] = []
    for idx, paragraph in enumerate(paragraphs, start=1):
        title = titles[min(idx - 1, len(titles) - 1)]
        words = len(paragraph.split())
        # Extra weight gives short but important transition beats enough screen time.
        beats.append(NarrationBeat(index=idx, title=title, text=paragraph, weight=max(words, 35)))

    fresh_script = "\n\n".join(f"{beat.title}. {beat.text}" for beat in beats)
    return fresh_script, beats


def normalize_voice_name(voice: str) -> str:
    compact = re.sub(r"[^a-z0-9]", "", voice.lower())
    aliases = {
        "aria": "en-US-AriaNeural",
        "arianeural": "en-US-AriaNeural",
        "enusarianeural": "en-US-AriaNeural",
        "jenny": "en-US-JennyNeural",
        "jennyneural": "en-US-JennyNeural",
        "enusjennyneural": "en-US-JennyNeural",
        "guy": "en-US-GuyNeural",
        "guyneural": "en-US-GuyNeural",
        "enusguyneural": "en-US-GuyNeural",
        "ryan": "en-GB-RyanNeural",
        "ryanneural": "en-GB-RyanNeural",
        "engbryanneural": "en-GB-RyanNeural",
    }
    return aliases.get(compact, voice)


async def synthesize_chunk(text: str, path: Path, voice: str, rate: str, pitch: str) -> None:
    import edge_tts  # type: ignore
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(str(path))


def atempo_filter(factor: float) -> str:
    if factor <= 0:
        raise ValueError("Audio tempo factor must be positive")
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


def planned_timeline(beats: list[NarrationBeat], total_duration: float, intro_pause: float, outro_pause: float, gap: float) -> list[tuple[NarrationBeat, float, float]]:
    available = total_duration - intro_pause - outro_pause - gap * max(0, len(beats) - 1)
    minimum = 6.0 * len(beats)
    if available < minimum:
        raise ValueError(f"Video duration {total_duration:.2f}s is too short for {len(beats)} narration beats with pauses")

    total_weight = sum(beat.weight for beat in beats)
    cursor = intro_pause
    timeline: list[tuple[NarrationBeat, float, float]] = []
    for i, beat in enumerate(beats):
        if i == len(beats) - 1:
            duration = max(6.0, total_duration - outro_pause - cursor)
        else:
            duration = max(6.0, available * beat.weight / total_weight)
        timeline.append((beat, cursor, duration))
        cursor += duration + gap
    return timeline


def silence(path: Path, duration: float) -> None:
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100", "-t", f"{duration:.3f}", "-c:a", "aac", "-b:a", "160k", str(path)])


def fit_chunk_to_slot(raw: Path, out: Path, slot_seconds: float) -> dict[str, float | str]:
    raw_duration = probe_duration(raw)
    padded_target = max(1.0, slot_seconds * 0.9)
    speed_factor = raw_duration / padded_target
    if speed_factor > 1.35:
        # Compress only when absolutely needed, keeping voice natural.
        run(["ffmpeg", "-y", "-i", str(raw), "-filter:a", atempo_filter(speed_factor), "-c:a", "aac", "-b:a", "160k", str(out)])
        action = "compressed"
    else:
        run(["ffmpeg", "-y", "-i", str(raw), "-c:a", "aac", "-b:a", "160k", str(out)])
        action = "natural"

    fitted_duration = probe_duration(out)
    if fitted_duration < slot_seconds:
        padded = out.with_name(out.stem + "_slot.m4a")
        pad = slot_seconds - fitted_duration
        run(["ffmpeg", "-y", "-i", str(out), "-af", f"apad=pad_dur={pad:.3f}", "-t", f"{slot_seconds:.3f}", "-c:a", "aac", "-b:a", "160k", str(padded)])
        shutil.move(padded, out)
    elif fitted_duration > slot_seconds:
        trimmed = out.with_name(out.stem + "_slot.m4a")
        run(["ffmpeg", "-y", "-i", str(out), "-t", f"{slot_seconds:.3f}", "-c:a", "aac", "-b:a", "160k", str(trimmed)])
        shutil.move(trimmed, out)
    return {"raw_duration": round(raw_duration, 3), "slot_duration": round(slot_seconds, 3), "fit_action": action}


def concat_audio(parts: list[Path], out: Path) -> None:
    concat_file = WORK / "fresh_audio_concat.txt"
    concat_file.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(out)])


def build_fresh_voiceover(beats: list[NarrationBeat], duration: float, voice: str, rate: str, pitch: str, intro_pause: float, outro_pause: float, gap: float) -> tuple[Path, list[dict[str, object]]]:
    voice = normalize_voice_name(voice)
    print(f"Creating brand-new narration bed with {voice}, rate {rate}, pitch {pitch}")
    timeline = planned_timeline(beats, duration, intro_pause, outro_pause, gap)
    parts: list[Path] = []
    manifest: list[dict[str, object]] = []

    intro = WORK / "beat_00_intro_silence.m4a"
    silence(intro, intro_pause)
    parts.append(intro)

    for beat, start, slot in timeline:
        raw = WORK / f"beat_{beat.index:02d}_raw.mp3"
        fitted = WORK / f"beat_{beat.index:02d}_slot.m4a"
        asyncio.run(synthesize_chunk(beat.text, raw, voice, rate, pitch))
        info = fit_chunk_to_slot(raw, fitted, slot)
        parts.append(fitted)
        manifest.append({"index": beat.index, "title": beat.title, "start": round(start, 3), **info})

    outro = WORK / "beat_99_outro_silence.m4a"
    silence(outro, outro_pause)
    parts.append(outro)

    bed = WORK / "fresh_narration_bed.m4a"
    concat_audio(parts, bed)
    final_mp3 = OUTPUT / "fresh_movin_voiceover.mp3"
    run(["ffmpeg", "-y", "-i", str(bed), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-t", f"{duration:.3f}", "-c:a", "libmp3lame", "-b:a", "192k", str(final_mp3)])
    return final_mp3, manifest


def build_video(video: Path, audio: Path, crf: int) -> Path:
    out = OUTPUT / "final_movin_fresh_voiceover.mp4"
    run([
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(audio),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", str(crf),
        "-vf", "fps=30,scale='if(gt(iw,1920),1920,iw)':'-2',format=yuv420p",
        "-c:a", "aac",
        "-b:a", "160k",
        "-shortest",
        "-movflags", "+faststart",
        str(out),
    ])
    return out


def write_manifest(args, video: Path, script: str, voice: str, source_duration: float, final_audio: Path, final_video: Path, beats: list[dict[str, object]]) -> None:
    manifest = {
        "build_style": "fresh_context_aligned_voiceover",
        "source_audio_policy": "ignored; source narration is not transcribed or reused",
        "voice": voice,
        "tts_rate": args.tts_rate,
        "tts_pitch": args.tts_pitch,
        "source_video": str(video),
        "source_video_duration_seconds": round(source_duration, 3),
        "final_audio": str(final_audio),
        "final_audio_duration_seconds": round(probe_duration(final_audio), 3),
        "final_video": str(final_video),
        "final_video_duration_seconds": round(probe_duration(final_video), 3),
        "narration_character_count": len(script),
        "narration_word_count": len(script.split()),
        "beats": beats,
    }
    (OUTPUT / "build_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def normalize_argv(argv: list[str]) -> list[str]:
    normalized: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in {"--tts-rate", "--tts-pitch"} and i + 1 < len(argv):
            # argparse treats values that begin with '-' as new options when
            # they are passed as the next token. Edge TTS rate/pitch values are
            # commonly negative (for example, -2% and -1Hz), so rewrite both
            # forms to --flag=value before parsing.
            normalized.append(f"{arg}={argv[i + 1]}")
            i += 2
            continue
        normalized.append(arg)
        i += 1
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", default=str(NARRATION / "curated_2_3_min.md"), help="Narration context used to create the fresh voiceover")
    parser.add_argument("--voice", default="en-US-GuyNeural", help="Microsoft neural voice or friendly alias")
    parser.add_argument("--tts-rate", default="-2%", help="Edge TTS prosody rate, e.g. +0%%, +10%%, -2%%")
    parser.add_argument("--tts-pitch", default="-1Hz", help="Edge TTS prosody pitch")
    parser.add_argument("--intro-pause", type=float, default=1.25)
    parser.add_argument("--outro-pause", type=float, default=1.5)
    parser.add_argument("--beat-gap", type=float, default=0.45)
    parser.add_argument("--crf", type=int, default=23)
    # Backward-compatible no-op flags so older manual workflow dispatches fail less often.
    parser.add_argument("--narration-mode", default="fresh_context", help=argparse.SUPPRESS)
    parser.add_argument("--target-seconds", type=float, default=0.0, help=argparse.SUPPRESS)
    parser.add_argument("--slowdown-factor", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument("--whisper-model", default="", help=argparse.SUPPRESS)
    args = parser.parse_args(normalize_argv(sys.argv[1:]))

    WORK.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    video = find_or_extract_video()
    source_duration = probe_duration(video)
    print(f"Source video duration: {source_duration:.2f}s")

    script, beats = load_fresh_narration(Path(args.script))
    (OUTPUT / "narration_text_used.txt").write_text(script + "\n", encoding="utf-8")
    print(f"Fresh narration: {len(script.split())} words / {len(script)} chars / {len(beats)} beats")

    resolved_voice = normalize_voice_name(args.voice)
    final_audio, beat_manifest = build_fresh_voiceover(beats, source_duration, resolved_voice, args.tts_rate, args.tts_pitch, args.intro_pause, args.outro_pause, args.beat_gap)
    final_video = build_video(video, final_audio, args.crf)
    write_manifest(args, video, script, resolved_voice, source_duration, final_audio, final_video, beat_manifest)

    print("\nDone.")
    print(f"Fresh MP3: {final_audio}")
    print(f"Final video: {final_video}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
