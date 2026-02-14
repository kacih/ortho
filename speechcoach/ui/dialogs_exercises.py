
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional, Dict, Any

class ExercisesDialog(tk.Toplevel):
    def __init__(self, master, dl):
        super().__init__(master)
        self.title("Bibliothèque d'exercices")
        self.geometry("900x520")
        self.resizable(True, True)

        # UX: ESC to close
        self.bind('<Escape>', lambda e: self.destroy())
        self.dl = dl

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        ttk.Label(top, text="Recherche:").pack(side="left")
        self.var_q = tk.StringVar(value="")
        ttk.Entry(top, textvariable=self.var_q, width=30).pack(side="left", padx=6)

        ttk.Label(top, text="Objectif:").pack(side="left")
        self.var_obj = tk.StringVar(value="")
        ttk.Entry(top, textvariable=self.var_obj, width=18).pack(side="left", padx=6)

        ttk.Label(top, text="Niveau:").pack(side="left")
        self.var_lvl = tk.StringVar(value="")
        ttk.Entry(top, textvariable=self.var_lvl, width=4).pack(side="left", padx=6)

        ttk.Label(top, text="Type:").pack(side="left")
        self.var_type = tk.StringVar(value="")
        ttk.Combobox(top, textvariable=self.var_type, values=["","mot","phrase","liste"], width=10, state="readonly").pack(side="left", padx=6)

        ttk.Button(top, text="Rechercher", command=self.refresh).pack(side="left", padx=6)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0,8))
        ttk.Button(btns, text="Ajouter", command=self.add).pack(side="left")
        ttk.Button(btns, text="Modifier", command=self.edit).pack(side="left", padx=6)
        ttk.Button(btns, text="Supprimer", command=self.delete).pack(side="left")
        ttk.Separator(btns, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(btns, text="Dupliquer", command=self.duplicate).pack(side="left")
        ttk.Separator(btns, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(btns, text="Importer CSV…", command=self.import_csv).pack(side="left")

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=8)

        self.tree = ttk.Treeview(frame, columns=("id","title","objective","level","type","text"), show="headings")
        for c,w in [("id",60),("title",180),("objective",120),("level",60),("type",80),("text",360)]:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w")
        y = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y.set)
        y.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.refresh()

    def _selected_id(self) -> Optional[int]:
        sel = self.tree.selection()
        if not sel:
            return None
        return int(self.tree.item(sel[0], "values")[0])

    def refresh(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        q = self.var_q.get().strip()
        obj = self.var_obj.get().strip()
        typ = self.var_type.get().strip()
        lvl = self.var_lvl.get().strip()
        level = int(lvl) if lvl.isdigit() else None
        rows = self.dl.list_exercises(q=q, objective=obj, level=level, typ=typ)
        for r in rows:
            self.tree.insert("", "end", values=(r["id"], r["title"], r["objective"], r["level"], r["type"], r["text"]))

    def _form(self, title: str, row: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        d = tk.Toplevel(self)
        d.title(title)
        d.geometry("560x420")
        d.resizable(True, False)
        d.grab_set()
        d.bind("<Escape>", lambda e: d.destroy())

        # Lazy-load Edge voices (best effort)
        try:
            from speechcoach import tts as ttsmod
            edge_voices = ttsmod.list_edge_voices("fr-")
        except Exception:
            edge_voices = []

        voice_values = [""] + (edge_voices or [])

        def _get(k, default=""):
            if not row:
                return default
            try:
                v = row.get(k)  # type: ignore[attr-defined]
            except Exception:
                v = row[k] if k in row else default
            return default if v is None else v

        try:
            rate0 = float(_get("rate", 1.0) or 1.0)
        except Exception:
            rate0 = 1.0
        rate0 = max(0.7, min(1.3, float(rate0)))

        vars_ = {
            "title": tk.StringVar(value=str(_get("title", ""))),
            "text": tk.StringVar(value=str(_get("text", ""))),
            "type": tk.StringVar(value=str(_get("type", "phrase") or "phrase")),
            "objective": tk.StringVar(value=str(_get("objective", ""))),
            "level": tk.StringVar(value=str(_get("level", "")) if _get("level", "") is not None else ""),
            "voice": tk.StringVar(value=str(_get("voice", ""))),
            "pause_ms": tk.StringVar(value=str(_get("pause_ms", "")) if _get("pause_ms", "") is not None else ""),
        }
        var_rate = tk.DoubleVar(value=rate0)

        frm = ttk.Frame(d)
        frm.pack(fill="both", expand=True, padx=12, pady=12)
        frm.columnconfigure(1, weight=1)

        def row_entry(label, var, r):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=6)
            ttk.Entry(frm, textvariable=var).grid(row=r, column=1, sticky="ew", pady=6)

        row_entry("Titre", vars_["title"], 0)
        row_entry("Texte", vars_["text"], 1)

        ttk.Label(frm, text="Type").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Combobox(frm, textvariable=vars_["type"], values=["mot", "phrase", "liste"], state="readonly").grid(row=2, column=1, sticky="ew", pady=6)

        row_entry("Objectif", vars_["objective"], 3)

        ttk.Label(frm, text="Niveau (1–5)").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Entry(frm, textvariable=vars_["level"]).grid(row=4, column=1, sticky="ew", pady=6)

        ttk.Label(frm, text="Voix Edge (option)").grid(row=5, column=0, sticky="w", pady=6)
        cb_voice = ttk.Combobox(frm, textvariable=vars_["voice"], values=voice_values, state="readonly")
        cb_voice.grid(row=5, column=1, sticky="ew", pady=6)

        ttk.Label(frm, text="Vitesse (0.7 → 1.3)").grid(row=6, column=0, sticky="w", pady=6)
        scale = ttk.Scale(frm, from_=0.7, to=1.3, variable=var_rate)
        scale.grid(row=6, column=1, sticky="ew", pady=6)

        lab_rate = ttk.Label(frm, text=f"{var_rate.get():.2f}")
        lab_rate.grid(row=6, column=2, sticky="w", padx=8)

        def _on_rate(*_):
            try:
                lab_rate.config(text=f"{var_rate.get():.2f}")
            except Exception:
                pass
        var_rate.trace_add("write", _on_rate)

        ttk.Label(frm, text="Pause ms (option)").grid(row=7, column=0, sticky="w", pady=6)
        ttk.Entry(frm, textvariable=vars_["pause_ms"]).grid(row=7, column=1, sticky="ew", pady=6)

        # Test button (best effort)
        test_frame = ttk.Frame(frm)
        test_frame.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        test_frame.columnconfigure(1, weight=1)

        ttk.Label(test_frame, text="Test:").grid(row=0, column=0, sticky="w")
        var_test = tk.StringVar(value="Bonjour. Ceci est un test de voix.")
        ttk.Entry(test_frame, textvariable=var_test).grid(row=0, column=1, sticky="ew", padx=6)

        def do_test():
            try:
                from speechcoach.tts import TTSEngine
                eng = TTSEngine()
                eng.backend = "edge"
                v = (vars_["voice"].get() or "").strip()
                if v:
                    eng.edge_voice = v
                try:
                    eng.apply_settings({"tts_backend": "edge", "edge_voice": eng.edge_voice, "tts_rate": float(var_rate.get())})
                except Exception:
                    pass
                eng.speak(var_test.get().strip() or "Bonjour.")
            except Exception as e:
                messagebox.showwarning("Test voix", f"Impossible de jouer le test : {e}")

        ttk.Button(test_frame, text="Tester", command=do_test).grid(row=0, column=2, sticky="e")

        res = {"ok": False}

        def ok():
            text = vars_["text"].get().strip()
            if not text:
                messagebox.showwarning("Champ requis", "Le texte est obligatoire.")
                return

            lvl = vars_["level"].get().strip()
            if lvl:
                if not lvl.isdigit():
                    messagebox.showwarning("Niveau invalide", "Le niveau doit être un entier entre 1 et 5.")
                    return
                iv = int(lvl)
                if iv < 1 or iv > 5:
                    messagebox.showwarning("Niveau invalide", "Le niveau doit être entre 1 et 5.")
                    return

            pm = vars_["pause_ms"].get().strip()
            if pm and not pm.isdigit():
                messagebox.showwarning("Pause invalide", "La pause doit être un entier (millisecondes).")
                return

            res["ok"] = True
            d.destroy()

        b = ttk.Frame(d)
        b.pack(fill="x", padx=12, pady=10)
        ttk.Button(b, text="Annuler", command=d.destroy).pack(side="right")
        ttk.Button(b, text="OK", command=ok).pack(side="right", padx=6)

        d.wait_window()
        if not res["ok"]:
            return None

        out = {k: v.get().strip() for k, v in vars_.items()}
        out["rate"] = f"{float(var_rate.get()):.2f}"
        return out

    def add(self):
        data = self._form("Ajouter un exercice")
        if not data:
            return
        self.dl.create_exercise(data)
        self.refresh()

    def edit(self):
        ex_id = self._selected_id()
        if not ex_id:
            return
        rows = self.dl.list_exercises()
        row = None
        for r in rows:
            if int(r["id"]) == ex_id:
                row = dict(r)
                break
        if not row:
            return
        data = self._form("Modifier un exercice", row=row)
        if not data:
            return
        self.dl.update_exercise(ex_id, data)
        self.refresh()

    def duplicate(self):
        ex_id = self._selected_id()
        if not ex_id:
            return
        rows = self.dl.list_exercises()
        for r in rows:
            if int(r["id"]) == ex_id:
                d = dict(r)
                d["title"] = (d.get("title") or "") + " (copie)"
                self.dl.create_exercise(d)
                break
        self.refresh()

    def delete(self):
        ex_id = self._selected_id()
        if not ex_id:
            return
        if not messagebox.askyesno("Confirmer", "Supprimer cet exercice ?"):
            return
        self.dl.delete_exercise(ex_id)
        self.refresh()

    def import_csv(self):
        path = filedialog.askopenfilename(title="Importer CSV", filetypes=[("CSV", "*.csv"), ("Tous", "*.*")])
        if not path:
            return
        res = self.dl.import_exercises_csv(path)
        msg = f"Import terminé. OK: {res.get('ok', 0)}"
        errs = res.get("errors") or []
        if errs:
            msg += f"\nErreurs: {len(errs)}\n" + "\n".join(errs[:10])
        messagebox.showinfo("Import CSV", msg)
        self.refresh()
