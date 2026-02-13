from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass(frozen=True)
class SessionPlan:
    """A simple plan for an auto-guided session.

    The goal is to make sessions predictable and short for children,
    while keeping enough repetitions to be useful.
    """
    duration_min: int = 3
    rounds: int = 6
    difficulty: str = "auto"  # reserved for future use
    reward_points: int = 1    # reserved for future use


def build_session_plan(child: Optional[Dict[str, Any]], duration_min: int = 3) -> SessionPlan:
    """Return a session plan adapted to the child's age.

    Rules of thumb (kid UX):
    - CP (~6): shorter, fewer rounds; avoid fatigue.
    - CE2 (~8): slightly longer; still keep it compact.
    """
    age = None
    try:
        if child is not None:
            age = child.get("age")
    except Exception:
        age = None

    # Default pacing: conservative, because each round includes TTS + prompt + record + ASR + analysis.
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
        # CP: very short & confidence-first
        rounds = min(base_rounds, 3 if duration_min <= 3 else 4)
    elif age <= 8:
        # CE2: slightly more reps, still compact
        rounds = min(base_rounds + 1, 5 if duration_min <= 5 else 7)
    else:
        rounds = min(10, base_rounds + 1)

    return SessionPlan(duration_min=int(duration_min), rounds=int(rounds))
