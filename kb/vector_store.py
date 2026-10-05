"""In-memory vector database using cosine similarity over normalized embeddings."""

from __future__ import annotations

import numpy as np


class InMemoryVectorDB:
    def __init__(self) -> None:
        self._matrix: np.ndarray | None = None

    def __len__(self) -> int:
        if self._matrix is None:
            return 0
        return int(self._matrix.shape[0])

    @property
    def ready(self) -> bool:
        return self._matrix is not None and len(self) > 0

    def replace(self, vectors: list[list[float]]) -> None:
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] == 0:
            raise ValueError("Expected a non-empty embedding matrix.")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._matrix = matrix / norms

    def search(self, query: list[float], limit: int) -> list[tuple[int, float]]:
        if not self.ready:
            return []
        assert self._matrix is not None
        vector = np.asarray(query, dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            return []
        vector = vector / norm
        scores = self._matrix @ vector
        count = min(limit, scores.shape[0])
        # argpartition is unordered within the top slice; sort that slice only.
        candidates = np.argpartition(-scores, count - 1)[:count]
        ordered = candidates[np.argsort(-scores[candidates])]
        return [(int(index), float(scores[index])) for index in ordered]
