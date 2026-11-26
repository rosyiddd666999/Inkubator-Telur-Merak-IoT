from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Alert, User
from ..schemas import AlertResponse
from ..auth import require_role

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])

# Default 100: sebelumnya endpoint ini mengembalikan SEMUA baris tanpa batas
# (7.116 baris di produksi) lalu AlertPanel merendernya sekaligus — berat di
# sisi server maupun browser. `limit=0` tetap diperbolehkan untuk ekspor.
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


@router.get("", response_model=List[AlertResponse])
def list_alerts(
    limit: int = Query(DEFAULT_LIMIT, ge=0, le=MAX_LIMIT,
                       description="0 = tanpa batas (ekspor)"),
    offset: int = Query(0, ge=0),
    unread: Optional[bool] = Query(None, description="Filter alert belum dibaca"),
    current_user: User = Depends(require_role("pemilik", "staff")),
    db: Session = Depends(get_db),
):
    """Alert terbaru, terurut menurun waktu + pagination.

    `count` total tidak ikut di body agar bentuk response tetap array
    (kompatibel dengan klien lama yang hanya memanggil `data.map(...)`).
    """
    query = db.query(Alert)
    if unread is not None:
        query = query.filter(Alert.is_read.is_(bool(unread)))
    query = query.order_by(Alert.created_at.desc(), Alert.id.desc())
    if limit:
        query = query.offset(offset).limit(limit)
    return query.all()


@router.put("/{alert_id}/read", response_model=AlertResponse)
def mark_alert_read(alert_id: int, current_user: User = Depends(require_role("pemilik", "staff")), db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert tidak ditemukan")
    alert.is_read = True
    db.commit()
    db.refresh(alert)
    return alert


@router.delete("/{alert_id}")
def delete_alert(alert_id: int, current_user: User = Depends(require_role("pemilik")), db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert tidak ditemukan")
    db.delete(alert)
    db.commit()
    return {"message": f"Alert {alert_id} berhasil dihapus"}
