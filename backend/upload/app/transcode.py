import subprocess

import av
from fastapi import HTTPException
from microtube_media import video_duration_seconds, video_stream


FORMATS = "mov,matroska,avi,mpeg,mpegts,flv,asf,ogg"


def inspect_upload(source):
    try:
        with av.open(source, mode="r", options={"format_whitelist": FORMATS}) as container:
            video = video_stream(container)
            if video is None or video.codec_context is None:
                raise ValueError("Missing video track")
            codec = video.codec_context
            copy_video = (
                (codec.name == "h264" and codec.pix_fmt in ("yuv420p", "yuvj420p"))
                or (codec.name == "hevc" and codec.pix_fmt in ("yuv420p", "yuv420p10le"))
            )
            copy_audio = all(track.codec_context and track.codec_context.name == "aac"
                             for track in container.streams.audio)
            mode = "transcode"
            brand = container.metadata.get("major_brand", "").strip()
            if copy_video and copy_audio:
                mode = "remux"
                if "mp4" in container.format.name.split(",") and brand and not brand.startswith(("qt", "3g", "M4A", "mjp2")):
                    mode = "direct"
            return dict(mode=mode, duration=video_duration_seconds(container),
                        video_codec=codec.name if copy_video else None, copy_audio=copy_audio)
    except (av.FFmpegError, ValueError) as error:
        raise HTTPException(415, "Expected a supported file with a readable video track") from error
    finally:
        source.seek(0)


def transcode_video(source, target, job, update):
    duration = job["duration"]
    if job["video_codec"]:
        video = ["-c:v", "copy"]
        if job["video_codec"] == "hevc":
            video += ["-tag:v", "hvc1"]
    else:
        video = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                 "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-threads:v", "2", "-filter_threads", "2"]
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror",
        "-stats_period", "2", "-progress", "pipe:1", "-protocol_whitelist", "file,pipe",
        "-format_whitelist", FORMATS, "-threads", "2", "-i", str(source),
        "-map", "0:V:0", "-map", "0:a?", *video, "-c:a", "copy" if job["copy_audio"] else "aac",
        "-f", "mp4", str(target),
    ]
    percent = 0
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as ffmpeg:
        try:
            for line in ffmpeg.stdout:
                key, _, value = line.strip().partition("=")
                if duration and key == "out_time_us" and value.lstrip("-").isdigit():
                    current = min(99, int(int(value) / (duration * 1_000_000) * 100))
                    if current > percent:
                        update(current)
                        percent = current
            if ffmpeg.wait():
                raise HTTPException(415, "The video could not be transcoded")
        finally:
            if ffmpeg.poll() is None:
                ffmpeg.kill()
    update(100)
