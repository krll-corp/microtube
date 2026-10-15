from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def run():
    return "backend-text-search"