"""
Transcribe audio files to text using the Whisper API.

Usage:
    python scripts/transcribe.py audio/memo_001.m4a
    python scripts/transcribe.py audio/
"""
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

SUPPORTED_EXTENSIONS = {".m4a", ".mp3", ".wav", ".webm", ".mp4", ".mpeg", ".mpga", ".ogg"}

client = OpenAI()


def transcribe_file(audio_path: Path) -> str:
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="text",
        )
    return result


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/transcribe.py <audio_file_or_directory>")
        sys.exit(1)

    target = Path(sys.argv[1])

    if target.is_file():
        paths = [target]
    elif target.is_dir():
        paths = [p for p in sorted(target.iterdir()) if p.suffix in SUPPORTED_EXTENSIONS]
    else:
        print(f"Path not found: {target}")
        sys.exit(1)

    for audio_path in paths:
        print(f"Transcribing {audio_path.name}...")
        transcript = transcribe_file(audio_path)
        out_path = audio_path.with_suffix(".txt")
        out_path.write_text(transcript)
        print(f"  Saved to {out_path}")
        print(f"  Transcript: {transcript[:80]}...")


if __name__ == "__main__":
    main()
