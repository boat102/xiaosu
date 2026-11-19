import math
from pathlib import Path
from pypdf import PdfReader
from docx import Document as DocxDocument
from sqlalchemy.orm import Session
from .models import Document, Chunk, now_utc
from .config import settings


def extract_text(filename: str, raw: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".txt"}:
        return raw.decode("utf-8", errors="replace")
    temp = Path(settings.upload_dir)
    temp.mkdir(parents=True, exist_ok=True)
    path = temp / ("extract-" + str(abs(hash(filename))) + suffix)
    path.write_bytes(raw)
    try:
        if suffix == ".pdf":
            return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
        if suffix == ".docx":
            doc = DocxDocument(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
    finally:
        path.unlink(missing_ok=True)
    raise ValueError("仅支持 Markdown / PDF / DOCX / TXT")


def split_text(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    clean = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not clean:
        return []
    chunks, start = [], 0
    while start < len(clean):
        end = min(len(clean), start + size)
        if end < len(clean):
            boundary = clean.rfind("\n", start, end)
            if boundary > start + size // 2:
                end = boundary
        chunks.append(clean[start:end].strip())
        if end == len(clean):
            break
        start = max(start + 1, end - overlap)
    return [c for c in chunks if c]


def embed_texts(client, texts: list[str]) -> list[list[float] | None]:
    if not client or not settings.openai_api_key:
        return [None for _ in texts]
    result = client.embeddings.create(model=settings.openai_embedding_model, input=texts)
    return [item.embedding for item in result.data]


def index_document(db: Session, doc: Document, text: str, client=None):
    doc.status = "pending"
    db.query(Chunk).filter(Chunk.document_id == doc.id).delete()
    parts = split_text(text)
    vectors = embed_texts(client, parts)
    for i, part in enumerate(parts):
        db.add(Chunk(document_id=doc.id, ordinal=i, content=part, embedding=vectors[i]))
    doc.chunk_count = len(parts)
    doc.status = "indexed" if parts else "failed"
    doc.updated_at = now_utc()
    db.commit()


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def retrieve(db: Session, query: str, client=None, limit: int = 5) -> list[dict]:
    chunks = db.query(Chunk).join(Document).filter(Document.status == "indexed").all()
    if not chunks:
        return []
    query_vector = None
    if client and settings.openai_api_key:
        try:
            query_vector = client.embeddings.create(model=settings.openai_embedding_model, input=[query]).data[0].embedding
        except Exception:
            query_vector = None
    scored = []
    terms = {t.lower() for t in query.replace("？", " ").replace("?", " ").split() if len(t) > 1}
    for chunk in chunks:
        doc = chunk.document
        if query_vector and chunk.embedding:
            score = cosine(query_vector, chunk.embedding)
        else:
            hay = chunk.content.lower()
            score = sum(1 for term in terms if term in hay) / max(1, len(terms))
        scored.append((score, chunk, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    threshold = settings.retrieval_threshold if query_vector else 0.01
    return [{"score": round(s, 4), "filename": d.filename, "chunk_id": c.id,
             "ordinal": c.ordinal, "content": c.content} for s, c, d in scored[:limit] if s >= threshold]
