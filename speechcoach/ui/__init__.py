from tkinter import ttk

class AnalysisPanel(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        cols = ("metric","value","note")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=7)
        self.tree.heading("metric", text="Indicateur")
        self.tree.heading("value", text="Valeur")
        self.tree.heading("note", text="Interprétation")
        self.tree.column("metric", width=210, anchor="w")
        self.tree.column("value", width=160, anchor="w")
        self.tree.column("note", width=520, anchor="w")
        self.tree.pack(fill="x")

    def set_metrics(self, metrics: dict):
        for i in self.tree.get_children():
            self.tree.delete(i)

        items = [
            ("WER", metrics.get("wer"), metrics.get("wer_note")),
            ("Acoustic (cible)", metrics.get("acoustic_score"), metrics.get("acoustic_note")),
            ("Acoustic (contraste)", metrics.get("acoustic_contrast"), metrics.get("contrast_note")),
            ("Confiance phonème", metrics.get("phoneme_confidence"), metrics.get("conf_note")),
            ("Score final", metrics.get("final_score"), metrics.get("final_note")),
            ("Fenêtre focus", metrics.get("focus_window"), metrics.get("focus_note")),
        ]
        for m, v, note in items:
            if v is None:
                vv = ""
            elif isinstance(v, float):
                vv = f"{v:.3f}"
            else:
                vv = str(v)
            self.tree.insert("", "end", values=(m, vv, note or ""))
