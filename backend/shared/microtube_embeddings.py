import math
import requests


def get_embedding(url, params):
    response = requests.get(url, params=params, timeout=600)
    response.raise_for_status()
    embedding = response.json()
    if (
        not isinstance(embedding, list)
        or len(embedding) != 768
        or not all(type(value) in (int, float) and math.isfinite(value) for value in embedding)
    ):
        raise ValueError(f"Invalid embedding from {url}")
    return embedding
