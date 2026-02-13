import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional
from datetime import datetime

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from speechcoach.reports_pdf import build_child_progress_pdf

class ProgressDialog(tk.Toplevel):
    """Child-friendly progress dashboard for adults.

    Sprint 6 goal: in a few seconds, show where the child stands, what is weak,
    and what is improving, plus a 1-click CSV export.
    """

    def __init__(self, master, dl, child_id: Optional[int]):
        super().__init__(master)
        self.title("Progrès enfant")
        self.geometry("1100x650")
        self.resizable(True, True)

        self.dl = dl
        self.child_id = child_id

        top = ttk.Frame(self)
        top.pack(fill="x", padx=12, pady=10)

        ttk.Label(top, text="Enfant:").pack(side="left")
        self.child_var = tk.StringVar(value="(sélection)")
        self.child_combo = ttk.Combobox(top, textvariable=self.child_var, state="readonly", width=26)
        self.child_combo.pack(side="left", padx=(6, 12))
        self.child_combo.bind("<<ComboboxSelected>>", lambda e: self._on_pick_child())

        ttk.Button(top, text="Rafraîchir", command=self.refresh).pack(side="left")
        ttk.Button(top, text="Exporter CSV…", command=self.export_csv).pack(side="left", padx=8)
        ttk.Button(top, text="Exporter PDF…", command=self.export_pdf).pack(side="left")
        ttk.Button(top, text="Fermer", command=self.destroy).pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Left: metrics and insights
        left = ttk.Frame(body)
        left.pack(side="left", fill="y")

        self.metrics = ttk.LabelFrame(left, text="Résumé")
        self.metrics.pack(fill="x", pady=(0, 10))

        self.lbl_total = ttk.Label(self.metrics, text="Séances: —")
        self.lbl_total.pack(anchor="w", padx=10, pady=3)
        self.lbl_time = ttk.Label(self.metrics, text="Temps total: —")
        self.lbl_time.pack(anchor="w", padx=10, pady=3)
        self.lbl_avg = ttk.Label(self.metrics, text="Score moyen: —")
        self.lbl_avg.pack(anchor="w", padx=10, pady=3)
        self.lbl_level = ttk.Label(self.metrics, text="Niveau / XP: —")
        self.lbl_level.pack(anchor="w", padx=10, pady=3)
        self.lbl_streak = ttk.Label(self.metrics, text="Streak: —")
        self.lbl_streak.pack(anchor="w", padx=10, pady=3)

        self.insights = ttk.LabelFrame(left, text="À travailler / En progrès")
        self.insights.pack(fill="both", expand=True)

        ttk.Label(self.insights, text="Difficultés (Top 3)").pack(anchor="w", padx=10, pady=(8, 4))
        self.lst_weak = tk.Listbox(self.insights, height=6)
        self.lst_weak.pack(fill="x", padx=10)

        ttk.Label(self.insights, text="En amélioration (Top 3)").pack(anchor="w", padx=10, pady=(12, 4))
        self.lst_improve = tk.Listbox(self.insights, height=6)
        self.lst_improve.pack(fill="x", padx=10)

        self.lbl_advice = ttk.Label(self.insights, text="", wraplength=340, justify="left")
        self.lbl_advice.pack(fill="x", padx=10, pady=(12, 8))

        # Right: chart
        right = ttk.LabelFrame(body, text="Évolution (20 dernières séances)")
        right.pack(side="right", fill="both", expand=True, padx=(12, 0))

        self.fig = Figure(figsize=(6.6, 4.8), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Séance")
        self.ax.set_ylabel("Score final")
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self._load_children_choices()
        self.refresh()

    def _load_children_choices(self):
        try:
            rows = self.dl.list_children() or []
        except Exception:
            rows = []

        values = ["(sélection)"]
        for r in rows:
            try:
                values.append(f"{r['name']} (#{r['id']})")
            except Exception:
                pass
        self.child_combo["values"] = values

        # Keep selection stable
        if self.child_id:
            # Try to auto-select current child
            for v in values:
                if f"(#{self.child_id})" in v:
                    self.child_var.set(v)
                    return
        if self.child_var.get() not in values:
            self.child_var.set("(sélection)")

    def _on_pick_child(self):
        label = (self.child_var.get() or "").strip()
        if not label or label == "(sélection)":
            return
        try:
            # label format "Name (#id)"
            if "(#" in label and ")" in label:
                cid = int(label.split("(#", 1)[1].split(")", 1)[0])
                self.child_id = cid
        except Exception:
            pass
        self.refresh()

    def refresh(self):
        if not self.child_id:
            self._plot_empty("Sélectionnez un enfant")
            self._set_empty_metrics()
            return

        # --- metrics
        s = self.dl.get_child_session_summary(self.child_id)
        total = int(s.get("total_sessions", 0) or 0)
        dur = float(s.get("total_duration_sec", 0.0) or 0.0)
        avg = float(s.get("avg_score", 0.0) or 0.0)
        xp = int(s.get("xp", 0) or 0)
        lvl = int(s.get("level", 1) or 1)
        streak = int(s.get("streak", 0) or 0)

        self.lbl_total.configure(text=f"Séances: {total}")
        self.lbl_time.configure(text=f"Temps total: {self._fmt_duration(dur)}")
        self.lbl_avg.configure(text=f"Score moyen: {avg:.2f}")
        self.lbl_level.configure(text=f"Niveau / XP: {lvl} / {xp}")
        self.lbl_streak.configure(text=f"Streak: {streak} jour(s)")

        # --- insights
        self.lst_weak.delete(0, tk.END)
        self.lst_improve.delete(0, tk.END)
        ins = self.dl.get_phoneme_insights(self.child_id)

        weakest = ins.get("weakest") or []
        improving = ins.get("improving") or []

        if not weakest:
            self.lst_weak.insert(tk.END, "(pas assez de données)")
        else:
            for p, n, a in weakest:
                self.lst_weak.insert(tk.END, f"{p}  →  {a:.0%}  (n={n})")

        if not improving:
            self.lst_improve.insert(tk.END, "(pas d'amélioration détectée)")
        else:
            for p, d, recent, prev, n in improving:
                self.lst_improve.insert(tk.END, f"{p}  +{d:.0%}  (récent {recent:.0%} / avant {prev:.0%})")

        self.lbl_advice.configure(text=self._make_advice(weakest, improving, total))

        # --- chart
        series = self.dl.get_child_recent_scores(self.child_id, limit=20)
        if not series:
            self._plot_empty("Aucune séance enregistrée")
            return
        ys = [float(v) for (_t, v) in series]
        xs = list(range(1, len(ys) + 1))

        self.ax.clear()
        self.ax.plot(xs, ys)
        self.ax.set_ylim(0.0, 1.0)
        self.ax.set_xlabel("Séance")
        self.ax.set_ylabel("Score final")
        self.ax.set_title("Score moyen par séance")
        self.canvas.draw()

    def export_csv(self):
        if not self.child_id:
            messagebox.showwarning("Export", "Sélectionnez un enfant.")
            return

        # default path in ./exports
        base_dir = os.getcwd()
        exports_dir = os.path.join(base_dir, "exports")
        os.makedirs(exports_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"bilan_child_{self.child_id}_{ts}.csv"
        default_path = os.path.join(exports_dir, default_name)

        path = filedialog.asksaveasfilename(
            parent=self,
            title="Exporter le bilan (CSV)",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Tous", "*")],
            initialdir=exports_dir,
            initialfile=default_name,
        )
        if not path:
            return

        try:
            written = self.dl.export_child_sessions_csv(self.child_id, path, limit=500)
            messagebox.showinfo("Export", f"Bilan exporté :\n{written}")
        except Exception as e:
            messagebox.showerror("Export", f"Échec export CSV :\n{e}")

    def _set_empty_metrics(self):
        self.lbl_total.configure(text="Séances: —")
        self.lbl_time.configure(text="Temps total: —")
        self.lbl_avg.configure(text="Score moyen: —")
        self.lbl_level.configure(text="Niveau / XP: —")
        self.lbl_streak.configure(text="Streak: —")
        self.lst_weak.delete(0, tk.END)
        self.lst_improve.delete(0, tk.END)
        self.lbl_advice.configure(text="")

    def _plot_empty(self, title: str):
        self.ax.clear()
        self.ax.set_title(title)
        self.ax.set_xlabel("Séance")
        self.ax.set_ylabel("Score final")
        self.canvas.draw()

    def _fmt_duration(self, sec: float) -> str:
        try:
            sec = float(sec)
        except Exception:
            sec = 0.0
        m = int(sec // 60)
        s = int(sec % 60)
        if m <= 0:
            return f"{s}s"
        return f"{m}m {s}s"

    def _make_advice(self, weakest, improving, total_sessions: int) -> str:
        if total_sessions < 3:
            return "Conseil : faire encore quelques séances pour établir une tendance." 

        parts = []
        if weakest:
            p, n, a = weakest[0]
            parts.append(f"Priorité : travailler {p} (niveau actuel ~{a:.0%}).")
            parts.append("Recommandé : phrases courtes, répétition x2, 5 min/jour.")
        if improving:
            p, d, *_ = improving[0]
            parts.append(f"Point positif : {p} progresse (+{d:.0%}).")
        return "\n".join(parts)


    def export_pdf(self):
        if not self.child_id:
            messagebox.showwarning("Exporter PDF", "Veuillez d'abord sélectionner un enfant.")
            return
        try:
            child = self.dl.get_child(self.child_id)
            summary = self.dl.get_child_session_summary(self.child_id)
            recent = self.dl.get_child_recent_scores(self.child_id, limit=20)
            insights = self.dl.get_phoneme_insights(self.child_id, limit=40)
            weaknesses = insights.get("weakest") or []
            improving = insights.get("improving") or []
        except Exception as e:
            messagebox.showerror("Exporter PDF", f"Impossible de préparer le bilan.\n\n{e}")
            return

        os.makedirs("exports", exist_ok=True)
        safe_name = "enfant"
        try:
            safe_name = (child["name"] or "enfant").strip().replace(" ", "_")
        except Exception:
            pass
        default = os.path.join("exports", f"bilan_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf")
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Exporter le bilan PDF",
            initialfile=os.path.basename(default),
            initialdir=os.path.dirname(default),
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not path:
            return

        try:
            build_child_progress_pdf(
                path,
                child=child,
                summary=summary,
                recent_scores=recent,
                weaknesses=weaknesses,
                improving=improving,
            )
            messagebox.showinfo("Exporter PDF", f"Bilan PDF créé :\n{path}")
        except Exception as e:
            messagebox.showerror("Exporter PDF", f"Échec génération PDF.\n\n{e}")
