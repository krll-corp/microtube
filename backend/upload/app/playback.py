import logging
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

import av
from microtube_media import video_stream
from microtube_services import commit_media, reload_media
from microtube_storage import VIDEO_STORAGE_DIR, PLAYBACK_HEIGHTS, find_video, open_video, playback_path


BITRATES = dict(zip(PLAYBACK_HEIGHTS, (2700, 5500, 16500)))
playback_lock = Lock()


def encode_playback(source, target, heights, audio):
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror",
        "-protocol_whitelist", "file,pipe", "-format_whitelist", "mov",
        "-threads", "2", "-i", str(source), "-filter_threads", "1",
        "-c:v", "libx264", "-preset", "veryfast", "-threads:v", "2", "-pix_fmt", "yuv420p",
        "-fpsmax", "60", "-sc_threshold", "0", "-force_key_frames", "expr:gte(t,n_forced*2)",
    ]
    variants = []
    for index, height in enumerate(heights):
        width = height * 16 // 9
        scale = (
            f"scale=w='min(iw,if(gte(iw,ih),{width},{height}))'"
            f":h='min(ih,if(gte(iw,ih),{height},{width}))'"
            ":force_original_aspect_ratio=decrease:force_divisible_by=2"
        )
        bitrate = BITRATES[height]
        command += ["-map", "0:V:0", f"-filter:v:{index}", scale,
                    f"-b:v:{index}", f"{bitrate}k", f"-maxrate:v:{index}", f"{bitrate * 11 // 10}k",
                    f"-bufsize:v:{index}", f"{bitrate * 2}k"]
        if audio:
            command += ["-map", "0:a:0"]
        variants.append(f"v:{index}" + (f",a:{index}" if audio else "") + f",name:{height}")
    if audio:
        command += ["-c:a", "aac", "-b:a", "128k", "-ac", "2"]
    init_name = "%v-init.mp4" if len(heights) > 1 else f"{heights[0]}-init.mp4"
    command += [
        "-f", "hls", "-hls_playlist_type", "vod", "-hls_time", "2",
        "-hls_segment_type", "fmp4", "-hls_flags", "independent_segments",
        "-hls_fmp4_init_filename", init_name, "-hls_segment_filename", "%v-%06d.m4s",
        "-master_pl_name", "master.m3u8", "-var_stream_map", " ".join(variants), "%v.m3u8",
    ]
    subprocess.run(command, cwd=target, check=True)
    if not (target / "master.m3u8").is_file():
        raise RuntimeError("Missing HLS master playlist")


def prepare_playback(id):
    try:
        with playback_lock:
            build_playback(id)
    except Exception:
        logging.exception("Could not prepare playback for %s", id)
        if os.getenv("MICROTUBE_MODAL_APP"):
            raise


def build_playback(id):
    reload_media()
    destination = playback_path(id)
    if (destination / "master.m3u8").is_file():
        return
    source = find_video(id)
    if source is None:
        raise FileNotFoundError(id)
    with open_video(source) as video, av.open(video, mode="r") as container:
        stream = video_stream(container)
        if stream is None:
            return
        heights = [height for height in PLAYBACK_HEIGHTS if height <= min(stream.width, stream.height)]
        audio = bool(container.streams.audio)
    if not heights:
        return

    staging = VIDEO_STORAGE_DIR / ".hls-work"
    staging.mkdir(exist_ok=True)
    with TemporaryDirectory() as work, TemporaryDirectory(dir=staging) as directory:
        if source.is_dir():
            with open_video(source) as video, (Path(work) / "source.mp4").open("wb") as file:
                shutil.copyfileobj(video, file, 1024 * 1024)
            source = Path(work) / "source.mp4"
        target = Path(directory) / "playback"
        target.mkdir()
        encode_playback(source, target, heights, audio)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.rename(destination)
        except OSError:
            if not (destination / "master.m3u8").is_file():
                raise
        commit_media()
