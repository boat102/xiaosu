import logging
from pathlib import Path
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc
from .config import settings
from .database import Base, engine, get_db
from .models import Document, Message, Conversation, ToolAudit
from .schemas import ChatRequest
from .agent import answer_chat, get_client, stream_chat_events
from .knowledge import extract_text, index_document
from .tools import EMPLOYEES, ATTENDANCE, ORDERS

Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, handlers=[logging.FileHandler(Path(settings.log_dir) / "backend.log"), logging.StreamHandler()],
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("xiaosu")
Base.metadata.create_all(bind=engine)
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health(): return {"status": "ok", "model": settings.openai_model, "openai_configured": bool(settings.openai_api_key)}


@app.post("/api/chat")
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    try:
        return answer_chat(db, payload.message, payload.user_id, payload.channel, payload.conversation_id)
    except Exception as exc:
        logger.exception("chat failed")
        raise HTTPException(status_code=502, detail="小苏暂时遇到问题，请稍后重试。") from exc


@app.post("/api/chat/stream")
def chat_stream(payload: ChatRequest, db: Session = Depends(get_db)):
    import json
    def events():
        try:
            for event in stream_chat_events(db, payload.message, payload.user_id, payload.channel, payload.conversation_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception:
            logger.exception("stream chat failed")
            yield f"data: {json.dumps({'type': 'error', 'message': '小苏暂时遇到问题，请稍后重试。'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/api/documents")
def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    allowed = {".md", ".txt", ".pdf", ".docx"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed: raise HTTPException(400, "仅支持 MD / TXT / PDF / DOCX")
    raw = file.file.read()
    if len(raw) > 15 * 1024 * 1024: raise HTTPException(413, "单文件最大 15MB")
    try: content = extract_text(file.filename, raw)
    except Exception as exc: raise HTTPException(400, f"文档解析失败：{exc}") from exc
    doc = db.query(Document).filter_by(filename=file.filename).first()
    if not doc:
        doc = Document(filename=file.filename, content_type=file.content_type or "application/octet-stream")
        db.add(doc); db.commit(); db.refresh(doc)
    else:
        doc.content_type = file.content_type or doc.content_type
        db.commit()
    try: index_document(db, doc, content, get_client())
    except Exception as exc:
        doc.status = "failed"; db.commit(); logger.exception("index failed")
        raise HTTPException(502, "文档索引失败，请检查模型配置后重试") from exc
    return {"id": doc.id, "filename": doc.filename, "status": doc.status, "chunk_count": doc.chunk_count, "content_type": doc.content_type}


@app.get("/api/documents")
def list_documents(db: Session = Depends(get_db)):
    return [{"id": d.id, "filename": d.filename, "status": d.status, "chunk_count": d.chunk_count,
             "content_type": d.content_type, "updated_at": d.updated_at.isoformat()} for d in db.query(Document).order_by(desc(Document.updated_at)).all()]


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc: raise HTTPException(404, "文档不存在")
    db.delete(doc); db.commit()
    return {"ok": True}


@app.get("/api/logs")
def logs(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(Message, Conversation).join(Conversation, Message.conversation_id == Conversation.id).order_by(desc(Message.id)).limit(min(limit, 500)).all()
    return [{"id": m.id, "user_id": c.user_id, "channel": c.channel, "conversation_id": c.external_conversation_id,
             "role": m.role, "content": m.content, "tools_used": m.tool_names or [],
             "prompt_tokens": m.prompt_tokens, "completion_tokens": m.completion_tokens, "created_at": m.created_at.isoformat()} for m, c in rows]


@app.get("/api/tools/logs")
def tool_logs(limit: int = 100, db: Session = Depends(get_db)):
    return [{"id": x.id, "tool_name": x.tool_name, "input": x.input_json, "output": x.output_text,
             "success": x.success, "created_at": x.created_at.isoformat()} for x in db.query(ToolAudit).order_by(desc(ToolAudit.id)).limit(min(limit, 500)).all()]


@app.get("/api/employee/{employee_id}")
def mock_employee(employee_id: str):
    employee = next((item for item in EMPLOYEES if item["id"] == employee_id), None)
    if not employee: raise HTTPException(404, "员工不存在")
    return employee


@app.get("/api/attendance")
def mock_attendance(employee_id: str, start_date: str | None = None, end_date: str | None = None):
    rows = [item for item in ATTENDANCE if item["emp_id"] == employee_id]
    if start_date: rows = [item for item in rows if item["date"] >= start_date]
    if end_date: rows = [item for item in rows if item["date"] <= end_date]
    return {"records": rows, "days_present": len(rows)}


@app.get("/api/orders")
def mock_orders(start_date: str | None = None, end_date: str | None = None):
    rows = [item for item in ORDERS if item["status"] == "paid"]
    if start_date: rows = [item for item in rows if item["date"] >= start_date]
    if end_date: rows = [item for item in rows if item["date"] <= end_date]
    return {"orders": rows, "order_count": len(rows), "sales_total": sum(item["amount"] for item in rows)}


@app.get("/api/settings")
def get_settings():
    return {"model": settings.openai_model, "base_url": settings.openai_base_url,
            "openai_configured": bool(settings.openai_api_key), "dingtalk_enabled": settings.dingtalk_enabled}
