from fastapi import Depends, FastAPI
from microtube_auth import require_user
from microtube_embeddings import get_embedding

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/search", dependencies=[Depends(require_user)])
def run(req: str):
    get_embedding("http://backend-ai-text:4001/embedding/text", {"text": req})
    return "backend-text-search"
