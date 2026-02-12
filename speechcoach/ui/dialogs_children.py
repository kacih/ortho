import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional, Dict, Any

class ChildManagerDialog(tk.Toplevel):
    def __init__(self, master, dl, on_select=None):
        super().__init__(master)
        self.title("Enfants")
        self.geometry("720x420")
        self.resizable(True, True)

        self.dl = dl
        self.on_select = on_select

        self.tree = ttk.Treeview(self, columns=("id","name","age","sex","grade","created"), show="headings", height=12)
        for c, w in [("id",60),("name",160),("age",60),("sex",80),("grade",80),("created",160)]:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=8)

        ttk.Button(btns, text="Ajouter", command=self.add_child).pack(side="left")
        ttk.Button(btns, text="Modifier", command=self.edit_child).pack(side="left", padx=6)
        ttk.Button(btns, text="Supprimer", command=self.delete_child).pack(side="left")
        ttk.Button(btns, text="Sélectionner", command=self.select_child).pack(side="right")

        self.refresh()

    def refresh(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for r in self.dl.list_children():
            self.tree.insert("", "end", values=(r["id"], r["name"], r["age"], r["sex"], r["grade"], r["created_at"]))

    def _get_selected_id(self) -> Optional[int]:
        sel = self.tree.selection()
        if not sel:
            return None
        vals = self.tree.item(sel[0], "values")
        return int(vals[0])

    def _child_form(self, title: str, row=None) -> Optional[Dict[str, Any]]:
        d = tk.Toplevel(self)
        d.title(title)
        d.geometry("420x300")
        d.grab_set()

        vars_ = {
            "name": tk.StringVar(value=(row["name"] if row else "")),
            "age": tk.StringVar(value=(str(row["age"]) if row and row["age"] is not None else "")),
            "sex": tk.StringVar(value=(row["sex"] if row else "")),
            "grade": tk.StringVar(value=(row["grade"] if row else "")),
            "avatar": tk.StringVar(value=(row["avatar_path"] if row else "")),
        }

        frm = ttk.Frame(d)
        frm.pack(fill="both", expand=True, padx=12, pady=12)
        frm.columnconfigure(1, weight=1)

        def roww(label, var, r):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=6)
            ttk.Entry(frm, textvariable=var).grid(row=r, column=1, sticky="ew", pady=6)

        roww("Nom", vars_["name"], 0)
        roww("Âge", vars_["age"], 1)
        roww("Sexe", vars_["sex"], 2)
        roww("Classe", vars_["grade"], 3)

        ttk.Label(frm, text="Avatar (chemin)").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Entry(frm, textvariable=vars_["avatar"]).grid(row=4, column=1, sticky="ew", pady=6)
        ttk.Button(frm, text="Parcourir", command=lambda: vars_["avatar"].set(filedialog.askopenfilename())).grid(row=4, column=2, padx=6)

        res = {"ok": False}
        def ok():
            name = vars_["name"].get().strip()
            if not name:
                messagebox.showwarning("Champ requis", "Le nom est obligatoire.")
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

        age = vars_["age"].get().strip()
        age_i = int(age) if age.isdigit() else None
        return {
            "name": vars_["name"].get().strip(),
            "age": age_i,
            "sex": vars_["sex"].get().strip(),
            "grade": vars_["grade"].get().strip(),
            "avatar_path": vars_["avatar"].get().strip(),
        }

    def add_child(self):
        data = self._child_form("Ajouter un enfant")
        if not data:
            return
        self.dl.add_child(**data)
        self.refresh()

    def edit_child(self):
        cid = self._get_selected_id()
        if not cid:
            return
        rows = [r for r in self.dl.list_children() if int(r["id"]) == cid]
        if not rows:
            return
        data = self._child_form("Modifier un enfant", row=rows[0])
        if not data:
            return
        self.dl.update_child(cid, **data)
        self.refresh()

    def delete_child(self):
        cid = self._get_selected_id()
        if not cid:
            return
        if not messagebox.askyesno("Confirmer", "Supprimer cet enfant ?"):
            return
        self.dl.delete_child(cid)
        self.refresh()

    def select_child(self):
        cid = self._get_selected_id()
        if not cid:
            return
        if self.on_select:
            self.on_select(cid)
        self.destroy()
