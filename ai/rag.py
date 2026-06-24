# ai/rag.py
#
# Minimal per-bot RAG (Retrieval-Augmented Generation) knowledge base.
# Each bot gets its own FAISS index + chunk store under vector_store/{bot_id}/.
# Used by the appointment bot to answer FAQ-style questions ("what are your
# hours?", "do you accept walk-ins?") using documents uploaded via the CMS.
#
# Mirrors the feature from the reference Streamlit appointment agent
# (FAISS + HuggingFace sentence-transformer embeddings) but adapted to be
# stateless-per-request and safe to call from an async WhatsApp webhook.

from __future__ import annotations

import os
import json
import logging
import threading

import numpy as np

logger = logging.getLogger(__name__)

VECTOR_STORE_DIR = os.getenv("VECTOR_STORE_DIR", "vector_store")
EMBEDDING_MODEL_NAME = os.getenv("RAG_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

_model = None
_model_lock = threading.Lock()


def _get_model():
    """Lazy-load the embedding model once per process (it's ~80MB, costly to reload)."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer
                logger.info(f"[rag] loading embedding model {EMBEDDING_MODEL_NAME}...")
                _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def _bot_dir(bot_id: int) -> str:
    path = os.path.join(VECTOR_STORE_DIR, str(bot_id))
    os.makedirs(path, exist_ok=True)
    return path


def _index_path(bot_id: int) -> str:
    return os.path.join(_bot_dir(bot_id), "index.faiss")


def _chunks_path(bot_id: int) -> str:
    return os.path.join(_bot_dir(bot_id), "chunks.json")


def _chunk_text(text: str, chunk_size: int = 600, overlap: int = 80) -> list[str]:
    text = " ".join(text.split())  # normalize whitespace
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def _load_chunks(bot_id: int) -> list[dict]:
    path = _chunks_path(bot_id)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_chunks(bot_id: int, chunks: list[dict]) -> None:
    with open(_chunks_path(bot_id), "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False)


def has_knowledge_base(bot_id: int) -> bool:
    return os.path.exists(_index_path(bot_id)) and os.path.exists(_chunks_path(bot_id))


def ingest_text(bot_id: int, text: str, title: str = "document") -> int:
    """Chunk + embed + append text to this bot's FAISS index. Returns chunk count added."""
    import faiss

    new_chunks = _chunk_text(text)
    if not new_chunks:
        return 0

    model = _get_model()
    embeddings = model.encode(new_chunks, normalize_embeddings=True)
    embeddings = np.asarray(embeddings, dtype="float32")
    dim = embeddings.shape[1]

    index_path = _index_path(bot_id)
    if os.path.exists(index_path):
        index = faiss.read_index(index_path)
    else:
        index = faiss.IndexFlatIP(dim)  # cosine similarity via normalized inner product

    index.add(embeddings)
    faiss.write_index(index, index_path)

    existing = _load_chunks(bot_id)
    existing.extend([{"text": c, "title": title} for c in new_chunks])
    _save_chunks(bot_id, existing)

    return len(new_chunks)


def ingest_pdf_bytes(bot_id: int, pdf_bytes: bytes, title: str = "document.pdf") -> int:
    """Extract text from a PDF (in-memory) and ingest it."""
    from pypdf import PdfReader
    import io

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return ingest_text(bot_id, text, title=title)


def query(bot_id: int, question: str, k: int = 3) -> list[str]:
    """Returns up to k most relevant chunks for the question. Empty list if no KB exists."""
    if not has_knowledge_base(bot_id):
        return []

    import faiss

    try:
        index = faiss.read_index(_index_path(bot_id))
        chunks = _load_chunks(bot_id)
        if index.ntotal == 0 or not chunks:
            return []

        model = _get_model()
        q_emb = model.encode([question], normalize_embeddings=True)
        q_emb = np.asarray(q_emb, dtype="float32")

        k = min(k, index.ntotal)
        scores, indices = index.search(q_emb, k)
        results = []
        for idx in indices[0]:
            if 0 <= idx < len(chunks):
                results.append(chunks[idx]["text"])
        return results
    except Exception as exc:
        logger.error(f"[rag] query failed for bot {bot_id}: {exc}")
        return []


async def answer_with_rag(question: str, bot, db) -> str | None:
    """
    Retrieves relevant chunks and asks the bot's configured LLM to answer using
    only that context. Returns None if there's no knowledge base or no answer.
    """
    chunks = query(bot.id, question, k=3)
    if not chunks:
        return None

    context = "\n\n---\n\n".join(chunks)
    system_prompt = (
        f"You are a helpful assistant for {bot.business_name or bot.name}. "
        "Answer the user's question using ONLY the context below. "
        "If the context doesn't contain the answer, say you don't have that "
        "information and offer to connect them with a human. Keep it short and friendly.\n\n"
        f"Context:\n{context}"
    )

    try:
        from ai_utils import resolve_provider_and_key, call_ai_chat

        provider, api_key = resolve_provider_and_key(bot, db)
        if not api_key:
            return None

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]
        return await call_ai_chat(messages, provider, api_key, bot, db, question)
    except Exception as exc:
        logger.error(f"[rag] answer generation failed: {exc}")
        return None
