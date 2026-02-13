import os
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, List, Dict, Any
from datetime import datetime

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class DashboardDialog(tk.Toplevel):
    def __init__(self, master, dl, audio, child_id: Optional[int], on_pick=None):
        super().__init__(master)
        self.on_pick = on_pick
        self.title("Dashboard Pro")
        self.geometry("1180x600")
        self.resizable(True, True)

        self.dl = dl
        self.audio = audio
        self.child_id = child_id

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        ttk.Label(top, text=f"DB: {dl.db_path}").pack(side="left")
        ttk.Button(top, text="Rafraîchir", command=self.refresh).pack(side="left", padx=8)
        ttk.Button(top, text="Supprimer ligne(s)", command=self.delete_selected).pack(side="left", padx=8)

                
        # ---- Zone centrale (table + graphe)
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # ---- Zone gauche : tableau
        left = ttk.Frame(container)
        left.pack(side="left", fill="both", expand=True)

        cols = ("id","created_at","child","story","expected","recognized","wer","final","phoneme")
        self.tree = ttk.Treeview(
            left,
            columns=cols,
            show="headings",
            height=20,
            selectmode="extended"
        )
        # Tags de coloration (score final)
        self.tree.tag_configure("score_green", background="#dff5e1")
        self.tree.tag_configure("score_yellow", background="#fff3cd")
        self.tree.tag_configure("score_orange", background="#ffe5d0")
        self.tree.tag_configure("score_red", background="#f8d7da")

        # Caches en mémoire (évite de dépendre des valeurs affichées)
        self._audio_by_iid: Dict[str, str] = {}
        self._sort_desc: Dict[str, bool] = {}      # col_id -> bool (desc)
        self._sort_cache: Dict[str, Dict[str, Any]] = {}  # iid -> {col_id: typed_value}

        widths = {
            "id": 60,
            "created_at": 150,
            "child": 70,
            "story": 220,
            "expected": 240,
            "recognized": 240,
            "wer": 70,
            "final": 70,
            "phoneme": 70,
        }

        # Clic en-tête = tri. IMPORTANT: lambda col=c pour éviter la capture tardive.
        for c in cols:
            self.tree.heading(c, text=c, command=lambda col=c: self._sort_by(col))
            self.tree.column(c, width=widths.get(c, 120), anchor="w")

        self.tree.pack(fill="both", expand=True)

        # ---- Zone droite : graphique
        right = ttk.LabelFrame(container, text="Évolution du score")
        right.pack(side="right", fill="both", expand=False, padx=(10, 0))

        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.ax = self.fig.add_subplot(111)

        self.ax.set_title("Sélectionnez une ligne…")
        self.ax.set_xlabel("Date")
        self.ax.set_ylabel("Score final")

        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Bind sélection + double-clic
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)
        self.tree.bind("<Double-1>", self._on_row_double_click)
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=8)
        ttk.Button(bottom, text="Rejouer audio", command=self.replay_selected).pack(side="left")
        ttk.Button(bottom, text="Fermer", command=self.destroy).pack(side="right")

        self.refresh()

    # ---------- Tri typé
    def _safe_int(self, x: Any, default: int = 0) -> int:
        try:
            return int(str(x).strip())
        except Exception:
            return default

    def _safe_float(self, x: Any, default: float = 0.0) -> float:
        try:
            s = str(x).strip().replace(",", ".")
            return float(s)
        except Exception:
            return default

    def _sort_by(self, col_id: str):
        """Tri Treeview par colonne, en utilisant un cache typé (int/float/datetime/str)."""
        desc = self._sort_desc.get(col_id, False)
        items = list(self.tree.get_children(""))

        def key(iid: str):
            cached = self._sort_cache.get(iid, {})
            if col_id in cached:
                return cached[col_id]
            # fallback texte (devrait être rare)
            try:
                return (self.tree.set(iid, col_id) or "").lower()
            except Exception:
                return ""

        items.sort(key=key, reverse=desc)
        for pos, iid in enumerate(items):
            self.tree.move(iid, "", pos)

        self._sort_desc[col_id] = not desc

    def refresh(self):
        # Nettoyage table + caches
        for i in self.tree.get_children():
            self.tree.delete(i)
        self._audio_by_iid.clear()
        self._sort_cache.clear()

        rows = self.dl.fetch_sessions_filtered(child_id=self.child_id, limit=800)
        for r in rows:
            session_id = self._safe_int(r["id"])
            child_id = self._safe_int(r["child_id"])

            dt = self._parse_created_at(r["created_at"])
            created_fr = self._fmt_created_at_fr(r["created_at"])

            wer_v = float(r["wer"] if r["wer"] is not None else 1.0)
            final_v = float(r["final_score"] if r["final_score"] is not None else 0.0)

            # Indicateur + tag couleur
            if final_v >= 0.85:
                ind, tag = "🟢", "score_green"
            elif final_v >= 0.70:
                ind, tag = "🟡", "score_yellow"
            elif final_v >= 0.55:
                ind, tag = "🟠", "score_orange"
            else:
                ind, tag = "🔴", "score_red"

            story_title = r["story_title"] or ""
            expected = (r["expected_text"] or "")[:120]
            recognized = (r["recognized_text"] or "")[:120]
            phoneme = r["phoneme_target"] or ""

            iid = self.tree.insert(
                "",
                "end",
                values=(
                    session_id,
                    created_fr,
                    child_id,
                    f"{ind} {story_title}",
                    expected,
                    recognized,
                    f"{wer_v:.2f}",
                    f"{final_v:.2f}",
                    phoneme,
                ),
                tags=(tag,),
            )

            # Cache audio + cache tri typé (évite le tri alphanumérique)
            self._audio_by_iid[iid] = (r["audio_path"] or "")
            self._sort_cache[iid] = {
                "id": session_id,
                "created_at": dt or datetime.min,
                "child": child_id,
                "story": (story_title or "").lower(),
                "expected": expected.lower(),
                "recognized": recognized.lower(),
                "wer": float(wer_v),
                "final": float(final_v),
                "phoneme": (phoneme or "").lower(),
            }
    def _parse_created_at(self, s: str):
        if not s:
            return None
        s = str(s).strip().replace("T", " ")
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None

    def _fmt_created_at_fr(self, s: str) -> str:
        dt = self._parse_created_at(s)
        return dt.strftime("%d/%m/%Y %H:%M") if dt else (s or "")

    def _selected_ids(self) -> List[int]:
        ids = []
        for item in self.tree.selection():
            vals = self.tree.item(item, "values")
            if vals:
                ids.append(int(vals[0]))
        return ids

    def delete_selected(self):
        ids = self._selected_ids()
        if not ids:
            messagebox.showinfo("Suppression", "Aucune ligne sélectionnée.")
            return
        if not messagebox.askyesno("Confirmer", f"Supprimer {len(ids)} ligne(s) ?"):
            return
        self.dl.delete_sessions_by_ids(ids)
        self.refresh()
        # UX: rester sur le TDB après suppression (évite de revenir visuellement à la fenêtre principale)
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def replay_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        audio_path = self._audio_by_iid.get(iid, "")

        if audio_path and os.path.exists(audio_path):
            self.audio.play_wav(audio_path)
        else:
            messagebox.showwarning("Audio introuvable", "Fichier audio manquant pour cette session.")

    def _get_selected_row(self):
        sel = self.tree.selection()
        if not sel:
            return None
        vals = self.tree.item(sel[0], "values")
        return vals

    def _on_row_double_click(self, event=None):
        # Double-clic: rejoue l'audio + conserve le comportement de sélection (graph)
        self.replay_selected()
        self._on_row_select(event)
    
    def _on_row_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return

        vals = self.tree.item(sel[0], "values")
        # Colonnes actuelles du TDB :
        # ("id","created","child","story","expected","recognized","wer","final","phoneme")
        try:
            child_id = int(vals[2])
        except Exception:
            return

        phoneme = (vals[8] or "").strip() or None
        self._plot_evolution(child_id, phoneme)

        # Callback externe optionnel (ex: autre panneau)
        if callable(self.on_pick):
            try:
                session_id = int(vals[0])
            except Exception:
                session_id = None
            self.on_pick(session_id=session_id, child_id=child_id, phoneme=phoneme)

    def _plot_evolution(self, child_id: int, phoneme: str | None):
        # Récupère sessions enfant
        rows = self.dl.fetch_sessions_filtered(child_id=child_id, limit=500)

        pts = []
        for r in rows:
            # r est une sqlite3.Row (accès par clé OK)
            if phoneme and (r["phoneme_target"] or "") != phoneme:
                continue

            created = r["created_at"]
            score = r["final_score"]
            if created is None or score is None:
                continue

            created_norm = str(created).replace("T", " ")
            try:
                dt = datetime.fromisoformat(created_norm)
            except Exception:
                try:
                    dt = datetime.strptime(created_norm, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue

            pts.append((dt, float(score)))

        pts.sort(key=lambda x: x[0])

        self.ax.clear()

        title = f"Enfant {child_id}"
        if phoneme:
            title += f" — phonème: {phoneme}"
        self.ax.set_title(title)
        self.ax.set_xlabel("Date")
        self.ax.set_ylabel("Score final")

        if not pts:
            self.ax.text(0.5, 0.5, "Aucune donnée", ha="center", va="center", transform=self.ax.transAxes)
            self.canvas.draw()
            return

        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]

        self.ax.plot(xs, ys, marker="o")
        self.ax.grid(True, alpha=0.25)
        self.fig.autofmt_xdate(rotation=30)

        self.canvas.draw()
