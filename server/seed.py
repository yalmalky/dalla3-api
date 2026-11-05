"""Seed catalog categories/promos and optional demo experts for empty DB."""
from sqlalchemy.orm import Session

from . import models

CATEGORIES = [
    {"id": "makeup", "name": "مكياج", "icon": "brush", "tint": "--pink-50"},
    {"id": "hair", "name": "شعر", "icon": "scissors", "tint": "--lav-50"},
    {"id": "nails", "name": "أظافر", "icon": "gem", "tint": "--peach-50"},
    {"id": "skin", "name": "بشرة", "icon": "droplet", "tint": "--lav-50"},
    {"id": "henna", "name": "حناء", "icon": "leaf", "tint": "--sage-50"},
    {"id": "massage", "name": "مساج", "icon": "flower", "tint": "--mint-50"},
]


def ensure_promos(db: Session):
    if db.query(models.Promo).count():
        return
    db.add_all([
        models.Promo(id="pr_home", title="زيارة منزلية", subtitle="توصيل الخبيرة لباب بيتك", cta="شوفي القريبات", badge="بيت", theme="pink", sponsored=False),
    ])
    db.commit()
