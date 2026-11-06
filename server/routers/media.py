from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .. import models
from ..auth import get_current_user
from ..db import get_db

router = APIRouter(tags=["media"])

MAX_BYTES = 4 * 1024 * 1024  # client sends <= ~1600px JPEG (~300-600 KB); hard cap 4 MB
ALLOWED = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
MAX_PER_USER = 60


@router.post("/me/media")
async def upload_media(request: Request, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Raw-body upload (Content-Type = the file's MIME type). Returns a public path /api/media/{id}."""
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in ALLOWED:
        raise HTTPException(415, "صيغة الملف غير مدعومة (JPEG/PNG/WebP/PDF)")
    body = await request.body()
    if not body:
        raise HTTPException(400, "الملف فاضي")
    if len(body) > MAX_BYTES:
        raise HTTPException(413, "الملف كبير — الحد 4 ميجا")
    count = db.query(models.MediaBlob).filter_by(owner_id=user.id).count()
    if count >= MAX_PER_USER:
        raise HTTPException(429, "وصلتي الحد الأعلى للملفات المرفوعة")
    m = models.MediaBlob(owner_id=user.id, content_type=ctype, size=len(body), data=body)
    db.add(m)
    db.commit()
    return {"id": m.id, "url": f"/api/media/{m.id}", "size": m.size, "content_type": ctype}


@router.get("/media/{media_id}")
def get_media(media_id: str, db: Session = Depends(get_db)):
    m = db.get(models.MediaBlob, media_id)
    if not m:
        raise HTTPException(404, "not found")
    return Response(content=m.data, media_type=m.content_type,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.delete("/me/media/{media_id}")
def delete_media(media_id: str, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.get(models.MediaBlob, media_id)
    if m and m.owner_id == user.id:
        db.delete(m)
        db.commit()
    return {"ok": True}
