import os
import re
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
        self.geometry("1770x600")
        self.resizable(True, True)

        self.dl = dl
        self.audio = audio
        self.child_id = child_id

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        ttk.Label(top, text=f"DB: {dl.db_path}").pack(side="left")
        ttk.Button(top, text="Rafraîchir", command=self.refresh).pack(side="left", padx=8)
        ttk.Button(top, text="Supprimer ligne(s)", command=self.delete_selected).pack(side="left", padx=8)

        # ---- Filtres (enfant + phonème)
        ttk.Label(top, text="Enfant:").pack(side="left", padx=(20, 4))
        self.child_filter = tk.StringVar(value="(sélection)")
        self.child_combo = ttk.Combobox(top, textvariable=self.child_filter, state="readonly", width=22)
        self.child_combo.pack(side="left")
        self.child_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        ttk.Label(top, text="Phonème:").pack(side="left", padx=(14, 4))
        self.phoneme_filter = tk.StringVar(value="Tous")
        self.phoneme_combo = ttk.Combobox(top, textvariable=self.phoneme_filter, state="readonly", width=14)
        self.phoneme_combo.pack(side="left")
        self.phoneme_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        ttk.Button(top, text="Réinitialiser", command=self.reset_filters).pack(side="left", padx=10)

        self._child_choices = []  # list of (label, child_id)

                
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
        self.ax.set_xlabel("Observation")
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
        # Update chart
        self._plot_evolution()


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

    def reset_filters(self):
        self.child_filter.set("(sélection)")
        self.phoneme_filter.set("Tous")
        self.refresh()

    def _get_selected_child_id(self) -> Optional[int]:
        label = (self.child_filter.get() or "").strip()
        if label == "Tous":
            return None
        if label == "(sélection)":
            return self.child_id
        try:
            m = re.search(r"#(\d+)\)", label)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return self.child_id

    def _get_selected_phoneme(self) -> Optional[str]:
        p = (self.phoneme_filter.get() or "").strip()
        if not p or p == "Tous":
            return None
        if p == "(non renseigné)":
            return ""
        return p

    def refresh(self):
        # ---- Update filter choices (child / phoneme)
        try:
            children = self.dl.list_children()
        except Exception:
            children = []

        child_values = ["(sélection)", "Tous"]
        for r in children:
            try:
                child_values.append(f'{r["name"]} (#{r["id"]})')
            except Exception:
                pass
        child_values = list(dict.fromkeys(child_values))
        self.child_combo["values"] = child_values
        if self.child_filter.get() not in child_values:
            self.child_filter.set("(sélection)")

        sel_child_id = self._get_selected_child_id()

        try:
            phonemes = self.dl.list_distinct_phonemes(child_id=sel_child_id)
        except Exception:
            phonemes = []
        ph_values = ["Tous"]
        if "" in phonemes:
            ph_values.append("(non renseigné)")
        ph_values += [p for p in phonemes if p]
        ph_values = list(dict.fromkeys(ph_values))
        self.phoneme_combo["values"] = ph_values
        if self.phoneme_filter.get() not in ph_values:
            self.phoneme_filter.set("Tous")

        sel_ph = self._get_selected_phoneme()

        # ---- Clear table + caches
        for i in self.tree.get_children():
            self.tree.delete(i)
        self._audio_by_iid.clear()
        self._sort_cache.clear()

        # ---- Fetch & render
        rows = self.dl.fetch_sessions_filtered(child_id=sel_child_id, phoneme_target=sel_ph, limit=800)
        for r in rows:
            session_id = self._safe_int(r["id"])
            child_id = self._safe_int(r["child_id"])

            created_fr = self._fmt_created_at_fr(r["created_at"])

            wer_v = float(r["wer"] if r["wer"] is not None else 1.0)
            final_v = float(r["final_score"] if r["final_score"] is not None else 0.0)
            phon = (r["phoneme_target"] or "").strip()

            # Score tag
            if final_v >= 0.85:
                ind, tag = "🟢", "score_green"
            elif final_v >= 0.70:
                ind, tag = "🟡", "score_yellow"
            elif final_v >= 0.50:
                ind, tag = "🟠", "score_orange"
            else:
                ind, tag = "🔴", "score_red"

            expected = (r["expected_text"] or "").strip()
            recognized = (r["recognized_text"] or "").strip()
            story = (r["story_title"] or r["story_id"] or "").strip()

            iid = f"sess_{session_id}"
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    session_id,
                    created_fr,
                    child_id,
                    story,
                    expected[:80],
                    recognized[:80],
                    f"{wer_v:.3f}",
                    f"{ind} {final_v:.2f}",
                    phon,
                ),
                tags=(tag,),
            )

            # cache typed values for sorting
            dt = self._parse_created_at(r["created_at"])
            self._sort_cache[iid] = {
                "id": session_id,
                "created_at": dt or datetime.min,
                "child": child_id,
                "story": story.lower(),
                "expected": expected.lower(),
                "recognized": recognized.lower(),
                "wer": wer_v,
                "final": final_v,
                "phoneme": phon.lower(),
            }

            ap = (r["audio_path"] or "").strip()
            if ap:
                self._audio_by_iid[iid] = ap

        # refresh graph from the currently selected row (or first row)
        self._plot_evolution()

    def _parse_created_at(self, s: Any) -> Optional[datetime]:
        if not s:
            return None
        s = str(s).strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s.replace("T", " "))
        except Exception:
            return None

    def _fmt_created_at_fr(self, s: Any) -> str:
        dt = self._parse_created_at(s)
        if not dt:
            return str(s) if s else ""
        return dt.strftime("%d/%m/%Y %H:%M:%S")

    def _selected_ids(self) -> List[int]:
        ids = []
        for iid in self.tree.selection():
            try:
                ids.append(int(self.tree.set(iid, "id")))
            except Exception:
                pass
        return ids

    def delete_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        # IMPORTANT (Windows/Tk): keep dialogs modal to THIS Toplevel.
        # Otherwise, focus can jump back to the main window after the messagebox.
        if not messagebox.askyesno(
            "Confirmer",
            f"Supprimer {len(ids)} ligne(s) du dashboard ?",
            parent=self,
        ):
            return
        try:
            self.dl.delete_sessions_by_ids(ids)
        except Exception as e:
            messagebox.showerror("Erreur", f"Suppression impossible: {e}", parent=self)
            return
        self.refresh()
        # Keep dashboard visible/focused after deletion (Windows tends to return
        # focus to the root window when a messagebox closes).
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

        # Re-focus the dashboard after refresh.
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def replay_selected(self):
        r = self._get_selected_row()
        if not r:
            return
        ap = r.get("audio_path") or ""
        if not ap:
            return
        try:
            self.audio.play_file(ap)
        except Exception as e:
            messagebox.showerror("Audio", f"Lecture impossible: {e}")

    def _get_selected_row(self) -> Optional[Dict[str, Any]]:
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        session_id = None
        try:
            session_id = int(self.tree.set(iid, "id"))
        except Exception:
            return None

        # Fetch from DB (source of truth)
        try:
            rows = self.dl.fetch_sessions_filtered(limit=1000)
        except Exception:
            return None
        for r in rows:
            try:
                if int(r["id"]) == session_id:
                    return dict(r)
            except Exception:
                continue
        return None

    def _on_row_double_click(self, _event=None):
        r = self._get_selected_row()
        if not r:
            return
        if self.on_pick:
            try:
                self.on_pick(int(r["id"]))
            except Exception:
                pass
        # replay audio on double click as a convenience
        self.replay_selected()

    def _on_row_select(self, _event=None):
        # When selecting a row, sync filters (child + phoneme) and refresh the graph.
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        values = item.get("values") or []
        # Expected columns in tree: (id, child_name, phoneme, score, created_at, ...)
        # We rely on hidden mappings stored on insertion (row meta) if present.
        meta = item.get("tags") or []
        # Prefer explicit mapping if the tree stores child_id in iid
        try:
            child_id = int(sel[0])
        except Exception:
            child_id = None

        phoneme = None
        if len(values) >= 3:
            phoneme = values[2]

        if child_id is not None:
            self.child_id = child_id
            # If there is a child filter dropdown, keep it in sync
            try:
                self.child_filter_var.set(str(child_id))
            except Exception:
                pass

        if phoneme:
            try:
                self.phoneme_filter_var.set(str(phoneme))
            except Exception:
                pass

        self._plot_evolution()

    
    def _plot_evolution(self):
        """Plot evolution of final_score for selected child and phoneme."""
        try:
            child_id = self._get_selected_child_id()
            phoneme = self._get_selected_phoneme()
        except Exception:
            child_id = None
            phoneme = "Tous"

        self.ax.clear()
        self.ax.grid(True)

        if not child_id:
            self.ax.set_title("Choisissez un enfant pour voir l'évolution")
            self.ax.set_xlabel("Observation")
            self.ax.set_ylabel("Score final")
            self.canvas.draw()
            return

        try:
            series = self.dl.get_score_series(int(child_id), phoneme)
        except Exception:
            series = []

        if not series:
            ph = phoneme if phoneme and phoneme != "Tous" else "tous phonèmes"
            self.ax.set_title(f"Aucune donnée pour {ph}")
            self.ax.set_xlabel("Observation")
            self.ax.set_ylabel("Score final")
            self.canvas.draw()
            return

        # Parse dates for a nicer x-axis (fallback to index if parse fails)
        xs = []
        ys = []
        for dt, sc in series:
            ys.append(float(sc))
            try:
                # Accept ISO timestamps
                d = datetime.fromisoformat(str(dt).replace("Z",""))
                xs.append(d)
            except Exception:
                xs.append(len(xs) + 1)

        try:
            self.ax.plot(xs, ys, marker="o")
        except Exception:
            # fallback simple
            self.ax.plot(list(range(1, len(ys)+1)), ys, marker="o")

        ph = phoneme if phoneme and phoneme != "Tous" else "Tous"
        self.ax.set_title(f"Évolution du score — Phonème: {ph}")
        self.ax.set_xlabel("Observation")
        self.ax.set_ylabel("Score final")
        self.canvas.draw()

