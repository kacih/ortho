import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional, Dict, Any
import os
import base64
from datetime import datetime

class ChildManagerDialog(tk.Toplevel):
    def __init__(self, master, dl, on_select=None):
        super().__init__(master)
        self.title("Enfants")
        self.geometry("720x420")
        self.resizable(True, True)

        self.dl = dl
        self.on_select = on_select

        # UX: make rows taller so the avatar is clearly visible.
        # Using a dedicated style avoids impacting other Treeviews.
        style = ttk.Style(self)
        style.configure("Children.Treeview", rowheight=56)

        # NOTE UX: on utilise la colonne #0 pour afficher un avatar (icône).
        # show="tree headings" permet de garder les colonnes en headings.
        self.tree = ttk.Treeview(
            self,
            columns=("id","name","age","sex","grade","created"),
            show="tree headings",
            height=6,
            style="Children.Treeview",
        )
        self.tree.heading("#0", text="Avatar")
        self.tree.column("#0", width=60, anchor="center", stretch=False)
        for c, w in [("id",60),("name",160),("age",60),("sex",80),("grade",80),("created",160)]:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w")
        # Tree + scrollbar (buttons must stay visible without resizing)
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        yscroll = ttk.Scrollbar(tree_frame, orient="vertical")
        yscroll.pack(side="right", fill="y")

        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.configure(command=self.tree.yview)

        self.tree.pack(side="left", fill="both", expand=True)

        # Keep PhotoImage references
        self._avatars = {}

        # UX: double-clic = sélectionner l'enfant et fermer
        self.tree.bind("<Double-1>", lambda e: self.select_child())

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
            # sqlite3.Row behaves like a mapping but has no .get()
            avatar_path = ""
            avatar_blob = None
            created_at = None
            try:
                if "avatar_path" in r.keys():
                    avatar_path = r["avatar_path"] or ""
                if "avatar_blob" in r.keys():
                    avatar_blob = r["avatar_blob"]
                if "created_at" in r.keys():
                    created_at = r["created_at"]
            except Exception:
                # best effort (older DB schemas)
                avatar_path = ""
                avatar_blob = None
                created_at = None

            # Robust avatar loading:
            # 1) Prefer binary stored in DB (stable)
            # 2) Fallback to avatar_path (best effort)
            img = self._load_avatar_image_blob(avatar_blob) or self._default_avatar_image()
            created_h = self._fmt_created_at_fr(created_at)
            # IMPORTANT (Python 3.14 / Tk): pass -values as a *single* Tcl list string.
            # If a Python tuple/list is passed through, it may be expanded into multiple
            # Tcl words and break insert() with "unknown option" errors.
            def _s(v):
                return "" if v is None else str(v)
            tcl_values = self.tree.tk.call(
                "list",
                _s(r["id"]),
                _s(r["name"]),
                _s(r["age"]),
                _s(r["sex"]),
                _s(r["grade"]),
                _s(created_h),
            )
            iid = self.tree.insert(
                "",
                "end",
                iid=f"child_{r['id']}",
                text="",
                image=img,
                values=tcl_values,
            )
            if img is not None:
                self._avatars[iid] = img

    def _fmt_created_at_fr(self, s: Optional[str]) -> str:
        """Format date as dd/MM/YYYY HH:MM:SS (best effort)."""
        if not s:
            return ""
        s = str(s).strip()
        try:
            # Accept ISO "2026-02-11T18:38:08" and "2026-02-12 16:39:02"
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.strftime("%d/%m/%Y %H:%M:%S")
        except Exception:
            return s

    def _load_avatar_image(self, path: str):
        """Load a small avatar icon (supports formats accepted by Tk PhotoImage).
        If loading fails, return None.
        """
        path = (path or "").strip()
        if not path or not os.path.exists(path):
            return None
        try:
            img = tk.PhotoImage(file=path)
            # Resize to ~32px keeping it lightweight (subsample only supports integer)
            w = max(1, img.width())
            h = max(1, img.height())
            factor = max(1, int(max(w, h) / 32))
            if factor > 1:
                img = img.subsample(factor, factor)
            return img
        except Exception:
            return None

    def _load_avatar_image_blob(self, blob: Any):
        """Load avatar from DB BLOB (expected PNG/GIF bytes). Best effort.
        Tk PhotoImage 'data' expects base64.
        """
        if not blob:
            return None
        try:
            if isinstance(blob, memoryview):
                blob = blob.tobytes()
            if not isinstance(blob, (bytes, bytearray)):
                return None
            b64 = base64.b64encode(blob).decode("ascii")
            img = tk.PhotoImage(data=b64)
            w = max(1, img.width())
            h = max(1, img.height())
            factor = max(1, int(max(w, h) / 32))
            if factor > 1:
                img = img.subsample(factor, factor)
            return img
        except Exception:
            return None

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
            "avatar": tk.StringVar(value=""),
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
            "avatar_file": vars_["avatar"].get().strip(),
        }

    
    def _read_avatar_bytes(self, path: str):
        p = (path or "").strip()
        if not p:
            return None
        try:
            if os.path.exists(p):
                with open(p, "rb") as f:
                    return f.read()
        except Exception:
            return None
        return None

    def add_child(self):
        data = self._child_form("Ajouter un enfant")
        if not data:
            return
        avatar_bytes = self._read_avatar_bytes(data.pop("avatar_file", ""))
        self.dl.add_child(
            name=data.get("name",""),
            age=data.get("age"),
            sex=data.get("sex",""),
            grade=data.get("grade",""),
            avatar_bytes=avatar_bytes,
        )
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
        avatar_bytes = self._read_avatar_bytes(data.pop("avatar_file", ""))
        self.dl.update_child(
            cid,
            name=data.get("name",""),
            age=data.get("age"),
            sex=data.get("sex",""),
            grade=data.get("grade",""),
            avatar_bytes=avatar_bytes,
        )
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
