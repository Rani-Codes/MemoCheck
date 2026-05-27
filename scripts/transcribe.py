"""
Transcribe audio files to text using mlx-whisper (local, Apple Silicon).

Usage:
    python scripts/transcribe.py data/audio/memo_001.m4a
    python scripts/transcribe.py data/audio/
    python scripts/transcribe.py data/audio/ --model small

    # Highest quality (requires ~4-6GB RAM):
    python scripts/transcribe.py data/audio/ --model large

    # Override output directory:
    python scripts/transcribe.py data/audio/ --output-dir some/other/dir

Output (per audio file):
    data/transcripts/<stem>.txt  -- raw transcript (editable for ASR corrections)
    data/transcripts/<stem>.json -- stub test case with id, transcript, and
                                    memo_recorded_at pre-filled; labeler fills
                                    in `category` and the `ground_truth` body.

The .json stub is NOT overwritten if it already exists, so re-running on a
labeled directory is safe. Delete the .json by hand if you want it regenerated.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

import mlx_whisper

SUPPORTED_EXTENSIONS = {".m4a", ".mp3", ".wav", ".webm", ".mp4", ".mpeg", ".mpga", ".ogg"}

# Models download from HuggingFace on first run and are cached locally.
# tiny (~75MB): fastest, lower accuracy -- good for quick tests
# base (~150MB): recommended default -- fast, accurate for clear speech
# small (~480MB): better accuracy for noisy/accented audio
# medium (~1.5GB): high accuracy, noticeably slower
# large (~2.9GB): highest accuracy, requires more RAM/processing
MODEL_REPOS = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large": "mlx-community/whisper-large-v3-mlx",
}
DEFAULT_MODEL = "base"
DEFAULT_OUTPUT_DIR = Path("data/transcripts")


def transcribe_file(audio_path: Path, model_repo: str) -> str:
    result = mlx_whisper.transcribe(str(audio_path), path_or_hf_repo=model_repo)
    return result["text"].strip()


def recording_timestamp(audio_path: Path) -> str:
    """Return the audio file's creation timestamp as a TZ-aware ISO 8601 string
    in the *local* timezone (with explicit UTC offset, e.g. -04:00).

    Uses st_birthtime on macOS (the recording's actual creation moment).
    Falls back to st_mtime on filesystems without birth time support.
    """
    stat = audio_path.stat()
    ts = getattr(stat, "st_birthtime", stat.st_mtime)
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def write_stub_json(audio_path: Path, transcript: str, output_dir: Path) -> Path | None:
    """Write a stub TestCase JSON next to the .txt. Returns the path if a new
    file was created, or None if a labeled JSON already exists (we never
    overwrite labeler work)."""
    out_path = output_dir / f"{audio_path.stem}.json"
    if out_path.exists():
        return None
    stub = {
        "id": audio_path.stem,
        "transcript": transcript,
        "memo_recorded_at": recording_timestamp(audio_path),
        "ground_truth": {
            "todos": [],
            "events": [],
            "reminders": [],
            "notes": [],
        },
    }
    out_path.write_text(json.dumps(stub, indent=2) + "\n")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe audio files with local mlx-whisper.")
    parser.add_argument("target", help="Audio file or directory")
    parser.add_argument(
        "--model",
        choices=list(MODEL_REPOS),
        default=DEFAULT_MODEL,
        help=f"Whisper model size (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to write .txt transcripts to (default: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()

    target = Path(args.target)
    model_repo = MODEL_REPOS[args.model]
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if target.is_file():
        paths = [target]
    elif target.is_dir():
        paths = [p for p in sorted(target.iterdir()) if p.suffix in SUPPORTED_EXTENSIONS]
    else:
        print(f"Path not found: {target}")
        raise SystemExit(1)

    print(f"Using model: {model_repo}")
    print(f"Writing transcripts to: {output_dir}")
    for audio_path in paths:
        print(f"Transcribing {audio_path.name}...")
        transcript = transcribe_file(audio_path, model_repo)
        txt_path = output_dir / f"{audio_path.stem}.txt"
        txt_path.write_text(transcript)
        print(f"  Saved transcript to {txt_path}")
        print(f"  Transcript: {transcript[:80]}...")
        stub_path = write_stub_json(audio_path, transcript, output_dir)
        if stub_path is None:
            print(f"  Stub JSON already exists at {output_dir / f'{audio_path.stem}.json'}, leaving it alone")
        else:
            print(f"  Wrote stub JSON to {stub_path}")


if __name__ == "__main__":
    main()