"""
Transcribe audio files to text using mlx-whisper (local, Apple Silicon).

Usage:
    python scripts/transcribe.py audio/memo_001.m4a
    python scripts/transcribe.py audio/
    python scripts/transcribe.py audio/ --model small
"""
import argparse
from pathlib import Path

import mlx_whisper

SUPPORTED_EXTENSIONS = {".m4a", ".mp3", ".wav", ".webm", ".mp4", ".mpeg", ".mpga", ".ogg"}

# Models download from HuggingFace on first run and are cached locally.
# tiny (~75MB): fastest, lower accuracy -- good for quick tests
# base (~150MB): recommended default -- fast, accurate for clear speech
# small (~480MB): better accuracy for noisy/accented audio
# medium (~1.5GB): highest accuracy, noticeably slower
MODEL_REPOS = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
}
DEFAULT_MODEL = "base"


def transcribe_file(audio_path: Path, model_repo: str) -> str:
    result = mlx_whisper.transcribe(str(audio_path), path_or_hf_repo=model_repo)
    return result["text"].strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe audio files with local mlx-whisper.")
    parser.add_argument("target", help="Audio file or directory")
    parser.add_argument(
        "--model",
        choices=list(MODEL_REPOS),
        default=DEFAULT_MODEL,
        help=f"Whisper model size (default: {DEFAULT_MODEL})",
    )
    args = parser.parse_args()

    target = Path(args.target)
    model_repo = MODEL_REPOS[args.model]

    if target.is_file():
        paths = [target]
    elif target.is_dir():
        paths = [p for p in sorted(target.iterdir()) if p.suffix in SUPPORTED_EXTENSIONS]
    else:
        print(f"Path not found: {target}")
        raise SystemExit(1)

    print(f"Using model: {model_repo}")
    for audio_path in paths:
        print(f"Transcribing {audio_path.name}...")
        transcript = transcribe_file(audio_path, model_repo)
        out_path = audio_path.with_suffix(".txt")
        out_path.write_text(transcript)
        print(f"  Saved to {out_path}")
        print(f"  Transcript: {transcript[:80]}...")


if __name__ == "__main__":
    main()
