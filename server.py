"""Local web app for the Ranger knowledge-base chatbot."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from kb.engine import KnowledgeBase, plain_answer  # noqa: E402

WEB_DIR = ROOT / "web"
kb = KnowledgeBase()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(kb.build)
    if kb.api_key:
        try:
            await asyncio.to_thread(kb.embed)
        except Exception as exc:
            kb.embed_error = str(exc)
    yield


app = FastAPI(title="Ranger knowledge base", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


class SettingsBody(BaseModel):
    api_key: str
    chat_model: str | None = None


class ChatBody(BaseModel):
    message: str = Field(min_length=1)
    history: list[dict] = Field(default_factory=list)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/status")
def status() -> dict:
    payload = kb.status()
    payload["vercel"] = bool(os.getenv("VERCEL"))
    return payload


@app.post("/api/settings")
async def save_settings(body: SettingsBody) -> dict:
    try:
        embedded = await asyncio.to_thread(kb.configure, body.api_key, body.chat_model)
    except Exception as exc:
        kb.embed_error = str(exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"embedded_chunks": embedded, **kb.status()}


@app.post("/api/uploads")
async def upload_documents(files: list[UploadFile] = File(...)) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="Choose at least one file.")
    payloads: list[tuple[str, bytes]] = []
    for item in files:
        payloads.append((item.filename or "upload.txt", await item.read()))
    try:
        result = await asyncio.to_thread(kb.ingest_uploads, payloads)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, **kb.status()}


@app.delete("/api/uploads/{filename}")
async def remove_document(filename: str) -> dict:
    try:
        await asyncio.to_thread(kb.remove_upload, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="That file is not in your documents.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return kb.status()


@app.get("/api/search")
async def search(q: str, limit: int = 6) -> dict:
    hits = await asyncio.to_thread(kb.search, q, max(1, min(limit, 12)))
    return {"results": [_public_hit(hit) for hit in hits]}


@app.post("/api/chat")
async def chat(body: ChatBody) -> StreamingResponse:
    question = body.message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Message is empty.")
    hits = await asyncio.to_thread(kb.search, question, 6)
    history = body.history

    def generate():
        mode = "hybrid" if any(hit.get("vector_rank") for hit in hits) else "lexical"
        yield _sse(
            {
                "type": "sources",
                "mode": mode,
                "sources": [_public_hit(hit) for hit in hits],
            }
        )
        if not kb.api_key:
            yield _sse(
                {
                    "type": "notice",
                    "text": plain_answer(hits),
                    "footnote": "This is read straight from the matching pages. Save an OpenAI key when you want one combined written answer.",
                }
            )
            yield _sse({"type": "done"})
            return

        events: queue.Queue = queue.Queue()

        def produce() -> None:
            try:
                for token in kb.stream_answer(question, history, hits):
                    events.put(("token", token))
                events.put(("done", None))
            except Exception as exc:
                events.put(("error", str(exc)))

        threading.Thread(target=produce, daemon=True).start()
        while True:
            kind, payload = events.get()
            if kind == "token":
                yield _sse({"type": "token", "text": payload})
            elif kind == "error":
                yield _sse({"type": "error", "text": payload})
                yield _sse({"type": "done"})
                break
            else:
                yield _sse({"type": "done"})
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _public_hit(hit: dict) -> dict:
    return {
        "id": hit["id"],
        "title": hit["title"],
        "document": hit["document"],
        "source": hit["source"],
        "url": hit["url"],
        "text": hit["text"],
        "summary": hit.get("summary") or "",
        "score": hit["score"],
        "lexical_rank": hit["lexical_rank"],
        "vector_rank": hit["vector_rank"],
        "lexical_score": hit["lexical_score"],
        "vector_score": hit["vector_score"],
    }


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
