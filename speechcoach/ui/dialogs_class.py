import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


class ClassOverviewDialog(tk.Toplevel):
    """Minimal teacher/class overview (Sprint 7).

    Shows per-child status (▲/■/▼) computed from recent session trend.
    """

    def __init__(self, master, data_layer):
        super().__init__(master)
        self.dl = data_layer
        self.title("Classe / Groupe")
        self.geometry("860x520")
        self.resizable(True, True)

        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(top, text="Vue classe (tendance sur les 20 dernières séances)").pack(side=tk.LEFT)

        ttk.Button(top, text="Rafraîchir", command=self.refresh).pack(side=tk.RIGHT)
        ttk.Button(top, text="Exporter CSV…", command=self.export_csv).pack(side=tk.RIGHT, padx=(0, 8))

        columns = ("status", "name", "age", "grade", "sessions", "avg", "delta")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=18)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.tree.heading("status", text="")
        self.tree.heading("name", text="Enfant")
        self.tree.heading("age", text="Âge")
        self.tree.heading("grade", text="Classe")
        self.tree.heading("sessions", text="# séances")
        self.tree.heading("avg", text="Score moyen")
        self.tree.heading("delta", text="Tendance")

        self.tree.column("status", width=40, anchor=tk.CENTER)
        self.tree.column("name", width=240, anchor=tk.W)
        self.tree.column("age", width=60, anchor=tk.CENTER)
        self.tree.column("grade", width=120, anchor=tk.CENTER)
        self.tree.column("sessions", width=90, anchor=tk.CENTER)
        self.tree.column("avg", width=110, anchor=tk.CENTER)
        self.tree.column("delta", width=110, anchor=tk.CENTER)

        note = ttk.Label(
            self,
            text="▲ amélioration (≥ +0.05)  •  ▼ baisse (≤ -0.05)  •  ■ stable",
        )
        note.pack(fill=tk.X, padx=10, pady=(0, 10))

        self.refresh()

    def refresh(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

        rows = self.dl.get_class_overview(limit_per_child=20)
        # Sort: improving first, then stable, then declining; within by name
        order = {"▲": 0, "■": 1, "▼": 2}
        rows.sort(key=lambda r: (order.get(r.get("status", "■"), 1), (r.get("name") or "").lower()))

        for r in rows:
            avg = r.get("avg_score")
            delta = r.get("delta")
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
            )

    def export_csv(self):
        try:
            rows = self.dl.get_class_overview(limit_per_child=20)
        except Exception as e:
            messagebox.showerror("Export CSV", f"Impossible de générer la vue classe.\n\n{e}")
            return

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
