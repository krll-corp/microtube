from fractions import Fraction

import av
from av.stream import Disposition


def first_video_frame(container):
    stream = next((stream for stream in container.streams.video if not stream.disposition & Disposition.attached_pic), None)
    if stream is not None:
        frame = next(container.decode(stream), None)
        if frame is not None:
            return frame
    raise ValueError("Missing video frames")


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