import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoProcessor

processor = AutoProcessor.from_pretrained("google/embeddinggemma-2")
model = AutoModel.from_pretrained("google/embeddinggemma-2", device_map="auto").eval()


video = torch.zeros((4, 3, 224, 224), dtype=torch.uint8)


video[1] = 85
video[2] = 170
video[3] = 255


inputs = processor( videos=[video], return_tensors="pt", do_sample_frames=False).to(model.device)


with torch.inference_mode():
    hidden = model(**inputs).last_hidden_state.float()
    mask = inputs["attention_mask"].unsqueeze(-1)
    embedding = (hidden * mask).sum(dim=1) / mask.sum(dim=1)
    embedding = F.normalize(embedding, dim=-1)

print(embedding.shape)  # torch.Size([1, 768])
print(embedding[0])