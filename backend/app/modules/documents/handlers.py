"""Job handlers of the documents module."""

import uuid

from app.modules.documents import service
from app.modules.documents.models import Document
from app.modules.events import service as events
from app.worker.registry import job_handler


@job_handler("documents.extract_text")
def extract_text(db, payload: dict) -> dict:
    """Extract text from a text-based PDF (no OCR). Idempotent."""
    import pymupdf

    doc = db.get(Document, uuid.UUID(payload["document_id"]))
    if doc is None:
        return {"skipped": "document not found"}
    if doc.text_status in ("done", "empty"):
        return {"skipped": f"already {doc.text_status}"}
    try:
        with pymupdf.open(service.file_path(doc), filetype="pdf") as pdf:
            pages = pdf.page_count
            content = "\n".join(page.get_text() for page in pdf)
    except (RuntimeError, ValueError) as exc:  # corrupt or encrypted PDF: retrying will not help
        doc.text_status = "failed"
        events.record(db, "document", doc.id, "text_extract_failed", {"error": str(exc)[:500]}, "worker")
        return {"status": "failed"}
    content = content.replace("\x00", "").strip()
    doc.text_content = content or None
    doc.text_status = "done" if content else "empty"
    db.flush()
    events.record(db, "document", doc.id, "text_extracted",
                  {"pages": pages, "chars": len(content), "status": doc.text_status}, "worker")
    return {"status": doc.text_status, "chars": len(content)}
