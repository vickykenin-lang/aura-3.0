from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "hf" / "semantic_config.json"
REGISTRY_PATH = ROOT / "hf" / "semantic_model_registry.json"


@dataclass(frozen=True)
class SimilarityPolicy:
    duplicate_min: float
    repetitive_theme_min: float

    def classify(self, score: float) -> str:
        if score >= self.duplicate_min:
            return "DUPLICATE"
        if score >= self.repetitive_theme_min:
            return "REPETITIVE_THEME"
        return "DISTINCT"


def text_fingerprint(text: str) -> str:
    normalized = " ".join(text.split()).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_policy() -> SimilarityPolicy:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sim = cfg["similarity_policy"]
    return SimilarityPolicy(
        duplicate_min=float(sim["duplicate_min"]),
        repetitive_theme_min=float(sim["repetitive_theme_min"]),
    )


class MultilingualSemanticAdapter:
    """Lazy local-only semantic adapter. No production authority or side effects."""

    def __init__(self, model_key: str = "multilingual_minilm_primary") -> None:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        self.spec = registry["models"][model_key]
        self.model_key = model_key
        self._tokenizer = None
        self._model = None
        self._torch = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModel, AutoTokenizer

        model_id = self.spec["model_id"]
        revision = self.spec["revision"]
        self._tokenizer = AutoTokenizer.from_pretrained(
            model_id,
            revision=revision,
            trust_remote_code=False,
        )
        self._model = AutoModel.from_pretrained(
            model_id,
            revision=revision,
            trust_remote_code=False,
            use_safetensors=True,
        )
        self._model.eval()
        self._torch = torch

    def encode(self, texts: Iterable[str]):
        self._ensure_loaded()
        texts = list(texts)
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        max_chars = int(cfg["limits"]["max_text_chars_per_item"])
        if not texts:
            raise ValueError("at least one text is required")
        if any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ValueError("all texts must be non-empty strings")
        if any(len(t) > max_chars for t in texts):
            raise ValueError("text exceeds semantic memory character policy")

        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        with self._torch.no_grad():
            model_output = self._model(**encoded)
        token_embeddings = model_output[0]
        mask = encoded["attention_mask"].unsqueeze(-1).expand(token_embeddings.size()).float()
        pooled = self._torch.sum(token_embeddings * mask, dim=1) / self._torch.clamp(mask.sum(dim=1), min=1e-9)
        return self._torch.nn.functional.normalize(pooled, p=2, dim=1)

    def compare(self, left: str, right: str) -> float:
        embeddings = self.encode([left, right])
        return float((embeddings[0] @ embeddings[1]).item())

    def scan(self, items: list[dict[str, str]]) -> dict:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if len(items) > int(cfg["limits"]["max_items_per_pilot_run"]):
            raise ValueError("semantic memory item limit exceeded")
        if any("id" not in item or "text" not in item for item in items):
            raise ValueError("each item requires id and text")

        embeddings = self.encode([item["text"] for item in items])
        policy = load_policy()
        pairs = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                score = float((embeddings[i] @ embeddings[j]).item())
                pairs.append({
                    "left_id": items[i]["id"],
                    "right_id": items[j]["id"],
                    "left_fingerprint": text_fingerprint(items[i]["text"]),
                    "right_fingerprint": text_fingerprint(items[j]["text"]),
                    "similarity": round(score, 6),
                    "classification": policy.classify(score),
                })
        pairs.sort(key=lambda p: p["similarity"], reverse=True)
        return {
            "model_key": self.model_key,
            "model_id": self.spec["model_id"],
            "revision": self.spec["revision"],
            "mode": "SHADOW_ONLY",
            "decision_authority": False,
            "production_effect": "NONE",
            "items": len(items),
            "pairs": pairs,
        }
