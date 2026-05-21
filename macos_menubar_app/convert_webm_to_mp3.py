#!/usr/bin/env python3
"""Convert .webm files to .mp3, keeping the originals."""

import argparse
import subprocess
import sys
from pathlib import Path

from batch_transcribe import _find_ffmpeg


def convert_webm_to_mp3(input_path: Path, output_path: Path, bitrate: str = "192k") -> None:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        print("Error: ffmpeg not found. Install via `brew install ffmpeg` or `pip install imageio-ffmpeg`.")
        sys.exit(1)

    result = subprocess.run(
        [ffmpeg, "-i", str(input_path), "-vn", "-ab", bitrate, "-y", str(output_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ffmpeg error: {result.stderr[:500]}")
        sys.exit(1)

    print(f"{input_path} -> {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Convert .webm files to .mp3")
    parser.add_argument("paths", nargs="+", help="Files or directories containing .webm files")
    parser.add_argument("--bitrate", default="192k", help="MP3 bitrate (default: 192k)")
    args = parser.parse_args()

    targets: list[Path] = []
    for p in args.paths:
        path = Path(p)
        if path.is_dir():
            targets.extend(sorted(path.glob("*.webm")))
        elif path.is_file() and path.suffix.lower() == ".webm":
            targets.append(path)
        else:
            print(f"Skipping: {p} (not a .webm file or directory)")

    if not targets:
        print("No .webm files found.")
        sys.exit(1)

    print(f"Converting {len(targets)} file(s)...")
    for webm in targets:
        mp3 = webm.with_suffix(".mp3")
        convert_webm_to_mp3(webm, mp3, args.bitrate)

    print("Done.")


if __name__ == "__main__":
    main()
