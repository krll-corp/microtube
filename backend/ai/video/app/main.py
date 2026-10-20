import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoProcessor
from transformers.video_utils import load_video

MODEL_ID = "google/embeddinggemma-2"
VIDEO_STORAGE_DIR = Path(os.getenv("VIDEO_STORAGE_DIR", "/videos"))

processor = AutoProcessor.from_pretrained(MODEL_ID)
model = AutoModel.from_pretrained(MODEL_ID, device_map="auto", dtype=torch.float32).eval() #TODO: GPUs

app = FastAPI()

@app.get("/embedding/video")
def run(hash: str = Query(pattern=r"^[0-9a-zA-Z_-]{8}$")):
    video = VIDEO_STORAGE_DIR / hash
    if not video.is_file():
        raise HTTPException(status_code=404, detail="Video not found")

    frames, metadata = load_video(
        str(video),
        backend="pyav",
        sample_indices_fn=lambda metadata, **kwargs: processor.video_processor.sample_frames(
            metadata, fps=1, max_frames=32, overflow_strategy="uniform"
        ),
    )
    with torch.inference_mode():
        inputs = processor(
            videos=[frames],
            video_metadata=[metadata],
            return_tensors="pt",
            do_sample_frames=False,
        ).to(model.device)
        hidden = model(**inputs).last_hidden_state.float()
        mask = inputs["attention_mask"].unsqueeze(-1)
        embedding = (hidden * mask).sum(dim=1) / mask.sum(dim=1)
        embedding = F.normalize(embedding, dim=-1)
        return embedding[0].cpu().tolist()
