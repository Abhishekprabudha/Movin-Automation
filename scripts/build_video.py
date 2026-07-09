#!/usr/bin/env python3
"""Build a 6-minute MOVIN narrated video with en-GB-RyanNeural.

Modes:
- source_transcript: transcribe the source video's existing audio with Whisper, then revoice it.
- curated_script: use narration/curated_2_3_min.md.
- repo_text: use a checked-in narration text file.
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


def get_narration_text(mode: str, video: Path, whisper_model: str, narration_text_file: Path) -> str:
    if mode == "curated_script":
        script_path = NARRATION / "curated_2_3_min.md"
        return clean_markdown_text(script_path.read_text(encoding="utf-8"))

    if mode == "repo_text":
        if not narration_text_file.is_absolute():
            narration_text_file = ROOT / narration_text_file
        if not narration_text_file.exists():
            raise FileNotFoundError(f"Narration text file not found: {narration_text_file}")
        text = clean_markdown_text(narration_text_file.read_text(encoding="utf-8"))
        if len(text) < 30:
            raise RuntimeError(f"Narration text file is too short: {narration_text_file}")
        return text

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




def validate_audio_file(path: Path, provider: str) -> None:
    if not path.exists():
        raise RuntimeError(f"{provider} TTS did not create {path}")
    size = path.stat().st_size
    if size < 1024:
        raise RuntimeError(f"{provider} TTS created an invalid or empty audio file at {path} ({size} bytes)")


async def synthesize_edge_chunk(text: str, path: Path, voice: str, rate: str) -> None:
    import edge_tts  # type: ignore
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(str(path))
    validate_audio_file(path, "Edge")


def azure_rate_to_percent(rate: str) -> str:
    value = rate.strip()
    if not value:
        return "+0%"
    if value.endswith("%"):
        return value
    return f"{value}%"


def synthesize_azure_chunk(text: str, path: Path, voice: str, rate: str) -> None:
    import azure.cognitiveservices.speech as speechsdk  # type: ignore

    key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION")
    endpoint = os.environ.get("AZURE_SPEECH_ENDPOINT")

    if endpoint:
        speech_config = (
            speechsdk.SpeechConfig(subscription=key, endpoint=endpoint)
            if key
            else speechsdk.SpeechConfig(endpoint=endpoint)
        )
    elif key and region:
        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
    else:
        raise RuntimeError("Azure TTS requires AZURE_SPEECH_KEY plus AZURE_SPEECH_REGION, or AZURE_SPEECH_ENDPOINT.")

    speech_config.speech_synthesis_voice_name = voice
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
    )
    audio_config = speechsdk.audio.AudioOutputConfig(filename=str(path))
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    ssml = (
        "<speak version='1.0' xml:lang='en-GB' xmlns='http://www.w3.org/2001/10/synthesis' "
        "xmlns:mstts='https://www.w3.org/2001/mstts'>"
        f"<voice name='{voice}'><prosody rate='{azure_rate_to_percent(rate)}'>{escape_ssml(text)}</prosody></voice>"
        "</speak>"
    )
    result = synthesizer.speak_ssml_async(ssml).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        details = (
            speechsdk.CancellationDetails(result)
            if result.reason == speechsdk.ResultReason.Canceled
            else None
        )
        message = details.error_details if details else str(result.reason)
        raise RuntimeError(f"Azure TTS failed: {message}")
    validate_audio_file(path, "Azure")


def escape_ssml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def concat_audio(chunks: list[Path], out: Path) -> None:
    if len(chunks) == 1:
        shutil.copyfile(chunks[0], out)
        return
    concat_file = WORK / "audio_concat.txt"
    concat_file.write_text("\n".join(f"file '{p.as_posix()}'" for p in chunks), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(out)])


def synthesize_tts_with_provider(text: str, voice: str, rate: str, provider: str) -> Path:
    print(f"Synthesising narration with {provider} TTS, voice {voice}, rate {rate}")
    chunks = split_text(text)
    audio_parts: list[Path] = []
    for i, chunk in enumerate(chunks, start=1):
        out = WORK / f"tts_{provider}_part_{i:02d}.mp3"
        if provider == "edge":
            asyncio.run(synthesize_edge_chunk(chunk, out, voice, rate))
        elif provider == "azure":
            synthesize_azure_chunk(chunk, out, voice, rate)
        else:
            raise ValueError(f"Unsupported TTS provider: {provider}")
        audio_parts.append(out)
    tts_out = OUTPUT / "narration_en_gb_ryan.mp3"
    concat_audio(audio_parts, tts_out)
    validate_audio_file(tts_out, provider.capitalize())
    return tts_out


def synthesize_tts(text: str, voice: str, rate: str, provider: str) -> tuple[Path, str]:
    providers = ["edge", "azure"] if provider == "auto" else [provider]
    errors: list[str] = []
    for candidate in providers:
        try:
            return synthesize_tts_with_provider(text, voice, rate, candidate), candidate
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
            print(f"WARNING: {candidate} TTS failed: {exc}", file=sys.stderr)
    joined = "; ".join(errors)
    raise RuntimeError(f"All configured TTS providers failed. {joined}")


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


def fit_audio_to_window(audio: Path, target_seconds: float, min_seconds: float = 360.0, max_seconds: float = 360.0) -> tuple[Path, float, float]:
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
        print(f"Audio is {duration:.2f}s; padding {pad:.2f}s silence to reach {min_seconds:.0f}s")
        run(["ffmpeg", "-y", "-i", str(audio), "-af", f"apad=pad_dur={pad:.3f}", "-t", f"{min_seconds:.3f}", "-c:a", "aac", "-b:a", "160k", str(final_audio)])
        return final_audio, probe_duration(final_audio), 1.0

    shutil.copyfile(audio, final_audio)
    return final_audio, duration, 1.0


def retime_audio(audio: Path, speed: float) -> tuple[Path, float]:
    """Adjust narration playback speed before the video is paced to match it."""
    if speed <= 0:
        raise ValueError("Video speed must be positive")

    retimed_audio = WORK / "narration_retimed.m4a"
    if math.isclose(speed, 1.0):
        shutil.copyfile(audio, retimed_audio)
    else:
        filt = atempo_filter(speed)
        print(f"Retiming narration audio with video speed {speed:.3f}x")
        run(["ffmpeg", "-y", "-i", str(audio), "-filter:a", filt, "-c:a", "aac", "-b:a", "160k", str(retimed_audio)])
    return retimed_audio, probe_duration(retimed_audio)


def resolve_repo_path(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else ROOT / path


def prepare_existing_mp3(mp3_path: Path) -> Path:
    if not mp3_path.exists():
        raise FileNotFoundError(f"Narration MP3 file not found: {mp3_path}")
    validate_audio_file(mp3_path, "Existing MP3")
    out = OUTPUT / "narration_en_gb_ryan.mp3"
    if mp3_path.resolve() != out.resolve():
        shutil.copyfile(mp3_path, out)
    return out


def build_video(video: Path, audio: Path, final_duration: float, crf: int) -> Path:
    source_duration = probe_duration(video)
    speed = source_duration / final_duration
    out = OUTPUT / "final_movin_ryan_neural.mp4"
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
        "tts_provider_requested": args.tts_provider,
        "tts_provider_used": args.tts_provider_used,
        "narration_text_file": args.narration_text_file if args.narration_mode == "repo_text" else None,
        "narration_mp3_file": args.narration_mp3_file if args.narration_mode == "existing_mp3" else None,
        "target_seconds": args.target_seconds,
        "source_video": str(video),
        "source_video_duration_seconds": round(source_duration, 3),
        "raw_tts_duration_seconds": round(raw_audio_duration, 3),
        "fitted_audio_duration_seconds": round(fitted_audio_duration, 3),
        "final_audio_duration_seconds": round(final_audio_duration, 3),
        "audio_speed_factor": round(audio_speed_factor, 4),
        "video_speed_multiplier": round(args.video_speed, 4),
        "video_speed_factor": round(source_duration / final_audio_duration, 4),
        "final_video": str(final_video),
        "narration_character_count": len(text),
        "narration_word_count": len(text.split()),
    }
    (OUTPUT / "build_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--narration-mode", choices=["source_transcript", "curated_script", "repo_text", "existing_mp3"], default="source_transcript")
    parser.add_argument("--target-seconds", type=float, default=360.0)
    parser.add_argument("--voice", default="en-GB-RyanNeural")
    parser.add_argument(
        "--tts-provider",
        choices=["auto", "edge", "azure"],
        default="auto",
        help="TTS provider. auto tries Edge first, then Azure if credentials are configured.",
    )
    parser.add_argument("--whisper-model", default="base")
    parser.add_argument("--narration-text-file", default="narration/narration_text.md", help="Repo-relative or absolute text/Markdown file to use when --narration-mode repo_text")
    parser.add_argument("--narration-mp3-file", default="input/narration.mp3", help="Repo-relative or absolute MP3 file to use when --narration-mode existing_mp3")
    parser.add_argument("--tts-rate", default="+0%", help="Edge TTS prosody rate, e.g. +0%%, +10%%, -5%%")
    parser.add_argument("--crf", type=int, default=23)
    parser.add_argument("--video-speed", type=float, default=1.0, help="Playback speed multiplier for the finished video. Use 0.5 for half speed, 2.0 for double speed.")
    args = parser.parse_args()

    WORK.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    video = find_or_extract_video()
    source_duration = probe_duration(video)
    print(f"Source video duration: {source_duration:.2f}s")

    if args.narration_mode == "existing_mp3":
        mp3_path = resolve_repo_path(args.narration_mp3_file)
        text = f"Existing MP3 narration: {mp3_path}"
        (OUTPUT / "narration_text_used.txt").write_text(text + "\n", encoding="utf-8")
        print(f"Using existing narration MP3: {mp3_path}")
        raw_audio = prepare_existing_mp3(mp3_path)
        args.tts_provider_used = "existing_mp3"
    else:
        text = get_narration_text(args.narration_mode, video, args.whisper_model, Path(args.narration_text_file))
        (OUTPUT / "narration_text_used.txt").write_text(text + "\n", encoding="utf-8")
        print(f"Narration: {len(text.split())} words / {len(text)} chars")
        raw_audio, tts_provider_used = synthesize_tts(text, args.voice, args.tts_rate, args.tts_provider)
        args.tts_provider_used = tts_provider_used

    raw_audio_duration = probe_duration(raw_audio)
    if args.narration_mode == "existing_mp3":
        fitted_audio = raw_audio
        fitted_audio_duration = raw_audio_duration
        audio_speed_factor = 1.0
    else:
        fitted_audio, fitted_audio_duration, audio_speed_factor = fit_audio_to_window(raw_audio, args.target_seconds)
    final_audio, final_audio_duration = retime_audio(fitted_audio, args.video_speed)

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
