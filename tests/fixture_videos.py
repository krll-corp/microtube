from support import account, compose, upload
from test_discovery import INDEX_VIDEOS, worker


CLIP = """
import io
import sys
from fractions import Fraction

import av

width, height, scale, rate = 640, 360, 12, 12
background = bytes.fromhex(sys.argv[2])
foreground = bytes.fromhex("f5f5f5")
# A bitmap keeps the test clip independent of installed fonts.
text = (
    "### ### ### ###",
    " #  #   #    # ",
    " #  ### ###  # ",
    " #  #     #  # ",
    " #  ### ###  # ",
)
rows = [b"".join((foreground if pixel == "#" else background) * scale for pixel in row) for row in text]
travel = width - len(text[0]) * scale - 80
top = (height - len(text) * scale) // 2
buffer = io.BytesIO()
with av.open(buffer, "w", format="mp4") as media:
    stream = media.add_stream("libx264", rate=rate)
    stream.width, stream.height = width, height
    stream.pix_fmt = "yuv420p"
    stream.options = {"preset": "ultrafast", "crf": "28"}
    for number in range(rate * int(sys.argv[1])):
        frame = av.VideoFrame(width, height, "rgb24")
        plane = frame.planes[0]
        pixels = bytearray((background * (plane.line_size // 3)) * height)
        offset = (travel // 2 + number * 5) % (2 * travel)
        left = 40 + min(offset, 2 * travel - offset)
        for row, data in enumerate(rows):
            for line in range(scale):
                start = (top + row * scale + line) * plane.line_size + left * 3
                pixels[start:start + len(data)] = data
        plane.update(pixels)
        frame.pts = number
        frame.time_base = Fraction(1, rate)
        media.mux(stream.encode(frame))
    media.mux(stream.encode())
sys.stdout.buffer.write(buffer.getvalue())
"""


def make_visual_clip(seconds, color):
    return compose(
        "exec", "-T", "backend-upload", "python", "-c", CLIP,
        str(seconds), color, capture_output=True,
    ).stdout


def seed_videos():
    samples = (
        ("Forest trail", "forest", "305c42"),
        ("Ocean waves", "ocean", "245979"),
        ("City walk", "city", "5a5366"),
        ("Mountain sunrise", "mountain", "795d38"),
        ("Night sky", "night", "373b61"),
        ("River journey", "river", "386968"),
    )
    opener = account()
    videos = {}
    for number, (title, tag, color) in enumerate(samples):
        # Leave time for the model to see playback and choose Pause.
        seconds = 120 if title == "Forest trail" else 4 + number
        clip = make_visual_clip(seconds, color)
        videos[title] = upload(opener, title, clip, tags=tag)
    worker(INDEX_VIDEOS, *(video["id"] for video in videos.values()))
    return videos
