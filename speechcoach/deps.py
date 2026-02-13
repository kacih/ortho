from __future__ import annotations

from typing import Dict, Tuple

def _check(mod: str) -> Tuple[bool, str]:
    try:
        __import__(mod)
        return True, ""
    except Exception as e:
        return False, str(e)

def check_dependencies() -> Dict[str, Tuple[bool, str]]:
    """Return dependency status for optional/critical modules.

    Keys are module names; values are (ok, detail).
    """
    mods = [
        "reportlab",
        "sounddevice",
        "soundfile",
        "faster_whisper",
    ]
    return {m: _check(m) for m in mods}

def format_dependency_report(status: Dict[str, Tuple[bool, str]]) -> str:
    lines = []
    for mod, (ok, detail) in status.items():
        if ok:
            lines.append(f"[OK] {mod}")
        else:
            lines.append(f"[WARN] {mod} missing: {detail}")
    return "\n".join(lines)
