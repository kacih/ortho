from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

# ReportLab is OPTIONAL. The application must not crash if it is missing.
REPORTLAB_AVAILABLE = True
_REPORTLAB_IMPORT_ERROR: Optional[str] = None

try:
    from reportlab.pdfgen import canvas  # type: ignore
    from reportlab.lib.pagesizes import A4  # type: ignore
    from reportlab.lib.units import cm  # type: ignore
except Exception as e:  # ImportError or missing deps
    REPORTLAB_AVAILABLE = False
    _REPORTLAB_IMPORT_ERROR = str(e)
    canvas = None  # type: ignore
    A4 = (595.27, 841.89)  # fallback A4 points
    cm = 28.3465  # fallback

def require_reportlab() -> None:
    if not REPORTLAB_AVAILABLE:
        msg = "Export PDF indisponible : dépendance 'reportlab' non installée."
        if _REPORTLAB_IMPORT_ERROR:
            msg += f" (détail: {_REPORTLAB_IMPORT_ERROR})"
        raise RuntimeError(msg)

def _safe(v, default=""):
    return v if v is not None else default


def _weak_to_dict(row: Any) -> Dict[str, Any]:
    """Normalize a 'weakest phoneme' row into a dict.

    Supports:
    - dict-like objects (already normalized)
    - tuples/lists from DataLayer.get_phoneme_insights(): (phoneme, n, avg_score)
    - sqlite3.Row / mapping-like objects with keys
    """
    if isinstance(row, dict):
        return row
    if isinstance(row, (tuple, list)):
        try:
            phon, n, avg = row[0], row[1], row[2]
            return {"phoneme": phon, "n": n, "avg_score": avg}
        except Exception:
            return {}
    try:
        return {"phoneme": row["phoneme"], "n": row["n"], "avg_score": row["avg_score"]}
    except Exception:
        return {}


def _improve_to_dict(row: Any) -> Dict[str, Any]:
    """Normalize an 'improving phoneme' row into a dict.

    Supports:
    - dict-like objects
    - tuples/lists: (phoneme, delta, recent_avg, prev_avg, n)
    - sqlite3.Row / mapping-like objects with keys
    """
    if isinstance(row, dict):
        return row
    if isinstance(row, (tuple, list)):
        try:
            phon, delta, recent, prev, n = row[0], row[1], row[2], row[3], row[4]
            return {"phoneme": phon, "delta": delta, "recent_avg": recent, "prev_avg": prev, "n": n}
        except Exception:
            return {}
    try:
        return {
            "phoneme": row["phoneme"],
            "delta": row["delta"],
            "recent_avg": row["recent_avg"],
            "prev_avg": row["prev_avg"],
            "n": row["n"],
        }
    except Exception:
        return {}


def _sparkline(c: canvas.Canvas, x: float, y: float, w: float, h: float, values: List[float]):
    """Draw a tiny line chart (0..1) inside the box whose bottom-left is (x,y)."""
    if not values:
        c.setFont("Helvetica", 9)
        c.drawString(x, y + h/2, "—")
        return

    vals = [max(0.0, min(1.0, float(v))) for v in values]
    n = len(vals)
    if n == 1:
        pts = [(x + w/2, y + vals[0]*h)]
    else:
        dx = w / (n - 1)
        pts = [(x + i*dx, y + vals[i]*h) for i in range(n)]

    # border
    c.rect(x, y, w, h, stroke=1, fill=0)

    # polyline
    c.setLineWidth(1)
    for i in range(1, len(pts)):
        c.line(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1])


def build_child_progress_pdf(
    filepath: str,
    child: Any,
    summary: Dict[str, Any],
    recent_scores: List[Tuple[str, float]],
    weaknesses: List[Any],
    improving: List[Any],
    created_at: Optional[str] = None,
):
    require_reportlab()
    """One-page PDF progress report for a child."""
    c = canvas.Canvas(filepath, pagesize=A4)
    W, H = A4
    margin = 2 * cm
    x = margin
    y = H - margin

    created = created_at or datetime.now().strftime("%Y-%m-%d %H:%M")

    # Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x, y, "Bilan SpeechCoach — Progrès enfant")
    y -= 0.8 * cm

    c.setFont("Helvetica", 11)
    child_name = _safe(getattr(child, "__getitem__", lambda k: "")("name") if hasattr(child, "__getitem__") else None, "")
    try:
        child_name = child["name"]
    except Exception:
        pass
    try:
        child_id = child["id"]
    except Exception:
        child_id = _safe(summary.get("child_id"), "?")

    grade = ""
    try:
        grade = (child["grade"] or "").strip()
    except Exception:
        grade = ""

    c.drawString(x, y, f"Enfant : {child_name} (#{child_id})")
    y -= 0.55 * cm
    if grade:
        c.drawString(x, y, f"Classe : {grade}")
        y -= 0.55 * cm
    c.drawString(x, y, f"Date : {created}")
    y -= 0.9 * cm

    # Summary box
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "Résumé")
    y -= 0.5 * cm

    c.setFont("Helvetica", 10)
    total_sessions = int(summary.get("total_sessions") or 0)
    total_time = float(summary.get("total_time_sec") or 0.0)
    avg_score = float(summary.get("avg_final_score") or 0.0)
    level = int(summary.get("level") or 1)
    xp = int(summary.get("xp") or 0)
    streak = int(summary.get("streak") or 0)

    c.drawString(x, y, f"• Séances : {total_sessions}")
    c.drawString(x + 7*cm, y, f"• Temps total : {int(total_time//60)} min")
    y -= 0.45 * cm
    c.drawString(x, y, f"• Score moyen : {avg_score:.2f}")
    c.drawString(x + 7*cm, y, f"• Niveau/XP : {level} / {xp}")
    y -= 0.45 * cm
    c.drawString(x, y, f"• Streak : {streak}")
    y -= 0.8 * cm

    # Sparkline
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "Évolution (20 dernières séances)")
    y -= 0.5 * cm

    scores = [s for _, s in recent_scores][-20:]
    box_w = W - 2*margin
    box_h = 3.0 * cm
    _sparkline(c, x, y - box_h, box_w, box_h, scores)
    y -= box_h + 0.7*cm

    # Insights
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "Points d'attention")
    y -= 0.55*cm
    c.setFont("Helvetica", 10)

    if weaknesses:
        c.drawString(x, y, "Difficultés (Top 3) :")
        y -= 0.45*cm
        for r in weaknesses[:3]:
            rr = _weak_to_dict(r)
            phon = rr.get("phoneme") or ""
            val = float(rr.get("avg_score") or 0.0)
            cnt = int(rr.get("n") or 0)
            c.drawString(x + 0.5*cm, y, f"• {phon}  —  {val:.2f} (n={cnt})")
            y -= 0.4*cm
    else:
        c.drawString(x, y, "Difficultés : —")
        y -= 0.45*cm

    y -= 0.3*cm

    if improving:
        c.drawString(x, y, "En amélioration (Top 3) :")
        y -= 0.45*cm
        for r in improving[:3]:
            rr = _improve_to_dict(r)
            phon = rr.get("phoneme") or ""
            delta = float(rr.get("delta") or 0.0)
            c.drawString(x + 0.5*cm, y, f"• {phon}  —  {delta:+.2f}")
            y -= 0.4*cm
    else:
        c.drawString(x, y, "En amélioration : —")
        y -= 0.45*cm

    # Footer
    c.setFont("Helvetica-Oblique", 8)
    c.drawRightString(W - margin, margin/2, "Généré par SpeechCoach")
    c.showPage()
    c.save()


def build_group_progress_pdf(
    filepath: str,
    children: List[Any],
    fetcher,
):
    require_reportlab()
    """Multi-page PDF: one page per child. `fetcher(child_id)` returns (child, summary, recent_scores, weaknesses, improving)."""
    c = canvas.Canvas(filepath, pagesize=A4)
    created = datetime.now().strftime("%Y-%m-%d %H:%M")

    for i, child in enumerate(children):
        child_id = None
        try:
            child_id = child["child_id"]
        except Exception:
            try:
                child_id = child["id"]
            except Exception:
                pass
        if child_id is None:
            continue

        child_obj, summary, recent_scores, weaknesses, improving = fetcher(child_id)

        # Render using same layout on current canvas by writing to temp? Simpler: call child renderer into same canvas
        # We'll inline minimal rendering on existing canvas.
        W, H = A4
        margin = 2 * cm
        x = margin
        y = H - margin

        c.setFont("Helvetica-Bold", 16)
        c.drawString(x, y, "Bilan SpeechCoach — Classe / Groupe")
        y -= 0.8*cm

        # Child header
        name = ""
        try: name = child_obj["name"]
        except Exception: pass
        grade = ""
        try: grade = (child_obj["grade"] or "").strip()
        except Exception: pass

        c.setFont("Helvetica", 11)
        c.drawString(x, y, f"Enfant : {name} (#{child_id})")
        y -= 0.55*cm
        if grade:
            c.drawString(x, y, f"Classe : {grade}")
            y -= 0.55*cm
        c.drawString(x, y, f"Date : {created}")
        y -= 0.9*cm

        # Summary
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x, y, "Résumé")
        y -= 0.5*cm
        c.setFont("Helvetica", 10)
        total_sessions = int(summary.get("total_sessions") or 0)
        avg_score = float(summary.get("avg_final_score") or 0.0)
        c.drawString(x, y, f"• Séances : {total_sessions}")
        c.drawString(x + 7*cm, y, f"• Score moyen : {avg_score:.2f}")
        y -= 0.6*cm

        # Sparkline
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x, y, "Évolution (20 dernières séances)")
        y -= 0.5*cm
        scores = [s for _, s in recent_scores][-20:]
        box_w = W - 2*margin
        box_h = 3.0 * cm
        _sparkline(c, x, y - box_h, box_w, box_h, scores)
        y -= box_h + 0.7*cm

        # Weakness/improving
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x, y, "Synthèse")
        y -= 0.55*cm
        c.setFont("Helvetica", 10)
        if weaknesses:
            w = _weak_to_dict(weaknesses[0])
            c.drawString(x, y, f"Difficulté principale : {w.get('phoneme','')} ({float(w.get('avg_score') or 0.0):.2f})")
        else:
            c.drawString(x, y, "Difficulté principale : —")
        y -= 0.45*cm
        if improving:
            im = _improve_to_dict(improving[0])
            c.drawString(x, y, f"Meilleure progression : {im.get('phoneme','')} ({float(im.get('delta') or 0.0):+.2f})")
        else:
            c.drawString(x, y, "Meilleure progression : —")

        c.setFont("Helvetica-Oblique", 8)
        c.drawRightString(W - margin, margin/2, "Généré par SpeechCoach")
        c.showPage()

    c.save()
