
import tkinter as tk
from tkinter import ttk, messagebox
import json
from typing import Any, Dict, List, Optional

class PlaylistsDialog(tk.Toplevel):
    def __init__(self, master, dl):
        super().__init__(master)
        self.title("Playlists")
        self.geometry("980x560")
        self.resizable(True, True)

        # UX: ESC to close
        self.bind('<Escape>', lambda e: self.destroy())
        self.dl = dl

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=10, pady=10)

        left = ttk.Frame(main)
        left.pack(side="left", fill="y", padx=(0,10))

        self.btn_create = ttk.Button(left, text="Créer", command=self.create)
        self.btn_create.pack(fill="x", pady=(0,6))
        self.btn_edit = ttk.Button(left, text="Modifier", command=self.edit)
        self.btn_edit.pack(fill="x", pady=(0,6))
        self.btn_delete = ttk.Button(left, text="Supprimer", command=self.delete)
        self.btn_delete.pack(fill="x", pady=(0,12))

        ttk.Separator(left, orient="horizontal").pack(fill="x", pady=(0,12))

        self.btn_add_ex = ttk.Button(left, text="Ajouter exercice…", command=self.add_exercise)
        self.btn_add_ex.pack(fill="x", pady=(0,6))
        self.btn_remove = ttk.Button(left, text="Retirer", command=self.remove_item)
        self.btn_remove.pack(fill="x", pady=(0,6))
        self.btn_up = ttk.Button(left, text="↑", command=lambda: self.move_item(-1))
        self.btn_up.pack(fill="x", pady=(0,6))
        self.btn_down = ttk.Button(left, text="↓", command=lambda: self.move_item(1))
        self.btn_down.pack(fill="x", pady=(0,12))

        self.btn_save = ttk.Button(left, text="Enregistrer", command=self.save_current)
        self.btn_save.pack(fill="x")

        right = ttk.Frame(main)
        right.pack(side="left", fill="both", expand=True)

        top = ttk.Frame(right)
        top.pack(fill="x")
        ttk.Label(top, text="Playlist:").pack(side="left")
        self.var_name = tk.StringVar(value="")
        ttk.Entry(top, textvariable=self.var_name, width=40).pack(side="left", padx=6)
        ttk.Label(top, text="Durée (min):").pack(side="left")
        self.var_min = tk.IntVar(value=5)
        ttk.Spinbox(top, from_=1, to=30, textvariable=self.var_min, width=4).pack(side="left", padx=6)

        self.tree_plans = ttk.Treeview(right, columns=("id","name","updated"), show="headings", height=8)
        for c,w in [("id",70),("name",260),("updated",180)]:
            self.tree_plans.heading(c, text=c); self.tree_plans.column(c, width=w, anchor="w")
        self.tree_plans.pack(fill="x", pady=(10,8))
        self.tree_plans.bind("<<TreeviewSelect>>", lambda e: self.load_selected())

        frm_items = ttk.Frame(right)
        frm_items.pack(fill="both", expand=True)

        self.tree_items = ttk.Treeview(frm_items, columns=("pos","exercise_id","text"), show="headings")
        for c,w in [("pos",60),("exercise_id",90),("text",600)]:
            self.tree_items.heading(c, text=c); self.tree_items.column(c, width=w, anchor="w")
        y = ttk.Scrollbar(frm_items, orient="vertical", command=self.tree_items.yview)
        self.tree_items.configure(yscrollcommand=y.set)
        y.pack(side="right", fill="y")
        self.tree_items.pack(side="left", fill="both", expand=True)
        self.tree_items.bind("<<TreeviewSelect>>", lambda e: self._update_buttons())

        self._current_plan_id: Optional[int] = None
        self._items: List[Dict[str, Any]] = []

        self.refresh()

    
    def _update_buttons(self):
        """Enable/disable buttons based on current selection/state (standard UX)."""
        # Plan selection
        pid = self._selected_plan_id()
        has_plan = pid is not None

        # Item selection
        sel_item = self.tree_items.selection()
        has_item = bool(sel_item)

        # Playlist CRUD
        try:
            self.btn_edit.config(state=("normal" if has_plan else "disabled"))
            self.btn_delete.config(state=("normal" if has_plan else "disabled"))
        except Exception:
            pass

        # Items actions
        try:
            self.btn_remove.config(state=("normal" if has_item else "disabled"))
            self.btn_up.config(state=("normal" if has_item else "disabled"))
            self.btn_down.config(state=("normal" if has_item else "disabled"))
        except Exception:
            pass

        # Save enabled if name not empty
        try:
            nm = (self.var_name.get() or "").strip()
            self.btn_save.config(state=("normal" if nm else "disabled"))
        except Exception:
            pass

    def refresh(self):
            for i in self.tree_plans.get_children():
                self.tree_plans.delete(i)
            rows = []
            try:
                rows = self.dl.list_session_plans()
            except Exception:
                rows = []
            for r in rows:
                try:
                    d = json.loads(r["plan_json"] or "{}")
                    if (d.get("mode") or "") != "playlist":
                        continue
                except Exception:
                    continue
                self.tree_plans.insert("", "end", values=(r["id"], r["name"], r["updated_at"]))
            self._update_buttons()

    def _selected_plan_id(self) -> Optional[int]:
        sel = self.tree_plans.selection()
        if not sel:
            return None
        return int(self.tree_plans.item(sel[0], "values")[0])

    def load_selected(self):
        pid = self._selected_plan_id()
        if not pid:
            return
        rows = self.dl.list_session_plans()
        row = None
        for r in rows:
            if int(r["id"]) == pid:
                row = r
                break
        if not row:
            return
        try:
            d = json.loads(row["plan_json"] or "{}")
        except Exception:
            d = {}
        self._current_plan_id = pid
        self.var_name.set(str(row["name"] or "").strip())
        try:
            self.var_min.set(int(d.get("duration_min") or 5))
        except Exception:
            self.var_min.set(5)
        items = d.get("items") or []
        if items and isinstance(items, list) and all(isinstance(x, str) for x in items):
            items = [{"text": x} for x in items]
        self._items = list(items)
        self._refresh_items()
        self._update_buttons()

    def _refresh_items(self):
        for i in self.tree_items.get_children():
            self.tree_items.delete(i)
        for idx,it in enumerate(self._items, start=1):
            ex_id = it.get("exercise_id") if isinstance(it, dict) else ""
            txt = it.get("text") if isinstance(it, dict) else str(it)
            self.tree_items.insert("", "end", values=(idx, ex_id or "", (txt or "")[:400]))

    def create(self):
        self._current_plan_id = None
        self.var_name.set("Nouvelle playlist")
        self.var_min.set(5)
        self._items = []
        self._refresh_items()
        self._update_buttons()

    def edit(self):
        self.load_selected()

    def delete(self):
        pid = self._selected_plan_id()
        if not pid:
            return
        if not messagebox.askyesno("Confirmer", "Supprimer cette playlist ?"):
            return
        self.dl.delete_session_plan(int(pid))
        self.create()
        self.refresh()

    def _pick_exercise(self) -> Optional[Dict[str, Any]]:
        d = tk.Toplevel(self)
        d.title("Choisir un exercice")
        d.geometry("820x460")
        d.grab_set()

        frame = ttk.Frame(d); frame.pack(fill="both", expand=True, padx=10, pady=10)
        tree = ttk.Treeview(frame, columns=("id","title","objective","level","type","text"), show="headings")
        for c,w in [("id",60),("title",180),("objective",120),("level",60),("type",80),("text",320)]:
            tree.heading(c, text=c); tree.column(c, width=w, anchor="w")
        y = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=y.set)
        y.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        d.bind("<Escape>", lambda e: d.destroy())

        rows = self.dl.list_exercises()
        for r in rows:
            tree.insert("", "end", values=(r["id"], r["title"], r["objective"], r["level"], r["type"], r["text"]))

        res = {"row": None}
        def ok():
            sel = tree.selection()
            if not sel:
                d.destroy()
                return
            vals = tree.item(sel[0], "values")
            res["row"] = {"exercise_id": int(vals[0]), "text": str(vals[5])}
            d.destroy()

        # UX: double-click selects exercise
        tree.bind("<Double-1>", lambda e: ok())

        b = ttk.Frame(d); b.pack(fill="x", padx=10, pady=10)
        ttk.Button(b, text="Annuler", command=d.destroy).pack(side="right")
        ttk.Button(b, text="OK", command=ok).pack(side="right", padx=6)

        d.wait_window()
        return res["row"]

    def add_exercise(self):
        ex = self._pick_exercise()
        if not ex:
            return
        self._items.append({"exercise_id": ex["exercise_id"], "text": ex["text"]})
        self._refresh_items()
        self._update_buttons()

    def remove_item(self):
        sel = self.tree_items.selection()
        if not sel:
            return
        pos = int(self.tree_items.item(sel[0], "values")[0]) - 1
        if 0 <= pos < len(self._items):
            self._items.pop(pos)
        self._refresh_items()
        self._update_buttons()

    def move_item(self, delta: int):
        sel = self.tree_items.selection()
        if not sel:
            return
        idx = int(self.tree_items.item(sel[0], "values")[0]) - 1
        j = idx + int(delta)
        if j < 0 or j >= len(self._items):
            return
        self._items[idx], self._items[j] = self._items[j], self._items[idx]
        self._refresh_items()
        self._update_buttons()
        # reselect moved row
        try:
            self.tree_items.selection_set(self.tree_items.get_children()[j])
        except Exception:
            pass

    def save_current(self):
        name = self.var_name.get().strip()
        if not name:
            messagebox.showwarning("Nom", "Le nom est obligatoire.")
            return
        if not self._items:
            messagebox.showwarning("Items", "Ajoute au moins un exercice.")
            return
        plan = {
            "plan_id": "playlist",
            "name": name,
            "mode": "playlist",
            "duration_min": int(self.var_min.get() or 5),
            "rounds": int(len(self._items)),
            "repeat_on_fail": True,
            "max_repeats_per_sentence": 1,
            "items": self._items,
        }
        try:
            if self._current_plan_id is None:
                pid = self.dl.save_session_plan(name, plan)
                self._current_plan_id = int(pid)
            else:
                self.dl.update_session_plan(int(self._current_plan_id), name, plan)
        except Exception as e:
            messagebox.showerror("Erreur", str(e))
            return
        self.refresh()
        messagebox.showinfo("Playlist", "Enregistré.")