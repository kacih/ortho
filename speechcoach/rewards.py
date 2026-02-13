
"""Rewards / collections (Pokemon-themed, local assets).

Important: We ship *original* icon assets (simple generated icons) to keep things legal.
Card names are user-facing labels; icons are generic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json
import random
from datetime import datetime, date

from .config import DATA_DIR
from .utils_text import now_iso

RARITY_ORDER = ["common", "rare", "legendary"]

@dataclass(frozen=True)
class Card:
    id: str
    name: str
    rarity: str           # common|rare|legendary
    min_level: int
    icon_path: str        # relative to resources/cards

def load_catalog(cards_catalog_path: str) -> List[Card]:
    p = Path(cards_catalog_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    out: List[Card] = []
    for r in data:
        out.append(Card(
            id=str(r.get("id")),
            name=str(r.get("name")),
            rarity=str(r.get("rarity")),
            min_level=int(r.get("min_level", 1)),
            icon_path=str(r.get("icon")),
        ))
    return out

def rarity_weights_for_level(level: int) -> Dict[str, float]:
    """Adaptive rarity: frequent commons early; rares/legendary ramp with level.

    The exact curve is intentionally simple & explainable.
    """
    level = max(1, int(level))
    if level <= 2:
        return {"common": 0.95, "rare": 0.05, "legendary": 0.0}
    if level <= 4:
        return {"common": 0.85, "rare": 0.15, "legendary": 0.0}
    if level <= 7:
        return {"common": 0.70, "rare": 0.28, "legendary": 0.02}
    return {"common": 0.60, "rare": 0.33, "legendary": 0.07}

def _pick_rarity(level: int) -> str:
    w = rarity_weights_for_level(level)
    r = random.random()
    acc = 0.0
    for k in RARITY_ORDER:
        acc += float(w.get(k, 0.0))
        if r <= acc:
            return k
    return "common"

def compute_xp_gain(final_score: float, used_today: bool) -> int:
    """XP is primarily about *showing up*, then about doing well."""
    base = 5
    # gentle performance bonus (0..+7)
    bonus = 0
    try:
        s = float(final_score)
        if s >= 0.85:
            bonus = 7
        elif s >= 0.75:
            bonus = 5
        elif s >= 0.65:
            bonus = 3
        elif s >= 0.55:
            bonus = 1
    except Exception:
        bonus = 0

    # discourage grinding: only one full XP per day
    if used_today:
        base = 2
        bonus = min(bonus, 2)

    return int(base + bonus)

def level_from_xp(xp: int) -> int:
    """Slowly increasing curve: level grows with sqrt(xp)."""
    xp = max(0, int(xp))
    # Level 1 at xp=0 ; Level 2 ~ 9 ; Level 4 ~ 81 ; Level 8 ~ 441
    return max(1, int((xp ** 0.5) // 3) + 1)

def choose_new_card_for_child(
    *,
    catalog: List[Card],
    owned_card_ids: List[str],
    child_level: int
) -> Optional[Card]:
    """Choose a non-owned card, adapted to level and rarity.
    Returns None if collection is complete for all eligible cards.
    """
    owned = set(owned_card_ids or [])

    # eligible by level
    eligible = [c for c in catalog if c.min_level <= child_level and c.id not in owned]
    if not eligible:
        return None

    # rarity bucket first (adaptive), then random inside bucket
    desired = _pick_rarity(child_level)
    bucket = [c for c in eligible if c.rarity == desired]
    if not bucket:
        # fallback: any eligible
        bucket = eligible
    return random.choice(bucket)

