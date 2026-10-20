from fastapi import FastAPI, Query
import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoProcessor

MODEL_ID = "google/embeddinggemma-2"

processor = AutoProcessor.from_pretrained(MODEL_ID)
model = AutoModel.from_pretrained(
    MODEL_ID,
    device_map="auto",
    dtype=torch.float32,
    vision_config=None,
    audio_config=None,
).eval() #TODO: GPUs

app = FastAPI()

@app.get("/embedding/text")
def embedding(text: str = Query(min_length=1, pattern=r"\S")):
    with torch.inference_mode():
        inputs = processor(
            text=[f"title: none | text: {text}"],
            return_tensors="pt",
            truncation=True,
            max_length=8192,
        ).to(model.device)
        hidden = model(**inputs).last_hidden_state.float()
        mask = inputs["attention_mask"].unsqueeze(-1)
        embedding = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
        embedding = F.normalize(embedding, dim=-1)
        return embedding[0].cpu().tolist()