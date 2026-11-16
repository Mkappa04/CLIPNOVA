"""Brand Kit: logo upload/replace/delete + overlay settings (position, size, opacity, margin, on/off)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.exceptions import NotFoundError, ValidationFailed
from backend.database.session import get_db
from backend.editing import logo_overlay as brand
from backend.editing.config import OUT_H, OUT_W

router = APIRouter(prefix="/api/brand-kit", tags=["brand-kit"])


def _state(db: Session, warnings: list[str] | None = None) -> dict:
    s = brand.load_settings(db)
    asset = brand.current_logo(db)
    logo = placement = None
    if asset is not None:
        logo = {"id": asset.id, "original_name": asset.original_name, "width": asset.width, "height": asset.height,
                "file_size": asset.file_size, "has_alpha": asset.has_alpha,
                "created_at": asset.created_at.isoformat() + "Z", "url": f"/api/brand-kit/logo?v={asset.id[:8]}"}
        x, y, w, h, corner, pw = brand.place(asset.width, asset.height, s)
        placement = {"x": x, "y": y, "w": w, "h": h, "corner": corner, "frame": [OUT_W, OUT_H], "warnings": pw}
    st = get_settings()
    return {"settings": s.model_dump(), "logo": logo, "placement": placement, "warnings": warnings or [],
            "limits": {"max_mb": st.brand_logo_max_mb, "max_px": st.brand_logo_max_px, "format": "PNG"}}


@router.get("")
def get_brand_kit(db: Session = Depends(get_db)) -> dict:
    return _state(db)


@router.put("/settings")
def put_settings(body: brand.BrandSettings, db: Session = Depends(get_db)) -> dict:
    brand.save_settings(db, body)
    return _state(db)


@router.post("/logo", status_code=201)
async def upload_logo(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    """PNG only (checked on the content, not the name), size-limited, decoded and re-encoded server side.
    Replaces the current logo."""
    limit = int(get_settings().brand_logo_max_mb * 1024 * 1024)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ValidationFailed(f"Logo troppo grande (massimo {get_settings().brand_logo_max_mb:g} MB)",
                               code="logo_too_large")
    _, warnings = brand.store_logo(db, data, file.filename or "logo.png")
    return _state(db, warnings)


@router.get("/logo")
def get_logo(db: Session = Depends(get_db)) -> FileResponse:
    asset = brand.current_logo(db)
    if asset is None:
        raise NotFoundError("Nessun logo caricato")
    p = brand.logo_path(asset)
    if not p.exists():
        raise NotFoundError("File del logo mancante")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.delete("/logo")
def delete_logo(confirm: bool = False, db: Session = Depends(get_db)) -> dict:
    if not confirm:
        raise ValidationFailed("Eliminare il logo richiede conferma (confirm=true)", code="confirmation_required")
    asset = brand.current_logo(db)
    if asset is None:
        raise NotFoundError("Nessun logo caricato")
    brand.delete_asset(db, asset)
    db.commit()
    return _state(db)
