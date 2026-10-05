"""Hybrid retrieval over lexical BM25 search and an in-memory embedding index."""

from __future__ import annotations

import os
import re
import threading
from collections import defaultdict

from openai import OpenAI
from rank_bm25 import BM25Okapi

from kb.corpus import load_chunks
from kb.vector_store import InMemoryVectorDB

TOKEN_RE = re.compile(r"[a-z0-9_*]+", re.IGNORECASE)
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "is", "it", "of", "on", "or", "that", "the", "to", "was", "what",
    "when", "where", "which", "who", "why", "with",
}
RRF_K = 60
LEXICAL_POOL = 12
VECTOR_POOL = 12
EMBED_BATCH = 64

SYSTEM_PROMPT = """You answer questions using only the retrieved passages.
The passages may come from Apache Ranger documents or from files the user uploaded.
Write the way you would explain it to a colleague: short paragraphs, everyday words, and the names of users, groups, and resources when they matter.
When several people or permissions are involved, use a few short sentences rather than a field dump.
Do not repeat labels such as "Policy id", "Document:", or "Enabled:".
Do not quote raw JSON or paste long excerpts.
If the passages do not contain the answer, say so in one sentence. Do not invent policies.
Mention the document title only when it helps the reader know where the rule comes from."""


def tokenize(text: str) -> list[str]:
    return [token for token in TOKEN_RE.findall(text.lower()) if token not in STOPWORDS and len(token) > 1]


class KnowledgeBase:
    def __init__(self) -> None:
        self.chunks: list[dict] = []
        self._bm25: BM25Okapi | None = None
        self.vectors = InMemoryVectorDB()
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.chat_model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
        self.embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small").strip() or "text-embedding-3-small"
        self.embed_error: str | None = None
        self._lock = threading.Lock()

    def build(self) -> None:
        chunks = load_chunks()
        tokenized = [tokenize(f"{chunk['title']}\n{chunk['text']}") or ["empty"] for chunk in chunks]
        bm25 = BM25Okapi(tokenized)
        with self._lock:
            self.chunks = chunks
            self._bm25 = bm25
            self.vectors = InMemoryVectorDB()
            self.embed_error = None

    def ingest_uploads(self, files: list[tuple[str, bytes]]) -> dict:
        from kb.uploads import save_upload

        saved: list[str] = []
        errors: list[str] = []
        for filename, data in files:
            try:
                saved.append(save_upload(filename, data))
            except ValueError as exc:
                errors.append(str(exc))
        if saved:
            self._reindex()
        if errors and not saved:
            raise ValueError(" ".join(errors))
        return {"saved": saved, "errors": errors}

    def remove_upload(self, filename: str) -> None:
        from kb.uploads import delete_upload

        delete_upload(filename)
        self._reindex()

    def _reindex(self) -> None:
        self.build()
        if not self.api_key:
            return
        try:
            self.embed()
        except Exception as exc:
            self.embed_error = str(exc)

    def configure(self, api_key: str, chat_model: str | None = None) -> int:
        """Save a key and build embeddings. A failed embedding leaves the previous key in place."""
        with self._lock:
            previous_key = self.api_key
            previous_model = self.chat_model
        self.set_credentials(api_key, chat_model)
        try:
            return self.embed()
        except Exception:
            with self._lock:
                self.api_key = previous_key
                self.chat_model = previous_model
            raise

    def set_credentials(self, api_key: str, chat_model: str | None = None) -> None:
        api_key = api_key.strip()
        if not api_key:
            raise ValueError("OpenAI API key is empty.")
        with self._lock:
            self.api_key = api_key
            if chat_model and chat_model.strip():
                self.chat_model = chat_model.strip()
            self.embed_error = None

    def embed(self) -> int:
        if not self.api_key:
            raise RuntimeError("Set an OpenAI API key before building embeddings.")
        with self._lock:
            chunks = list(self.chunks)
            model = self.embedding_model
            api_key = self.api_key
        if not chunks:
            raise RuntimeError("The corpus has no chunks to embed.")

        client = OpenAI(api_key=api_key)
        vectors: list[list[float]] = []
        texts = [f"{chunk['title']}\n{chunk['text']}"[:12000] for chunk in chunks]
        for start in range(0, len(texts), EMBED_BATCH):
            batch = texts[start : start + EMBED_BATCH]
            response = client.embeddings.create(model=model, input=batch)
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend(item.embedding for item in ordered)

        store = InMemoryVectorDB()
        store.replace(vectors)
        with self._lock:
            if len(self.chunks) != len(chunks):
                raise RuntimeError("Corpus changed while embeddings were building. Retry.")
            self.vectors = store
            self.embed_error = None
        return len(vectors)

    def search(self, query: str, limit: int = 6) -> list[dict]:
        query = query.strip()
        if not query:
            return []
        with self._lock:
            chunks = self.chunks
            bm25 = self._bm25
            vectors = self.vectors
            api_key = self.api_key
            embedding_model = self.embedding_model

        if bm25 is None or not chunks:
            return []

        lexical_hits = self._lexical(query, bm25, min(LEXICAL_POOL, len(chunks)))
        vector_hits: list[tuple[int, float]] = []
        vector_error = None
        if vectors.ready and api_key:
            try:
                client = OpenAI(api_key=api_key)
                embedded = client.embeddings.create(model=embedding_model, input=[query[:8000]])
                vector_hits = vectors.search(embedded.data[0].embedding, min(VECTOR_POOL, len(chunks)))
            except Exception as exc:  # surface retrieval degradation without failing the request
                vector_error = str(exc)

        fused = _fuse(lexical_hits, vector_hits, limit)
        results = []
        for index, score, lexical_rank, vector_rank, lexical_score, vector_score in fused:
            chunk = chunks[index]
            results.append(
                {
                    "id": chunk["id"],
                    "title": chunk["title"],
                    "document": chunk["document"],
                    "source": chunk["source"],
                    "url": chunk["url"],
                    "text": chunk["text"],
                    "summary": chunk.get("summary") or "",
                    "score": round(score, 4),
                    "lexical_rank": lexical_rank,
                    "vector_rank": vector_rank,
                    "lexical_score": None if lexical_score is None else round(lexical_score, 4),
                    "vector_score": None if vector_score is None else round(vector_score, 4),
                    "vector_error": vector_error,
                }
            )
        return results

    def _lexical(self, query: str, bm25: BM25Okapi, limit: int) -> list[tuple[int, float]]:
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = bm25.get_scores(tokens)
        ranked = sorted(((index, float(score)) for index, score in enumerate(scores) if score > 0), key=lambda item: item[1], reverse=True)
        return ranked[:limit]

    def status(self) -> dict:
        with self._lock:
            documents: dict[str, dict] = {}
            for chunk in self.chunks:
                entry = documents.setdefault(
                    chunk["source"],
                    {
                        "file": chunk["source"],
                        "title": chunk["document"],
                        "url": chunk["url"],
                        "chunks": 0,
                        "uploaded": bool(chunk.get("uploaded")),
                        "upload_name": chunk.get("upload_name") or "",
                    },
                )
                entry["chunks"] += 1
            return {
                "documents": list(documents.values()),
                "chunks": len(self.chunks),
                "lexical_ready": self._bm25 is not None,
                "embeddings_ready": self.vectors.ready,
                "has_api_key": bool(self.api_key),
                "chat_model": self.chat_model,
                "embedding_model": self.embedding_model,
                "embed_error": self.embed_error,
            }

    def stream_answer(self, question: str, history: list[dict], hits: list[dict]):
        if not self.api_key:
            raise RuntimeError("Add an OpenAI API key to generate an answer.")
        client = OpenAI(api_key=self.api_key)
        context = _format_context(hits)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in history[-8:]:
            role = turn.get("role")
            content = (turn.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append(
            {
                "role": "user",
                "content": f"Question:\n{question.strip()}\n\nRetrieved passages:\n{context}",
            }
        )
        stream = client.chat.completions.create(
            model=self.chat_model,
            messages=messages,
            temperature=0.2,
            stream=True,
        )
        for event in stream:
            delta = event.choices[0].delta.content if event.choices else None
            if delta:
                yield delta


def _fuse(
    lexical_hits: list[tuple[int, float]],
    vector_hits: list[tuple[int, float]],
    limit: int,
) -> list[tuple[int, float, int | None, int | None, float | None, float | None]]:
    """Reciprocal rank fusion of lexical and embedding result lists."""
    if not vector_hits:
        return [
            (index, 1.0 / (RRF_K + rank), rank, None, score, None)
            for rank, (index, score) in enumerate(lexical_hits[:limit], start=1)
        ]

    scores: dict[int, float] = defaultdict(float)
    lexical_rank: dict[int, int] = {}
    vector_rank: dict[int, int] = {}
    lexical_score: dict[int, float] = {}
    vector_score: dict[int, float] = {}
    for rank, (index, score) in enumerate(lexical_hits, start=1):
        scores[index] += 1.0 / (RRF_K + rank)
        lexical_rank[index] = rank
        lexical_score[index] = score
    for rank, (index, score) in enumerate(vector_hits, start=1):
        scores[index] += 1.0 / (RRF_K + rank)
        vector_rank[index] = rank
        vector_score[index] = score

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [
        (
            index,
            score,
            lexical_rank.get(index),
            vector_rank.get(index),
            lexical_score.get(index),
            vector_score.get(index),
        )
        for index, score in ordered
    ]


def plain_answer(hits: list[dict]) -> str:
    """Readable answer from retrieved summaries, used before a chat model is available."""
    lines: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        summary = (hit.get("summary") or "").strip()
        if not summary or summary in seen:
            continue
        seen.add(summary)
        lines.append(summary)
        if len(lines) == 3:
            break
    if not lines:
        return "I couldn't find a passage that answers that."
    return "\n\n".join(lines)


def _format_context(hits: list[dict]) -> str:
    if not hits:
        return "No passages were retrieved."
    blocks = []
    for number, hit in enumerate(hits, start=1):
        blocks.append(
            f"[{number}] {hit['document']} / {hit['title']} ({hit['source']})\n{hit['text']}"
        )
    return "\n\n".join(blocks)
