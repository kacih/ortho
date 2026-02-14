
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import csv, json
from typing import Optional

class HistoryDialog(tk.Toplevel):
    def __init__(self, master, dl, child_id: int):
        super().__init__(master)
        self.title("Historique")
        self.geometry("980x560")
        self.resizable(True, True)

        # UX: ESC to close
        self.bind('<Escape>', lambda e: self.destroy())
        self.dl = dl
        self.child_id = int(child_id)

        top = ttk.Frame(self); top.pack(fill="x", padx=10, pady=8)
        ttk.Label(top, text=f"Enfant ID: {self.child_id}").pack(side="left")
        ttk.Button(top, text="Exporter CSV…", command=self.export_csv).pack(side="right")

        main = ttk.Frame(self); main.pack(fill="both", expand=True, padx=10, pady=10)

        left = ttk.Frame(main); left.pack(side="left", fill="y", padx=(0,10))
        right = ttk.Frame(main); right.pack(side="left", fill="both", expand=True)

        self.tree_runs = ttk.Treeview(left, columns=("id","date","done","planned","early"), show="headings", height=22)
        for c,w in [("id",70),("date",160),("done",70),("planned",70),("early",60)]:
            self.tree_runs.heading(c, text=c); self.tree_runs.column(c, width=w, anchor="w")
        self.tree_runs.pack(fill="y", expand=True)
        self.tree_runs.bind("<<TreeviewSelect>>", lambda e: self.load_detail())

        frm = ttk.Frame(right); frm.pack(fill="both", expand=True)
        self.tree_items = ttk.Treeview(frm, columns=("id","date","expected","recognized","score","wer"), show="headings")
        for c,w in [("id",70),("date",150),("expected",260),("recognized",260),("score",80),("wer",80)]:
            self.tree_items.heading(c, text=c); self.tree_items.column(c, width=w, anchor="w")
        y = ttk.Scrollbar(frm, orient="vertical", command=self.tree_items.yview)
        self.tree_items.configure(yscrollcommand=y.set)
        y.pack(side="right", fill="y")
        self.tree_items.pack(side="left", fill="both", expand=True)

        self.refresh()

    def refresh(self):
        for i in self.tree_runs.get_children():
            self.tree_runs.delete(i)
        runs = self.dl.list_session_runs_for_child(self.child_id, limit=200)
        for r in runs:
            early = "oui" if int(r["ended_early"] or 0) else ""
            self.tree_runs.insert("", "end", values=(r["id"], r["created_at"], r["completed_items"], r["planned_items"], early))

    def _selected_run_id(self) -> Optional[int]:
        sel = self.tree_runs.selection()
        if not sel:
            return None
        return int(self.tree_runs.item(sel[0], "values")[0])

    def load_detail(self):
        run_id = self._selected_run_id()
        if not run_id:
            return
        for i in self.tree_items.get_children():
            self.tree_items.delete(i)
        rows = self.dl.list_sessions_for_run(run_id)
        for r in rows:
            self.tree_items.insert("", "end", values=(r["id"], r["created_at"], r["expected_text"], r["recognized_text"], r["final_score"], r["wer"]))

    def export_csv(self):
        run_id = self._selected_run_id()
        if not run_id:
            messagebox.showwarning("Export", "Sélectionne une séance (run) à exporter.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")], title="Exporter CSV")
        if not path:
            return
        rows = self.dl.list_sessions_for_run(run_id)
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["session_id","created_at","expected_text","recognized_text","final_score","wer","audio_path"])
            for r in rows:
                w.writerow([r["id"], r["created_at"], r["expected_text"], r["recognized_text"], r["final_score"], r["wer"], r["audio_path"]])
        messagebox.showinfo("Export", "CSV exporté.")
