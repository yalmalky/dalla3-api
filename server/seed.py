"""Seed catalog categories/promos and optional demo experts for empty DB."""
from sqlalchemy.orm import Session

from . import models

CATEGORIES = [
    {"id": "makeup", "name": "مكياج", "icon": "Sparkles", "tint": "lavender"},
    {"id": "hair", "name": "شعر", "icon": "Scissors", "tint": "pink"},
    {"id": "nails", "name": "أظافر", "icon": "Hand", "tint": "mint"},
    {"id": "skin", "name": "بشرة", "icon": "Droplets", "tint": "lavender"},
    {"id": "henna", "name": "حناء", "icon": "Flower2", "tint": "pink"},
    {"id": "massage", "name": "مساج", "icon": "Heart", "tint": "mint"},
]


def ensure_promos(db: Session):
    if db.query(models.Promo).count():
        return
    db.add_all([
        models.Promo(id="pr_welcome", title="أول حجز عليك علينا", subtitle="خصم ٢٠٪ لكود WELCOME", cta="استخدمي العرض", code="WELCOME", badge="20%", theme="lavender", sponsored=False),
        models.Promo(id="pr_home", title="زيارة منزلية", subtitle="توصيل الخبيرة لباب بيتك", cta="شوفي القريبات", badge="بيت", theme="pink", sponsored=False),
    ])
    db.commit()
