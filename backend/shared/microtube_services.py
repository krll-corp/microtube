import os
from functools import cache
from tempfile import NamedTemporaryFile


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


@cache
def certificate_file(certificate):
    with NamedTemporaryFile(mode="w", suffix=".crt", delete=False) as file:
        file.write(certificate)
        return file.name


def database_options(name):
    app = os.getenv("MICROTUBE_MODAL_APP")
    if not app:
        return {"host": "db-" + name}
    import modal
    options = modal.Cls.from_name(app, "Database")(name=name).ready.remote()
    options["sslrootcert"] = certificate_file(options.pop("certificate"))
    return {**options, "sslmode": "verify-full"}


def commit_media():
    if os.getenv("MICROTUBE_MODAL_APP"):
        import modal
        modal.Volume.from_name("microtube-videos", version=2).commit()
