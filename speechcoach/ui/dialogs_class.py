import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .dialogs_progress import ProgressDialog
from speechcoach.reports_pdf import build_group_progress_pdf


class ClassOverviewDialog(tk.Toplevel):
    """Teacher/class overview (Sprint 7+).

    Sprint 8:
    - Grade filter + name search
    - "Top à aider" list
    - Open child progress from selection
    """

    def __init__(self, master, data_layer):
        super().__init__(master)
        self.dl = data_layer
        self.title("Classe / Groupe")
        self.geometry("980x560")
        self.resizable(True, True)

        self._rows = []
        self._grade_values = ["Toutes"]
        self._selected_child_id = None

        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(top, text="Vue classe (tendance sur les 20 dernières séances)").pack(side=tk.LEFT)

        ttk.Button(top, text="Rafraîchir", command=self.refresh).pack(side=tk.RIGHT)
        ttk.Button(top, text="Exporter CSV…", command=self.export_csv).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(top, text="Exporter PDF…", command=self.export_pdf).pack(side=tk.RIGHT, padx=(0, 8))

        # Filters row
        filters = ttk.Frame(self)
        filters.pack(fill=tk.X, padx=10, pady=(0, 8))

        ttk.Label(filters, text="Classe :").pack(side=tk.LEFT)
        self.grade_var = tk.StringVar(value="Toutes")
        self.grade_combo = ttk.Combobox(filters, textvariable=self.grade_var, values=self._grade_values, state="readonly", width=18)
        self.grade_combo.pack(side=tk.LEFT, padx=(6, 16))
        self.grade_combo.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        ttk.Label(filters, text="Recherche :").pack(side=tk.LEFT)
        self.search_var = tk.StringVar(value="")
        self.search_entry = ttk.Entry(filters, textvariable=self.search_var, width=26)
        self.search_entry.pack(side=tk.LEFT, padx=(6, 8))
        self.search_entry.bind("<KeyRelease>", lambda e: self.apply_filters())

        ttk.Button(filters, text="Ouvrir progrès…", command=self.open_progress_for_selected).pack(side=tk.RIGHT)

        main = ttk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        columns = ("status", "name", "age", "grade", "sessions", "avg", "delta")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", height=18)
        self.tree.pack(fill=tk.BOTH, expand=True)

        self.tree.heading("status", text="")
        self.tree.heading("name", text="Enfant")
        self.tree.heading("age", text="Âge")
        self.tree.heading("grade", text="Classe")
        self.tree.heading("sessions", text="# séances")
        self.tree.heading("avg", text="Score moyen")
        self.tree.heading("delta", text="Tendance")

        self.tree.column("status", width=40, anchor=tk.CENTER)
        self.tree.column("name", width=260, anchor=tk.W)
        self.tree.column("age", width=60, anchor=tk.CENTER)
        self.tree.column("grade", width=120, anchor=tk.CENTER)
        self.tree.column("sessions", width=90, anchor=tk.CENTER)
        self.tree.column("avg", width=110, anchor=tk.CENTER)
        self.tree.column("delta", width=110, anchor=tk.CENTER)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self.open_progress_for_selected())

        right = ttk.Frame(main)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))

        ttk.Label(right, text="Top à aider").pack(anchor="w")
        self.help_list = tk.Listbox(right, height=14, width=28)
        self.help_list.pack(fill=tk.Y, expand=False, pady=(6, 8))
        self.help_list.bind("<Double-1>", lambda e: self._open_progress_from_help())

        ttk.Button(right, text="Ouvrir progrès…", command=self._open_progress_from_help).pack(fill=tk.X)

        note = ttk.Label(
            self,
            text="▲ amélioration (≥ +0.05)  •  ▼ baisse (≤ -0.05)  •  ■ stable",
        )
        note.pack(fill=tk.X, padx=10, pady=(0, 10))

        self.refresh()

    def _on_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            self._selected_child_id = None
            return
        item = sel[0]
        try:
            child_id = self.tree.item(item, "tags")[0]
            self._selected_child_id = int(child_id)
        except Exception:
            self._selected_child_id = None

    def refresh(self):
        try:
            self._rows = self.dl.get_class_overview(limit_per_child=20)
        except Exception as e:
            messagebox.showerror("Classe / Groupe", f"Impossible de charger la vue classe.\n\n{e}")
            self._rows = []

        # Update grades list
        grades = sorted({(r.get("grade") or "").strip() for r in self._rows if (r.get("grade") or "").strip()}, key=lambda s: s.lower())
        self._grade_values = ["Toutes"] + grades
        self.grade_combo.configure(values=self._grade_values)
        if self.grade_var.get() not in self._grade_values:
            self.grade_var.set("Toutes")

        self.apply_filters()

    def apply_filters(self):
        # Tree
        for i in self.tree.get_children():
            self.tree.delete(i)

        grade = (self.grade_var.get() or "Toutes").strip()
        q = (self.search_var.get() or "").strip().lower()

        rows = list(self._rows)
        if grade and grade != "Toutes":
            rows = [r for r in rows if (r.get("grade") or "").strip() == grade]
        if q:
            rows = [r for r in rows if q in (r.get("name") or "").lower()]

        # Sort: improving first, then stable, then declining; within by name
        order = {"▲": 0, "■": 1, "▼": 2}
        rows.sort(key=lambda r: (order.get(r.get("status", "■"), 1), (r.get("name") or "").lower()))
        self._filtered_rows = list(rows)

        for r in rows:
            avg = r.get("avg_score")
            delta = r.get("delta")
            child_id = r.get("child_id")
            self.tree.insert(
                "",
                tk.END,
                values=(
                    r.get("status", "■"),
                    r.get("name", ""),
                    r.get("age", ""),
                    r.get("grade", ""),
                    r.get("sessions", 0),
                    (f"{avg:.2f}" if isinstance(avg, (int, float)) else ""),
                    (f"{delta:+.2f}" if isinstance(delta, (int, float)) else ""),
                ),
                tags=(str(child_id),) if child_id is not None else tuple(),
            )

        # Help list
        self._refresh_help_list(rows)

    def _refresh_help_list(self, rows):
        self.help_list.delete(0, tk.END)
        candidates = []
        for r in rows:
            sessions = int(r.get("sessions") or 0)
            if sessions < 3:
                continue
            avg = r.get("avg_score")
            delta = r.get("delta")
            status = r.get("status", "■")
            # Needs-help rule (simple and conservative)
            needs = (status == "▼") or (isinstance(avg, (int, float)) and avg < 0.50)
            if not needs:
                continue
            severity = 0.0
            if isinstance(avg, (int, float)):
                severity += max(0.0, 0.60 - avg)  # lower avg -> higher severity
            if isinstance(delta, (int, float)) and delta < 0:
                severity += min(0.30, abs(delta))
            if status == "▼":
                severity += 0.20
            candidates.append((severity, r))

        candidates.sort(key=lambda t: (-t[0], (t[1].get("name") or "").lower()))
        for sev, r in candidates[:8]:
            avg = r.get("avg_score")
            status = r.get("status", "■")
            label = f"{status} {r.get('name','')}  ({avg:.2f})" if isinstance(avg, (int, float)) else f"{status} {r.get('name','')}"
            # store child_id in listbox via a simple mapping attribute
            self.help_list.insert(tk.END, label)
        self._help_rows = [r for _, r in candidates[:8]]

    def open_progress_for_selected(self):
        if not self._selected_child_id:
            messagebox.showinfo("Progrès", "Sélectionnez d'abord un enfant dans la liste.")
            return
        ProgressDialog(self, self.dl, int(self._selected_child_id))

    def _open_progress_from_help(self):
        sel = self.help_list.curselection()
        if not sel:
            return
        idx = int(sel[0])
        try:
            r = self._help_rows[idx]
            cid = int(r.get("child_id"))
        except Exception:
            return
        ProgressDialog(self, self.dl, cid)

    def export_csv(self):
        # export filtered view
        grade = (self.grade_var.get() or "Toutes").strip()
        q = (self.search_var.get() or "").strip().lower()

        rows = list(self._rows)
        self._filtered_rows = rows
        if grade and grade != "Toutes":
            rows = [r for r in rows if (r.get("grade") or "").strip() == grade]
        if q:
            rows = [r for r in rows if q in (r.get("name") or "").lower()]

        initial_dir = os.path.join(os.getcwd(), "exports")
        os.makedirs(initial_dir, exist_ok=True)
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Exporter la vue classe",
            initialdir=initial_dir,
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return

        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["status", "name", "age", "grade", "sessions", "avg_score", "delta"])
            for r in rows:
                w.writerow([
                    r.get("status", "■"),
                    r.get("name", ""),
                    r.get("age", ""),
                    r.get("grade", ""),
                    r.get("sessions", 0),
                    (f"{r.get('avg_score'):.3f}" if isinstance(r.get("avg_score"), (int, float)) else ""),
                    (f"{r.get('delta'):+.3f}" if isinstance(r.get("delta"), (int, float)) else ""),
                ])

        messagebox.showinfo("Export CSV", f"Export effectué :\n{path}")


    def export_pdf(self):
        # Export filtered class view as a multi-page PDF (one page per child)
        rows = getattr(self, "_filtered_rows", None) or []
        if not rows:
            messagebox.showwarning("Exporter PDF", "Aucun enfant à exporter (vérifiez les filtres).")
            return

        os.makedirs("exports", exist_ok=True)
        default = os.path.join("exports", f"bilan_groupe_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M')}.pdf")
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Exporter le bilan PDF (groupe)",
            initialfile=os.path.basename(default),
            initialdir=os.path.dirname(default),
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not path:
            return

        def fetcher(child_id: int):
            child = self.dl.get_child(child_id)
            summary = self.dl.get_child_session_summary(child_id)
            recent = self.dl.get_child_recent_scores(child_id, limit=20)
            insights = self.dl.get_phoneme_insights(child_id, limit=40)
            weaknesses = insights.get("weakest") or []
            improving = insights.get("improving") or []
            return child, summary, recent, weaknesses, improving

        try:
            build_group_progress_pdf(path, children=rows, fetcher=fetcher)
            messagebox.showinfo("Exporter PDF", f"Bilan PDF créé :\n{path}")
        except Exception as e:
            messagebox.showerror("Exporter PDF", f"Échec génération PDF.\n\n{e}")
