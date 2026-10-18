import secrets
from fastapi import FastAPI, Form, UploadFile

app = FastAPI()

@app.post("/upload")
def run(
    file: UploadFile,
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
):
    id = secrets.token_urlsafe(6)
    #TODO: save to /videos aka into the DB
    return {
        "id": id,
        "filename": file.filename,
        "size": file.size,
        "title": title,
        "description": description,
        "tags": tags.split(),
        "stored": False,
    }