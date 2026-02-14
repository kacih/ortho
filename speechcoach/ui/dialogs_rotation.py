
import tkinter as tk
from tkinter import ttk, messagebox
import json
from typing import Optional, List, Dict, Any

class RotationDialog(tk.Toplevel):
    def __init__(self, master, dl, app):
        super().__init__(master)
        self.title("Rotation classe (kiosque)")
        self.geometry("720x420")
        self.resizable(True, True)

        # UX: ESC to close
        self.bind('<Escape>', lambda e: self.destroy())
        self.dl = dl
        self.app = app

        top = ttk.Frame(self); top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="Groupe / Classe:").pack(side="left")
        self.var_grade = tk.StringVar(value="")
        self.cmb_grade = ttk.Combobox(top, textvariable=self.var_grade, state="readonly", width=18, values=[])
        self.cmb_grade.pack(side="left", padx=6)
        self.cmb_grade.bind("<<ComboboxSelected>>", lambda e: (self._load_children(), self._update_buttons()))

        ttk.Label(top, text="Playlist:").pack(side="left")
        self.var_plan = tk.StringVar(value="")
        self.cmb_plan = ttk.Combobox(top, textvariable=self.var_plan, state="readonly", width=28, values=[])
        self.cmb_plan.pack(side="left", padx=6)

        self.var_autostart = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Auto démarrer", variable=self.var_autostart).pack(side="left", padx=6)

        main = ttk.Frame(self); main.pack(fill="both", expand=True, padx=10, pady=10)

        self.lst = tk.Listbox(main, height=12)
        self.lst.pack(side="left", fill="both", expand=True)

        right = ttk.Frame(main); right.pack(side="left", fill="y", padx=(10,0))
        self.btn_start = ttk.Button(right, text="▶️ Démarrer rotation", command=self.start)
        self.btn_start.pack(fill="x", pady=(0,6))
        self.btn_next = ttk.Button(right, text="⏭️ Suivant", command=self.next_child)
        self.btn_next.pack(fill="x", pady=(0,6))
        self.btn_pause = ttk.Button(right, text="⏸️ Pause", command=self.pause)
        self.btn_pause.pack(fill="x", pady=(0,6))
        self.btn_resume = ttk.Button(right, text="▶️ Reprendre", command=self.resume)
        self.btn_resume.pack(fill="x", pady=(0,6))
        self.btn_stop = ttk.Button(right, text="⏹️ Stop", command=self.stop)
        self.btn_stop.pack(fill="x", pady=(0,12))

        ttk.Label(right, text="Timer (sec):").pack(anchor="w")
        self.var_timer = tk.IntVar(value=180)
        ttk.Spinbox(right, from_=30, to=600, increment=30, textvariable=self.var_timer, width=6).pack(anchor="w", pady=(0,6))
        self.lbl = ttk.Label(right, text="Prêt.")
        self.lbl.pack(anchor="w", pady=(10,0))

        self._children: List[Dict[str, Any]] = []
        self._index = -1
        self._running = False
        self._paused = False
        self._remaining = 0
        self._after_id = None

        self._load_grades()
        self._load_plans()
        self._update_buttons()

    
    def _update_buttons(self):
        """Enable/disable buttons based on current state (standard UX)."""
        running = bool(self._running)
        paused = bool(self._paused)
        has_children = bool(self._children)

        # Start only when not running and children list non-empty
        try:
            self.btn_start.config(state=("normal" if (not running and has_children) else "disabled"))
        except Exception:
            pass

        # Next only when running and not paused
        try:
            self.btn_next.config(state=("normal" if (running and not paused) else "disabled"))
        except Exception:
            pass

        # Stop only when running
        try:
            self.btn_stop.config(state=("normal" if running else "disabled"))
        except Exception:
            pass

        # Pause only when running and not paused
        try:
            self.btn_pause.config(state=("normal" if (running and not paused) else "disabled"))
        except Exception:
            pass

        # Resume only when running and paused
        try:
            self.btn_resume.config(state=("normal" if (running and paused) else "disabled"))
        except Exception:
            pass

    def resume(self):
        """Resume after pause."""
        if not self._running or not self._paused:
            return
        self._paused = False
        self.lbl.config(text=f"Timer: {self._remaining}s")
        self._update_buttons()
        self._tick()

    def _load_grades(self):
            grades = self.dl.list_grades()
            self.cmb_grade["values"] = [""] + grades

    def _load_plans(self):
        # only playlist plans
        vals = []
        self._plan_map = {}  # label -> (plan_id, key_for_app)
        try:
            rows = self.dl.list_session_plans()
        except Exception:
            rows = []
        for r in rows:
            try:
                d = json.loads(r["plan_json"] or "{}")
                # Accept playlist plans; if mode missing, still show (legacy)
            except Exception:
                continue
            pid = int(r["id"])
            name = str(r["name"] or "").strip() or f"Playlist {pid}"
            label = f"{pid} - {name}"
            # app key format used in refresh_plans
            key = f"user:{pid}:{name}"
            vals.append(label)
            self._plan_map[label] = (pid, key)
        self.cmb_plan["values"] = vals
        if vals:
            self.var_plan.set(vals[0])

    def _load_children(self):
        grade = self.var_grade.get().strip()
        self.lst.delete(0, "end")
        self._children = []
        if not grade:
            return
        rows = self.dl.list_children_by_grade(grade)
        for r in rows:
            self._children.append({"id": int(r["id"]), "name": str(r["name"] or "")})
        for c in self._children:
            self.lst.insert("end", f"{c['id']} - {c['name']}")
        self._update_buttons()

    def _apply_selected_plan_to_app(self):
        label = self.var_plan.get().strip()
        if not label or label not in self._plan_map:
            return
        plan_id, key = self._plan_map[label]
        try:
            self.app.refresh_plans()
            self.app.var_plan_id.set(key)
            self.app.on_plan_change()
        except Exception:
            pass

    def start(self):
        if not self._children:
            messagebox.showwarning("Rotation", "Sélectionne un groupe avec des enfants.")
            return
        self._apply_selected_plan_to_app()
        self._running = True
        self._paused = False
        self._index = -1
        self.next_child()
        self._update_buttons()

    def next_child(self):
        if not self._running:
            return
        self._index += 1
        if self._index >= len(self._children):
            self.stop()
            self.lbl.config(text="Rotation terminée.")
            return
        c = self._children[self._index]
        # select in listbox
        try:
            self.lst.selection_clear(0, "end")
            self.lst.selection_set(self._index)
            self.lst.see(self._index)
        except Exception:
            pass
        try:
            self.app.set_child(int(c["id"]))
        except Exception:
            pass
        self._remaining = int(self.var_timer.get() or 180)
        self.lbl.config(text=f"En cours: {c['name']} ({self._remaining}s)")
        if self.var_autostart.get():
            try:
                self.app.start_game()
            except Exception:
                pass
        self._tick()

    def _tick(self):
        if not self._running or self._paused:
            return
        self._remaining -= 1
        if self._remaining <= 0:
            self.next_child()
            return
        self.lbl.config(text=f"Timer: {self._remaining}s")
        self._after_id = self.after(1000, self._tick)

    
    def pause(self):
        """Pause current rotation timer (no toggle)."""
        if not self._running:
            return
        if self._paused:
            return
        self._paused = True
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self.lbl.config(text="Pause.")
        self._update_buttons()

    def stop(self):
        """Stop rotation and reset state."""
        self._running = False
        self._paused = False
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self._update_buttons()
