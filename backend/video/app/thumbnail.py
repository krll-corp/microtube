from threading import Lock

import av
from microtube_media import encode_thumbnail, first_video_frame
from microtube_storage import find_video, open_video, save_thumbnail, thumbnail_path

thumbnail_lock = Lock()


def read_thumbnail(id):
    try:
        target = thumbnail_path(id)
        with thumbnail_lock:
            if target.is_file() and target.stat().st_size:
                return target
            path = find_video(id)
            if path is None:
                return None
            with open_video(path) as source, av.open(source, format="mp4") as container:
                return save_thumbnail(id, encode_thumbnail(first_video_frame(container)))
    except (OSError, ValueError, av.FFmpegError):
        return None
