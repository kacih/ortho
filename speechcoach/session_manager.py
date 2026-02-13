from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List


@dataclass(frozen=True)
class SessionPlan:
    """Predictable plan for a guided session (Sprint 1).

    Notes:
    - We keep fields explicit and serializable (to store in sessions.plan_json).
    - Targeting/difficulty will come later; Sprint 1 focuses on duration/pacing.
    """

    plan_id: str = "standard"
    name: str = "Standard"
    mode: str = "standard"  # decouverte | standard | intensif | libre

    duration_min: int = 5
    rounds: int = 14

    warmup_ratio: float = 0.15
    cooldown_ratio: float = 0.15

    # Minimal adaptation (Sprint 1): if a turn is hard, repeat once.
    repeat_on_fail: bool = True
    max_repeats_per_sentence: int = 1

    def to_json_dict(self) -> Dict[str, Any]:
        return asdict(self)


def preset_plans() -> List[SessionPlan]:
    """Hardcoded presets for Sprint 1 (no DB persistence yet)."""

    return [
        SessionPlan(
            plan_id="decouverte",
            name="Découverte",
            mode="decouverte",
            duration_min=3,
            rounds=8,
            warmup_ratio=0.25,
            cooldown_ratio=0.25,
            repeat_on_fail=True,
            max_repeats_per_sentence=1,
        ),
        SessionPlan(
            plan_id="standard",
            name="Standard",
            mode="standard",
            duration_min=5,
            rounds=14,
            warmup_ratio=0.15,
            cooldown_ratio=0.15,
            repeat_on_fail=True,
            max_repeats_per_sentence=1,
        ),
        SessionPlan(
            plan_id="intensif",
            name="Intensif",
            mode="intensif",
            duration_min=9,
            rounds=24,
            warmup_ratio=0.10,
            cooldown_ratio=0.10,
            repeat_on_fail=True,
            max_repeats_per_sentence=2,
        ),
    ]


def get_preset_plan(plan_id: str) -> SessionPlan:
    for p in preset_plans():
        if p.plan_id == plan_id:
            return p
    # fallback
    return preset_plans()[1]


def build_session_plan(child: Optional[Dict[str, Any]], duration_min: int = 3) -> SessionPlan:
    """Legacy auto-plan (child mode).

    Keeps the previous behavior, but now returns a SessionPlan compatible
    with the new plan metadata/logging.
    """

    age = None
    try:
        if child is not None:
            age = child.get("age")
    except Exception:
        age = None

    if duration_min <= 3:
        base_rounds = 3
    elif duration_min <= 5:
        base_rounds = 4
    elif duration_min <= 10:
        base_rounds = 6
    else:
        base_rounds = 8

    if age is None:
        rounds = base_rounds
    elif age <= 6:
        rounds = min(base_rounds, 3 if duration_min <= 3 else 4)
    elif age <= 8:
        rounds = min(base_rounds + 1, 5 if duration_min <= 5 else 7)
    else:
        rounds = min(10, base_rounds + 1)

    return SessionPlan(
        plan_id="auto_kid",
        name="Auto enfant",
        mode="auto",
        duration_min=int(duration_min),
        rounds=int(rounds),
        warmup_ratio=0.20,
        cooldown_ratio=0.20,
        repeat_on_fail=True,
        max_repeats_per_sentence=1,
    )
