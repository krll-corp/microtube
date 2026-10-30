import os
import re
from pathlib import Path

VIDEO_STORAGE_DIR = Path(os.getenv("VIDEO_STORAGE_DIR", "/videos")).resolve()


def video_path(id):
    if re.fullmatch(r"[A-Za-z0-9_-]{8}", id) is None:
        raise ValueError("Invalid video ID")
    path = (VIDEO_STORAGE_DIR / id[:2] / id[2:]).resolve()
    if not path.is_relative_to(VIDEO_STORAGE_DIR):
        raise ValueError("Video path escapes storage directory")
    return path


def find_video(id):
    path = video_path(id)
    if path.is_file():
        return path
    # Existing volumes may still contain files from the flat layout.
    legacy = (VIDEO_STORAGE_DIR / id).resolve()
    if legacy.is_relative_to(VIDEO_STORAGE_DIR) and legacy.is_file():
        return legacy
    return None
