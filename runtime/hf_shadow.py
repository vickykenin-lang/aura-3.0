#!/usr/bin/env python3
"""AURA3 Hugging Face shadow evaluator.

This module is intentionally non-authoritative. It may inspect non-sensitive inputs
and emit comparison evidence, but it cannot approve/reject production content,
publish, change production routing, or establish a business outcome.
"""
from __future__ import annotations

import io
import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]


class ShadowPolicyError(RuntimeError):
    pass


def load_json(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    cooldown_seconds: int = 900
    consecutive_failures: int = 0
    opened_at: float | None = None

    def allow(self, now: float | None = None) -> bool:
        if self.opened_at is None:
            return True
        current = time.monotonic() if now is None else now
        if current - self.opened_at >= self.cooldown_seconds:
            self.consecutive_failures = 0
            self.opened_at = None
            return True
        return False

    def success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None

    def failure(self, now: float | None = None) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self.opened_at = time.monotonic() if now is None else now


def validate_shadow_contract(config: dict[str, Any], model: dict[str, Any], licence: dict[str, Any]) -> None:
    if config.get("mode") != "SHADOW_ONLY":
        raise ShadowPolicyError("HF mode must remain SHADOW_ONLY in Phase 1")
    if config.get("production_authority") is not False:
        raise ShadowPolicyError("HF production authority must be false")
    if config.get("required_for_business_execution") is not False:
        raise ShadowPolicyError("HF cannot be required for business execution in Phase 1")
    if model.get("production_authority") is not False:
        raise ShadowPolicyError("model production authority must be false")
    if model.get("trust_remote_code") is not False:
        raise ShadowPolicyError("remote code is not allowed in Phase 1")
    if not model.get("revision"):
        raise ShadowPolicyError("model revision must be pinned")
    if licence.get("commercial_use_gate") != "PASS_FOR_SHADOW_PILOT":
        raise ShadowPolicyError("model licence is not cleared for shadow pilot")


def download_image(url: str, config: dict[str, Any]) -> bytes:
    policy = config["image_policy"]
    if policy.get("https_only", True) and not url.startswith("https://"):
        raise ShadowPolicyError("image URL must use HTTPS")
    request = urllib.request.Request(url, headers={"User-Agent": "AURA3-HF-Shadow/1.0"})
    with urllib.request.urlopen(request, timeout=int(config["execution"]["timeout_seconds"])) as response:
        mime = response.headers.get_content_type()
        if mime not in set(policy["allowed_mime_types"]):
            raise ShadowPolicyError(f"unsupported image MIME type: {mime}")
        max_bytes = int(policy["max_image_bytes"])
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ShadowPolicyError("image exceeds configured size limit")
    if not payload:
        raise ShadowPolicyError("empty image payload")
    return payload


class LocalSiglipAdapter:
    """Lazy local Transformers adapter. No model import/download occurs until evaluate()."""

    def __init__(self, model_config: dict[str, Any], global_config: dict[str, Any]):
        self.model_config = model_config
        self.global_config = global_config
        self._processor = None
        self._model = None

    def _load(self) -> None:
        if self._processor is not None and self._model is not None:
            return
        from transformers import AutoModel, AutoProcessor

        token = os.getenv(self.global_config["security"]["token_env"]) or None
        kwargs = {
            "revision": self.model_config["revision"],
            "trust_remote_code": False,
            "token": token,
        }
        self._processor = AutoProcessor.from_pretrained(self.model_config["model_id"], **kwargs)
        model_kwargs = dict(kwargs)
        if self.model_config.get("safetensors_required"):
            model_kwargs["use_safetensors"] = True
        self._model = AutoModel.from_pretrained(self.model_config["model_id"], **model_kwargs)
        self._model.eval()

    def evaluate(self, image_bytes: bytes, candidate_labels: list[str]) -> dict[str, Any]:
        if not candidate_labels:
            raise ValueError("candidate_labels cannot be empty")
        self._load()
        from PIL import Image
        import torch

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        inputs = self._processor(text=candidate_labels, images=image, padding="max_length", return_tensors="pt")
        with torch.no_grad():
            outputs = self._model(**inputs)
            scores = torch.sigmoid(outputs.logits_per_image[0]).detach().cpu().tolist()
        ranked = sorted(
            ({"label": label, "score": float(score)} for label, score in zip(candidate_labels, scores)),
            key=lambda row: row["score"],
            reverse=True,
        )
        return {
            "task": self.model_config["task"],
            "model_id": self.model_config["model_id"],
            "revision": self.model_config["revision"],
            "ranked_labels": ranked,
            "top_label": ranked[0]["label"],
            "top_score": ranked[0]["score"],
        }


class HFShadowEvaluator:
    def __init__(
        self,
        config: dict[str, Any] | None = None,
        model_registry: dict[str, Any] | None = None,
        licence_registry: dict[str, Any] | None = None,
        adapter_factory: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
    ):
        self.config = config or load_json("hf/config.json")
        self.model_registry = model_registry or load_json("hf/model_registry.json")
        self.licence_registry = licence_registry or load_json("hf/licence_registry.json")
        cb = self.config["execution"]["circuit_breaker"]
        self.breaker = CircuitBreaker(int(cb["failure_threshold"]), int(cb["cooldown_seconds"]))
        self.adapter_factory = adapter_factory or LocalSiglipAdapter

    def _envelope(self, status: str, **extra: Any) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "department_id": "aura3",
            "layer": "hugging_face_shadow_evaluation",
            "status": status,
            "mode": "SHADOW_ONLY",
            "decision_authority": False,
            "production_effect": "NONE",
            "business_outcome_claim": False,
            **extra,
        }

    def evaluate_url(self, image_url: str, candidate_labels: list[str], force_shadow: bool = False) -> dict[str, Any]:
        if not self.config.get("enabled") and not force_shadow:
            return self._envelope("NOT_EXECUTED_DISABLED")
        if not self.breaker.allow():
            return self._envelope("EVALUATOR_UNAVAILABLE", reason="CIRCUIT_OPEN")

        model_key = self.config["primary_model"]
        model = self.model_registry["models"][model_key]
        if not model.get("enabled_for_shadow"):
            return self._envelope("NOT_EXECUTED_MODEL_DISABLED", model_key=model_key)
        licence_key = f"{model['model_id']}@{model['revision']}"
        licence = self.licence_registry["entries"].get(licence_key, {})
        validate_shadow_contract(self.config, model, licence)

        attempts = int(self.config["execution"].get("transient_retries", 0)) + 1
        last_error = None
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                image_bytes = download_image(image_url, self.config)
                adapter = self.adapter_factory(model, self.config)
                result = adapter.evaluate(image_bytes, candidate_labels)
                self.breaker.success()
                return self._envelope(
                    "SHADOW_RESULT",
                    model_key=model_key,
                    latency_ms=round((time.monotonic() - started) * 1000, 2),
                    attempt=attempt,
                    result=result,
                )
            except (ShadowPolicyError, ValueError) as exc:
                self.breaker.failure()
                return self._envelope("EVALUATION_REJECTED", reason=type(exc).__name__, detail=str(exc)[:240])
            except Exception as exc:
                last_error = exc
                self.breaker.failure()
                if attempt < attempts:
                    time.sleep(1)
                    continue
        return self._envelope(
            "EVALUATOR_UNAVAILABLE",
            reason=type(last_error).__name__ if last_error else "UNKNOWN",
            detail=str(last_error)[:240] if last_error else "",
        )
