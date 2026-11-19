import os
from functools import cache


@cache
def service_url(name, default):
    app = os.getenv("MICROTUBE_MODAL_APP")
    if not app:
        return default
    import modal
    return modal.Function.from_name(app, name).get_web_url()


def service_headers():
    token = os.getenv("MICROTUBE_SERVICE_TOKEN")
    return {"X-Microtube-Service": token} if token else {}


def database_host(name):
    app = os.getenv("MICROTUBE_MODAL_APP")
    if not app:
        return "db-" + name
    import modal
    return modal.Cls.from_name(app, "Database")(name=name).ready.remote()


def commit_media():
    if os.getenv("MICROTUBE_MODAL_APP"):
        import modal
        modal.Volume.from_name("microtube-videos", version=2).commit()
