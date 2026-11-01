import io
import json
import operator
import os
import re
import shutil
from pathlib import Path

VIDEO_STORAGE_DIR = Path(os.getenv("VIDEO_STORAGE_DIR", "/videos")).resolve()
CHUNK_SIZE = 64 * 1024 * 1024


def video_path(id):
    if re.fullmatch(r"[A-Za-z0-9_-]{8}", id) is None:
        raise ValueError("Invalid video ID")
    path = (VIDEO_STORAGE_DIR / id[:2] / id[2:]).resolve()
    if not path.is_relative_to(VIDEO_STORAGE_DIR):
        raise ValueError("Video path escapes storage directory")
    return path


def find_video(id):
    path = video_path(id)
    if path.is_file() or (path.is_dir() and (path / "manifest.json").is_file()):
        return path
    # Existing volumes may still contain files from the flat layout.
    legacy = (VIDEO_STORAGE_DIR / id).resolve()
    if legacy.is_relative_to(VIDEO_STORAGE_DIR) and legacy.is_file():
        return legacy
    return None


def save_video(id, source):
    path = video_path(id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()
    size, chunks = 0, 0
    try:
        while data := source.read(min(1024 * 1024, CHUNK_SIZE)):
            with (path / f"{chunks:06d}").open("xb") as destination:
                written = 0
                while data:
                    destination.write(data)
                    written += len(data)
                    size += len(data)
                    if written == CHUNK_SIZE:
                        break
                    data = source.read(min(1024 * 1024, CHUNK_SIZE - written))
            chunks += 1
        # Readers discover a video only after its manifest is published.
        manifest = path / ".manifest.tmp"
        manifest.write_text(json.dumps({"size": size, "chunk_size": CHUNK_SIZE, "chunks": chunks}))
        manifest.replace(path / "manifest.json")
        return size
    except BaseException:
        shutil.rmtree(path)
        raise


class VideoFile(io.BufferedIOBase):
    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.position = 0
        if self.path.is_dir():
            manifest = self.path / "manifest.json"
            if manifest.is_symlink():
                raise ValueError("Invalid video manifest")
            try:
                data = json.loads(manifest.read_text())
                self.size, self.chunk_size, chunks = (data[key] for key in ("size", "chunk_size", "chunks"))
            except (KeyError, TypeError) as error:
                raise ValueError("Invalid video manifest") from error
            if any(type(value) is not int for value in (self.size, self.chunk_size, chunks)):
                raise ValueError("Invalid video manifest")
            if self.size < 0 or self.chunk_size <= 0 or chunks != (self.size + self.chunk_size - 1) // self.chunk_size:
                raise ValueError("Invalid video manifest")
            self.parts = tuple(self.path / f"{index:06d}" for index in range(chunks))
            if {part.name for part in self.path.iterdir() if part.name.isdigit()} != {part.name for part in self.parts}:
                raise ValueError("Unexpected video chunks")
            if any(part.is_symlink() or not part.is_file() for part in self.parts):
                raise ValueError("Invalid video chunk")
            stats = [part.stat() for part in self.parts]
            if any(info.st_size != min(self.chunk_size, self.size - index * self.chunk_size) for index, info in enumerate(stats)):
                raise ValueError("Incomplete video chunks")
            self.mtime_ns = max([manifest.stat().st_mtime_ns] + [info.st_mtime_ns for info in stats])
        else:
            info = self.path.stat()
            self.size = info.st_size
            self.chunk_size = self.size or CHUNK_SIZE
            self.parts = (self.path,)
            self.mtime_ns = info.st_mtime_ns

    def readable(self):
        return not self.closed

    def seekable(self):
        return not self.closed

    def tell(self):
        if self.closed:
            raise ValueError("I/O operation on closed video")
        return self.position

    def seek(self, offset, whence=0):
        if self.closed:
            raise ValueError("I/O operation on closed video")
        offset, whence = operator.index(offset), operator.index(whence)
        if whence not in (0, 1, 2):
            raise ValueError("Invalid whence")
        position = offset + (0, self.position, self.size)[whence]
        if position < 0:
            raise ValueError("Negative seek position")
        self.position = position
        return position

    def read(self, size=-1):
        if self.closed:
            raise ValueError("I/O operation on closed video")
        if size is not None:
            size = operator.index(size)
        remaining = max(0, self.size - self.position)
        if size is not None and size >= 0:
            remaining = min(size, remaining)
        result = bytearray()
        while remaining:
            index, offset = divmod(self.position, self.chunk_size)
            length = min(remaining, self.chunk_size - offset)
            with self.parts[index].open("rb") as source:
                source.seek(offset)
                data = source.read(length)
            if len(data) != length:
                raise OSError("Video changed while reading")
            result.extend(data)
            self.position += length
            remaining -= length
        return bytes(result)

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)


def open_video(path):
    return VideoFile(path)