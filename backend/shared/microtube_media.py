from fractions import Fraction

import av
from av.stream import Disposition


def video_stream(container):
    return next((stream for stream in container.streams.video if not stream.disposition & Disposition.attached_pic), None)


def first_video_frame(container):
    stream = video_stream(container)
    if stream is not None:
        frame = next(container.decode(stream), None)
        if frame is not None:
            return frame
    raise ValueError("Missing video frames")


def video_duration_seconds(container):
    stream = video_stream(container)
    if stream is None:
        return None
    if container.duration is not None and container.duration > 0:
        return container.duration / av.time_base
    if stream.duration and stream.time_base:
        duration = float(stream.duration * stream.time_base)
        if duration > 0:
            return duration
    return None


def encode_thumbnail(frame):
    scale = min(1, 480 / max(frame.width, frame.height))
    width = max(2, int(frame.width * scale) // 2 * 2)
    height = max(2, int(frame.height * scale) // 2 * 2)
    frame = frame.reformat(width=width, height=height, format="yuvj420p")
    frame.pts = 0
    encoder = av.CodecContext.create("mjpeg", "w")
    encoder.width, encoder.height = width, height
    encoder.pix_fmt = "yuvj420p"
    encoder.time_base = Fraction(1, 25)
    packets = encoder.encode(frame) + encoder.encode(None)
    return b"".join(bytes(packet) for packet in packets)