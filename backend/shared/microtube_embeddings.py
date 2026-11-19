import math
import requests
from urllib.parse import urlsplit
from microtube_services import service_headers, service_url


def get_embedding(url, params):
    endpoint = urlsplit(url)
    url = service_url(endpoint.hostname, f"{endpoint.scheme}://{endpoint.netloc}") + endpoint.path
    response = requests.get(url, params=params, timeout=600, headers=service_headers())
    response.raise_for_status()
    embedding = response.json()
    if (
        not isinstance(embedding, list)
        or len(embedding) != 768
        or not all(type(value) in (int, float) and math.isfinite(value) for value in embedding)
    ):
        raise ValueError(f"Invalid embedding from {url}")
    return embedding
