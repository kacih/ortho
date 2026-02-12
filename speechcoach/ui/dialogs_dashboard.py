import os
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, List

class DashboardDialog(tk.Toplevel):
    def __init__(self, master, dl, audio, child_id: Optional[int]):
        super().__init__(master)
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

        cols = ("id","created","child","story","expected","recognized","wer","final","phoneme","audio")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=20, selectmode="extended")
        widths = {"id":60,"created":150,"child":70,"story":170,"expected":230,"recognized":230,"wer":60,"final":60,"phoneme":70,"audio":220}
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=widths.get(c, 120), anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=8)
        ttk.Button(bottom, text="Rejouer audio", command=self.replay_selected).pack(side="left")
        ttk.Button(bottom, text="Fermer", command=self.destroy).pack(side="right")

        self.refresh()

    def refresh(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

        rows = self.dl.fetch_sessions_filtered(child_id=self.child_id, limit=800)
        for r in rows:
            wer_v = float(r["wer"] if r["wer"] is not None else 1.0)
            final = float(r["final_score"] if r["final_score"] is not None else 0.0)

            if final >= 0.85: ind = "🟢"
            elif final >= 0.70: ind = "🟡"
            elif final >= 0.55: ind = "🟠"
            else: ind = "🔴"

            self.tree.insert("", "end", values=(
                r["id"], r["created_at"], r["child_id"],
                f"{ind} {r['story_title'] or ''}",
                (r["expected_text"] or "")[:120],
                (r["recognized_text"] or "")[:120],
                f"{wer_v:.2f}",
                f"{final:.2f}",
                r["phoneme_target"] or "",
                r["audio_path"] or "",
            ))

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

    def replay_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        audio_path = vals[9] if vals else ""
        if audio_path and os.path.exists(audio_path):
            self.audio.play_wav(audio_path)
        else:
            messagebox.showwarning("Audio", "Fichier audio introuvable.")
