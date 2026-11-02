"""
Multi-API-Key rotation manager for Google Gemini API.
Automatically rotates through a pool of API keys when encountering 429 quota exhaustion.
Supports per-model quota tracking so that exhausting daily requests on one model
(e.g., gemini-3.8-flash with 20 RPD) does not unnecessarily block keys on fallback
models (e.g., gemini-2.5-flash with 1,500 RPD).
"""

from __future__ import annotations

import logging
from typing import Sequence

logger = logging.getLogger(__name__)


class KeyRotator:
    """Manages rotation across multiple Gemini API keys with per-model quota tracking."""

    def __init__(self, api_keys: Sequence[str] | str | None = None):
        if isinstance(api_keys, str):
            # Split comma-separated string
            keys = [k.strip() for k in api_keys.split(",") if k.strip()]
        elif api_keys:
            keys = [k.strip() for k in api_keys if k and k.strip()]
        else:
            keys = []

        self.keys: list[str] = keys
        self.exhausted_keys: set[str] = set()
        self.exhausted_by_model: dict[str, set[str]] = {}
        self._current_index: int = 0

    @property
    def total_keys(self) -> int:
        return len(self.keys)

    @property
    def available_keys(self) -> list[str]:
        return [k for k in self.keys if k not in self.exhausted_keys]

    def available_keys_for_model(self, model: str | None = None) -> list[str]:
        """Return available keys for a specific model (or globally if model is None)."""
        if not model:
            return self.available_keys
        model_exhausted = self.exhausted_by_model.get(model, set())
        return [k for k in self.keys if k not in model_exhausted]

    def has_available_keys(self, model: str | None = None) -> bool:
        return len(self.available_keys_for_model(model)) > 0

    def all_exhausted(self, model: str | None = None) -> bool:
        return len(self.keys) > 0 and len(self.available_keys_for_model(model)) == 0

    def get_current_key(self, model: str | None = None) -> str | None:
        """Return the current non-exhausted API key for the model, or None if none available."""
        if not self.keys:
            return None

        avail = self.available_keys_for_model(model)
        if not avail:
            return None

        # If current index key is valid for this model, return it
        current_candidate = self.keys[self._current_index % len(self.keys)]
        if current_candidate in avail:
            return current_candidate

        # Otherwise advance to next available key
        return self.rotate_key(model=model)

    def rotate_key(self, model: str | None = None) -> str | None:
        """Advance to the next non-exhausted key in the pool for the specified model."""
        avail = self.available_keys_for_model(model)
        if not avail:
            model_info = f" for model '{model}'" if model else ""
            logger.warning("All %d API key(s) are exhausted%s.", len(self.keys), model_info)
            return None

        # Look for the next non-exhausted key
        num_keys = len(self.keys)
        for offset in range(1, num_keys + 1):
            next_idx = (self._current_index + offset) % num_keys
            candidate = self.keys[next_idx]
            if candidate in avail:
                self._current_index = next_idx
                model_info = f" on {model}" if model else ""
                logger.info(
                    "Rotated Gemini API key to key index %d of %d (ends with ...%s)%s",
                    next_idx + 1,
                    num_keys,
                    candidate[-6:],
                    model_info,
                )
                return candidate

        return None

    def mark_key_exhausted(
        self, key: str, reason: str = "", model: str | None = None
    ) -> str | None:
        """
        Mark a key as quota-exhausted (optionally per model) and rotate to the next available key.
        Returns the next available key, or None if all are exhausted.
        """
        clean_key = key.strip() if key else ""
        if clean_key:
            self.exhausted_keys.add(clean_key)
            if model:
                self.exhausted_by_model.setdefault(model, set()).add(clean_key)

            avail_remaining = len(self.available_keys_for_model(model))
            model_info = f" for {model}" if model else ""
            logger.warning(
                "Gemini API key (...%s) marked exhausted (%s)%s. %d of %d keys remaining.",
                clean_key[-6:],
                reason or "429 Quota Exceeded",
                model_info,
                avail_remaining,
                len(self.keys),
            )
        return self.rotate_key(model=model)

    def reset(self, model: str | None = None) -> None:
        """Clear exhausted status for keys (optionally for a specific model)."""
        if model:
            self.exhausted_by_model.pop(model, None)
            all_model_exhausted = set()
            for s in self.exhausted_by_model.values():
                all_model_exhausted.update(s)
            self.exhausted_keys = all_model_exhausted
        else:
            self.exhausted_keys.clear()
            self.exhausted_by_model.clear()
            self._current_index = 0
