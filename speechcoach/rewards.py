"""Rewards / collections.

Theme: "Pokemon" (requested). This module stores *only text labels*.
No copyrighted images are bundled.

Design goal: one new card per completed child session, without duplicates,
until the set is complete.
"""

from __future__ import annotations

import random
from typing import Iterable, Optional, List


# Starter set (text only). Extend as you like.
POKEMON_CARDS_STARTER: List[str] = [
    "Pikachu",
    "Évoli",
    "Salamèche",
    "Carapuce",
    "Bulbizarre",
    "Rondoudou",
    "Psykokwak",
    "Miaouss",
    "Poussifeu",
    "Gobou",
    "Arcko",
    "Tiplouf",
    "Ouisticram",
    "Tortipouss",
    "Zorua",
    "Goupix",
    "Dracaufeu",
    "Tortank",
    "Florizarre",
    "Lucario",
    "Riolu",
    "Gardevoir",
    "Dracolosse",
    "Lokhlass",
    "Mew",
    "Mewtwo",
    "Togepi",
    "Magicarpe",
    "Léviator",
    "Ronflex",
]


def pick_new_card(owned: Iterable[str], catalog: Optional[List[str]] = None) -> Optional[str]:
    """Pick a new (unowned) card from the catalog, or None if completed."""
    catalog = catalog or POKEMON_CARDS_STARTER
    owned_set = {str(x).strip() for x in owned if x}
    candidates = [c for c in catalog if c not in owned_set]
    if not candidates:
        return None
    return random.choice(candidates)
