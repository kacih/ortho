import tkinter as tk
from speechcoach.game import GameState
from tkinter import ttk, messagebox, simpledialog
import threading
import json

from speechcoach.deps import check_dependencies, format_dependency_report

from speechcoach.config import (
    APP_NAME, APP_VERSION,
    DATA_DIR, AUDIO_DIR,
    DEFAULT_DB_PATH, DEFAULT_STORIES_PATH, FALLBACK_STORIES_PATH,
    RESOURCES_DIR,
)
from speechcoach.utils_paths import ensure_dir, pick_existing
from speechcoach.db import DataLayer
from speechcoach.settings import SettingsManager
from speechcoach.stories import StoryEngine
from speechcoach.audio import AudioEngine
from speechcoach.asr import ASREngine
from speechcoach.game import GameController
from speechcoach.session_manager import build_session_plan, get_preset_plan, preset_plans
from speechcoach.rewards import load_catalog, choose_new_card_for_child

from .dialogs_children import ChildManagerDialog
from .dialogs_dashboard import DashboardDialog
from .dialogs_progress import ProgressDialog
from .dialogs_class import ClassOverviewDialog
from .dialogs_audio import AudioSettingsDialog as AudioDevicesDialog
from .panels_analysis import AnalysisPanel
from speechcoach.ui.audio_settings import AudioSettingsDialog as TTSAudioSettingsDialog


class SpeechCoachApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # Dependency diagnostics (do not crash if optional deps are missing)
        try:
            _deps = check_dependencies()
            print(format_dependency_report(_deps))
        except Exception:
            pass

        self.title(f"{APP_NAME} — {APP_VERSION}")
        self.geometry("1060x740")

        ensure_dir(DATA_DIR)
        ensure_dir(AUDIO_DIR)

        db_path = DEFAULT_DB_PATH
        stories_path = pick_existing(DEFAULT_STORIES_PATH, FALLBACK_STORIES_PATH)

        self.dl = DataLayer(db_path)
        self.settings_mgr = SettingsManager(db_path)
        self._plan_key_to_plan = {}

        self.stories = StoryEngine(stories_path)
        n = self.stories.load()

        # Rewards catalog (cards)
        try:
            from pathlib import Path
            cat_path = Path(RESOURCES_DIR) / "cards" / "catalog.json"
            self.cards_catalog = load_catalog(str(cat_path)) if cat_path.exists() else []
        except Exception:
            self.cards_catalog = []


        self.audio = AudioEngine()
        self.asr = ASREngine()

        def ui_dispatch(fn):
            self.after(0, fn)

        self.game = GameController(self.stories, self.audio, self.asr, self.dl, ui_dispatch)

        self.current_child_id = None

        self._build_menu()
        self._build_ui()

        # bind callbacks
        self.game.on_status = self.set_status
        self.game.on_sentence = self.on_sentence
        self.game.on_analysis = self.on_analysis
        self.game.on_end = self.on_end

        self.set_status(f"Prêt. Stories={n} | JSON={stories_path} | DB={db_path}")

        # UX audio: préchauffage silencieux du moteur TTS pour réduire
        # les premières syllabes "mangées" sur certains périphériques.
        try:
            threading.Thread(target=self.audio.tts.warmup, daemon=True).start()
        except Exception:
            pass

        self.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def on_close(self):
        """Fermeture propre de l'application (audio/session/DB) puis destruction Tk."""
        # Stopper une session si elle existe
        try:
            if hasattr(self, "session_manager") and self.session_manager:
                self.session_manager.stop()
        except Exception:
            pass

        # Stopper audio/tts si vous avez des objets dédiés
        try:
            if hasattr(self, "audio") and self.audio:
                self.audio.stop_all()  # ou .stop() selon votre implémentation
        except Exception:
            pass

        # Fermer la DB si besoin
        try:
            if hasattr(self, "dl") and self.dl:
                self.dl.close()  # si DataLayer expose close(); sinon laisser
        except Exception:
            pass

        self.destroy()


    def open_audio_devices(self):
        """Open audio device selection (micro + output)."""
        AudioDevicesDialog(self, self.audio)

    def open_tts_settings(self):
        """Open TTS voice/rate/volume settings dialog."""
        TTSAudioSettingsDialog(self, self.audio)

    def _build_menu(self):
        menubar = tk.Menu(self)
        # Keep references to menus so we can enable/disable them (kiosk mode).
        self._menubar = menubar

        m_child = tk.Menu(menubar, tearoff=0)
        m_child.add_command(label="Gérer les enfants…", command=self.open_children)
        menubar.add_cascade(label="Enfants", menu=m_child)
        self._menu_children = m_child

        m_audio = tk.Menu(menubar, tearoff=0)
        m_audio.add_command(label="Audio (micro/sortie)…", command=self.open_audio_devices)
        m_audio.add_command(label="Voix TTS…", command=self.open_tts_settings)
        m_audio.add_separator()
        menubar.add_cascade(label="Audio", menu=m_audio)
        self._menu_audio = m_audio

        m_dash = tk.Menu(menubar, tearoff=0)
        m_dash.add_command(label="Dashboard Pro…", command=self.open_dashboard)
        m_dash.add_command(label="Progrès enfant…", command=self.open_progress)
        m_dash.add_command(label="Classe / Groupe…", command=self.open_class_overview)
        menubar.add_cascade(label="TDB", menu=m_dash)
        self._menu_dash = m_dash

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="À propos", command=lambda: messagebox.showinfo("À propos", f"{APP_NAME}\n{APP_VERSION}"))
        menubar.add_cascade(label="Aide", menu=m_help)
        self._menu_help = m_help
        self.config(menu=menubar)

    def _build_ui(self):
        # Load persisted settings early (kiosk/last plan, etc.).
        try:
            self._app_settings = self.settings_mgr.load()
        except Exception:
            self._app_settings = {}

        root = ttk.Frame(self)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x", padx=12, pady=(12, 6))
        self.lbl_paths = ttk.Label(
            header,
            text=f"Stories: {len(self.stories.stories)} | JSON: {self.stories.path} | DB: {self.dl.db_path}",
            foreground="#333"
        )
        self.lbl_paths.pack(anchor="w")

        top = ttk.Frame(root)
        top.pack(fill="x", padx=12, pady=10)

        ttk.Label(top, text="Enfant:").pack(side="left")
        self.lbl_child = ttk.Label(top, text="(non sélectionné)")
        self.lbl_child.pack(side="left", padx=8)
        self.btn_select_child = ttk.Button(top, text="Sélectionner…", command=self.open_children)
        self.btn_select_child.pack(side="left", padx=6)

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)

        self.var_child_mode = tk.BooleanVar(value=False)
        self.chk_child_mode = ttk.Checkbutton(
            top,
            text="Mode enfant (auto)",
            variable=self.var_child_mode,
            command=self.on_toggle_mode
        )
        self.chk_child_mode.pack(side="left", padx=6)

        # Sprint 3: mode enseignant (enchaînement rapide)
        self.var_teacher_mode = tk.BooleanVar(value=False)
        self.chk_teacher_mode = ttk.Checkbutton(
            top,
            text="Mode enseignant",
            variable=self.var_teacher_mode,
            command=self.on_toggle_teacher_mode
        )
        self.chk_teacher_mode.pack(side="left", padx=6)

        # Sprint 5: mode kiosque (verrouillage UI pour l'école)
        self.var_kiosk_mode = tk.BooleanVar(value=bool(self._app_settings.get("kiosk_mode", 0)))
        self.chk_kiosk_mode = ttk.Checkbutton(
            top,
            text="Mode kiosque",
            variable=self.var_kiosk_mode,
            command=self.on_toggle_kiosk_mode,
        )
        self.chk_kiosk_mode.pack(side="left", padx=6)

        self.teacher_frame = ttk.Frame(top)
        # (packed only when enabled)
        ttk.Label(self.teacher_frame, text="Enchaîner:").pack(side="left")
        self.var_teacher_child = tk.StringVar(value="")
        self.cmb_teacher_child = ttk.Combobox(
            self.teacher_frame,
            textvariable=self.var_teacher_child,
            state="readonly",
            width=24,
            values=[]
        )
        self.cmb_teacher_child.pack(side="left", padx=6)
        self.cmb_teacher_child.bind("<<ComboboxSelected>>", lambda e: self.on_teacher_child_selected())
        self.var_teacher_autostart = tk.BooleanVar(value=False)
        self.chk_teacher_autostart = ttk.Checkbutton(
            self.teacher_frame,
            text="Auto démarrer",
            variable=self.var_teacher_autostart
        )
        self.chk_teacher_autostart.pack(side="left", padx=6)
        self.btn_teacher_next = ttk.Button(self.teacher_frame, text="⏭️ Suivant", command=self.teacher_next_child)
        self.btn_teacher_next.pack(side="left", padx=4)
        self._teacher_children = []
        self._teacher_child_keys = []
        self._teacher_index = -1

        # Sprint 1/2: plan presets + user presets (adult mode)
        ttk.Label(top, text="Plan:").pack(side="left")
        self.var_plan_id = tk.StringVar(value="standard")
        self.cmb_plan = ttk.Combobox(
            top,
            textvariable=self.var_plan_id,
            state="readonly",
            width=20,
            values=[]
        )
        self.cmb_plan.pack(side="left", padx=6)
        self.cmb_plan.bind("<<ComboboxSelected>>", lambda e: self.on_plan_change())

        self.btn_save_plan = ttk.Button(top, text="💾 Enregistrer", command=self.save_current_plan_preset)
        self.btn_save_plan.pack(side="left", padx=4)
        self.btn_resume_plan = ttk.Button(top, text="↩️ Reprendre", command=self.resume_last_plan)
        self.btn_resume_plan.pack(side="left", padx=4)

        self.refresh_plans()

        ttk.Label(top, text="Durée (min):").pack(side="left")
        self.var_minutes = tk.IntVar(value=3)
        self.spin_minutes = ttk.Spinbox(top, from_=1, to=20, textvariable=self.var_minutes, width=4, command=self.on_duration_change)
        self.spin_minutes.pack(side="left", padx=6)

        ttk.Label(top, text="Tours (auto):").pack(side="left")
        self.var_rounds = tk.IntVar(value=3)
        self.spin_rounds = ttk.Spinbox(top, from_=1, to=20, textvariable=self.var_rounds, width=4, state="readonly")
        self.spin_rounds.pack(side="left", padx=6)
        

        self.btn_start = ttk.Button(top, text="▶️ Démarrer", command=self.start_game)
        self.btn_start.pack(side="left", padx=6)

        self.btn_pause = ttk.Button(top, text="⏸️ Pause", command=self.toggle_pause, state="disabled")
        self.btn_pause.pack(side="left", padx=6)

        self.btn_replay = ttk.Button(top, text="🔁 Rejouer phrase", command=self.replay_phrase, state="disabled")
        self.btn_replay.pack(side="left", padx=6)

        self.btn_stop = ttk.Button(top, text="⏹️ Stop", command=self.stop_game, state="disabled")
        self.btn_stop.pack(side="left", padx=6)

        # Apply persisted kiosk mode after building widgets.
        try:
            self.apply_kiosk_mode()
        except Exception:
            pass

        mid = ttk.Frame(root)
        mid.pack(fill="x", padx=12, pady=8)

        self.lbl_story = ttk.Label(mid, text="Story: —", font=("Segoe UI", 11, "bold"))
        self.lbl_story.pack(anchor="w")

        self.lbl_sentence = ttk.Label(mid, text="Phrase: —", wraplength=1000, font=("Segoe UI", 12))
        self.lbl_sentence.pack(anchor="w", pady=6)

        self.lbl_target = ttk.Label(mid, text="Phonème cible: —")
        self.lbl_target.pack(anchor="w")

        ttk.Label(root, text="Analyse (lisible):", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        self.analysis_panel = AnalysisPanel(root)
        self.analysis_panel.pack(fill="x", padx=12)

        frm_rec = ttk.Frame(root)
        frm_rec.pack(fill="x", padx=12, pady=10)
        ttk.Label(frm_rec, text="Texte reconnu:").pack(anchor="w")
        self.txt_rec = tk.Text(frm_rec, height=3, wrap="word")
        self.txt_rec.pack(fill="x")

        self.var_status = tk.StringVar(value="Prêt.")
        status = ttk.Label(root, textvariable=self.var_status, relief="sunken", anchor="w")
        status.pack(fill="x", side="bottom")

    # ---- Actions
    def open_children(self):
        ChildManagerDialog(self, self.dl, on_select=self.set_child)

    def set_child(self, child_id: int):
        self.current_child_id = child_id
        self.game.set_child(child_id)
        rows = [r for r in self.dl.list_children() if int(r["id"]) == child_id]
        if rows:
            r = rows[0]
            self.lbl_child.config(text=f"{r['name']} (id={child_id})")
        else:
            self.lbl_child.config(text=f"id={child_id}")
        # keep teacher combobox in sync
        try:
            if getattr(self, 'var_teacher_mode', None) is not None and self.var_teacher_mode.get():
                self.refresh_teacher_children()
        except Exception:
            pass
    def open_dashboard(self):
        DashboardDialog(
            self,
            self.dl,
            self.audio,
            self.current_child_id,
            on_pick=self.show_evolution_graph
        )

    def open_progress(self):
        """Open the progress/bilan dashboard (Sprint 6)."""
        ProgressDialog(
            self,
            self.dl,
            self.current_child_id,
        )

    def open_class_overview(self):
        """Open class/group overview (Sprint 7)."""
        ClassOverviewDialog(self, self.dl)

    def show_evolution_graph(self, session_id, child_id, phoneme):
        print("GRAPH:", session_id, child_id, phoneme)


    
    def on_plan_change(self):
        """Apply plan values to duration/rounds (Sprint 1/2)."""
        try:
            # Do not interfere with child mode
            if getattr(self, "var_child_mode", None) is not None and self.var_child_mode.get():
                return

            key = (self.var_plan_id.get() or "libre").strip()
            plan = None
            try:
                plan = self._plan_key_to_plan.get(key)
            except Exception:
                plan = None

            if plan is None:
                # Libre: keep current rounds/duration
                return

            try:
                self.var_minutes.set(int(getattr(plan, "duration_min", self.var_minutes.get())))
            except Exception:
                pass
            try:
                self.var_rounds.set(int(getattr(plan, "rounds", self.var_rounds.get())))
            except Exception:
                pass
        except Exception:
            pass


    
    def refresh_plans(self):
        """Populate combobox with builtin presets + user presets from DB (Sprint 2)."""
        try:
            self._plan_key_to_plan = {}
            values = []

            # Builtins
            values.append("libre")
            self._plan_key_to_plan["libre"] = None
            for p in preset_plans():
                key = p.plan_id
                values.append(key)
                self._plan_key_to_plan[key] = p

            # User presets
            try:
                rows = self.dl.list_session_plans()
            except Exception:
                rows = []
            for r in rows:
                try:
                    pid = int(r["id"])
                    name = str(r["name"] or "").strip() or f"Plan {pid}"
                    key = f"user:{pid}:{name}"
                    d = json.loads(r["plan_json"]) if r["plan_json"] else {}
                    plan = plan_from_json_dict(d)
                    values.append(key)
                    self._plan_key_to_plan[key] = plan
                except Exception:
                    continue

            self.cmb_plan["values"] = values

            # Restore last plan if available
            try:
                s = self.settings_mgr.load()
                last_json = (s.get("last_plan_json") or "").strip()
                last_name = (s.get("last_plan_name") or "").strip()
                last_mode = (s.get("last_plan_mode") or "").strip()
                if last_json:
                    try:
                        d = json.loads(last_json)
                        plan = plan_from_json_dict(d)
                        key = f"last:{last_mode}:{last_name}".strip(":")
                        # put at top after libre
                        if key not in values:
                            values.insert(1, key)
                            self.cmb_plan["values"] = values
                            self._plan_key_to_plan[key] = plan
                        self.var_plan_id.set(key)
                        self.on_plan_change()
                        return
                    except Exception:
                        pass
            except Exception:
                pass

            # default selection
            if not self.var_plan_id.get():
                self.var_plan_id.set("standard")
            self.on_plan_change()
        except Exception:
            pass

    def _current_selected_plan(self):
        key = (self.var_plan_id.get() or "libre").strip()
        try:
            return self._plan_key_to_plan.get(key)
        except Exception:
            return None

    def save_current_plan_preset(self):
        """Save currently selected plan as a user preset (Sprint 2)."""
        try:
            if getattr(self, "var_child_mode", None) is not None and self.var_child_mode.get():
                messagebox.showinfo("Plan", "Le mode enfant n'enregistre pas de plan.")
                return

            plan = self._current_selected_plan()
            if plan is None:
                # create a minimal plan from current UI values
                from speechcoach.session_manager import SessionPlan
                plan = SessionPlan(plan_id="custom", name="Custom", mode="libre",
                                   duration_min=int(self.var_minutes.get()),
                                   rounds=int(self.var_rounds.get()))

            name = simpledialog.askstring("Enregistrer un plan", "Nom du plan :", parent=self)
            if not name:
                return

            pid = self.dl.save_session_plan(name=name, plan=plan.to_json_dict())
            messagebox.showinfo("Plan", f"Plan enregistré (id={pid}).")
            self.refresh_plans()
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def resume_last_plan(self):
        """Start a session with the last used plan (Sprint 2)."""
        try:
            s = self.settings_mgr.load()
            last_json = (s.get("last_plan_json") or "").strip()
            if not last_json:
                messagebox.showinfo("Reprendre", "Aucun plan précédent n'a été enregistré.")
                return
            d = json.loads(last_json)
            plan = plan_from_json_dict(d)
            # reflect in UI
            self.var_minutes.set(int(getattr(plan, "duration_min", self.var_minutes.get())))
            self.var_rounds.set(int(getattr(plan, "rounds", self.var_rounds.get())))
            self.set_status(f"↩️ Reprise : {getattr(plan, 'name', 'Plan')} ({plan.rounds} tours)")
            # start
            return self._start_with_rounds(int(plan.rounds), plan=plan)
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def on_duration_change(self):
        """Recompute auto rounds when duration changes."""
        # In adult preset mode, rounds are driven by the preset, not by minutes.
        try:
            if getattr(self, "var_child_mode", None) is not None and not self.var_child_mode.get():
                pid = (getattr(self, "var_plan_id", None) and self.var_plan_id.get()) or "libre"
                if str(pid).strip().lower() in ("decouverte","standard","intensif"):
                    return
        except Exception:
            pass
        try:
            if not self.current_child_id:
                return
            child = self.dl.get_child(int(self.current_child_id))
            plan = build_session_plan(child, duration_min=int(self.var_minutes.get() or 3))
            self.var_rounds.set(int(plan.rounds))
        except Exception:
            pass


    def on_toggle_mode(self):
        # In child mode, we hide advanced controls; duration remains user-configurable.
        try:
            is_child = bool(self.var_child_mode.get())
        except Exception:
            is_child = False

        # pause/replay disabled in child mode (UX)
        if is_child:
            self.btn_pause.config(state="disabled")
            self.btn_replay.config(state="disabled")
            self.btn_start.config(text="🎮 Jouer")
        else:
            self.btn_start.config(text="▶️ Démarrer")
        # Always recompute rounds when duration or child changes
        self.on_duration_change()



    # ---- Sprint 3: mode enseignant
    def on_toggle_teacher_mode(self):
        enabled = bool(self.var_teacher_mode.get()) if getattr(self, 'var_teacher_mode', None) is not None else False
        if enabled:
            # Show teacher quick-switch controls
            self.teacher_frame.pack(side='left', padx=10)
            self.refresh_teacher_children()
            # In teacher mode, avoid accidental child auto-mode
            try:
                self.var_child_mode.set(False)
                self.on_toggle_mode()
            except Exception:
                pass
        else:
            try:
                self.teacher_frame.pack_forget()
            except Exception:
                pass

    # ---- Sprint 5: mode kiosque (verrouillage UI)
    def on_toggle_kiosk_mode(self):
        """Enable/disable kiosk mode and persist it."""
        enabled = bool(self.var_kiosk_mode.get()) if getattr(self, 'var_kiosk_mode', None) is not None else False
        # Persist
        try:
            s = self.settings_mgr.load()
            s["kiosk_mode"] = 1 if enabled else 0
            self.settings_mgr.save(s)
        except Exception:
            pass
        self.apply_kiosk_mode()

    def apply_kiosk_mode(self):
        enabled = bool(self.var_kiosk_mode.get()) if getattr(self, 'var_kiosk_mode', None) is not None else False

        # Disable menus that allow configuration changes.
        try:
            if hasattr(self, "_menubar") and self._menubar is not None:
                for label in ("Enfants", "Audio", "TDB"):
                    try:
                        self._menubar.entryconfig(label, state=("disabled" if enabled else "normal"))
                    except Exception:
                        pass
        except Exception:
            pass

        # Disable buttons that open configuration dialogs.
        try:
            if hasattr(self, "btn_select_child") and self.btn_select_child is not None:
                self.btn_select_child.config(state=("disabled" if enabled else "normal"))
        except Exception:
            pass

        try:
            # In kiosk mode, we generally don't want presets to be modified on the fly.
            if hasattr(self, "btn_save_plan") and self.btn_save_plan is not None:
                self.btn_save_plan.config(state=("disabled" if enabled else "normal"))
        except Exception:
            pass

        # Guide the user toward a safe operational state.
        if enabled:
            try:
                # Prefer teacher mode for quick chaining; keep child auto-mode off.
                self.var_child_mode.set(False)
                if hasattr(self, "var_teacher_mode"):
                    self.var_teacher_mode.set(True)
                    self.on_toggle_teacher_mode()
                self.on_toggle_mode()
            except Exception:
                pass
            try:
                self.set_status("🔒 Mode kiosque activé : menus de configuration verrouillés")
            except Exception:
                pass
        else:
            try:
                self.set_status("Mode kiosque désactivé")
            except Exception:
                pass

    def refresh_teacher_children(self):
        try:
            rows = self.dl.list_children()
        except Exception:
            rows = []
        # Build display keys 'Name (id=..)'
        keys = []
        children = []
        for r in rows:
            try:
                cid = int(r['id'])
            except Exception:
                continue
            try:
                name = r['name']
            except Exception:
                name = ''
            key = f"{name} (id={cid})"
            keys.append(key)
            children.append({'id': cid, 'name': name, 'key': key})
        # sort by name, then id
        children.sort(key=lambda x: (x['name'].lower(), x['id']))
        self._teacher_children = children
        self._teacher_child_keys = [c['key'] for c in children]
        self.cmb_teacher_child['values'] = self._teacher_child_keys

        # Update selection index
        self._teacher_index = -1
        if self.current_child_id is not None:
            for i,c in enumerate(children):
                if c['id'] == self.current_child_id:
                    self._teacher_index = i
                    self.var_teacher_child.set(c['key'])
                    break
        if self._teacher_index == -1 and children:
            self._teacher_index = 0
            self.var_teacher_child.set(children[0]['key'])

    def on_teacher_child_selected(self):
        key = self.var_teacher_child.get()
        for i,c in enumerate(getattr(self, '_teacher_children', []) or []):
            if c['key'] == key:
                self._teacher_index = i
                self.set_child(c['id'])
                break

    def teacher_next_child(self):
        children = getattr(self, '_teacher_children', []) or []
        if not children:
            self.refresh_teacher_children()
            children = getattr(self, '_teacher_children', []) or []
        if not children:
            messagebox.showinfo('Mode enseignant', 'Aucun enfant enregistré.')
            return
        self._teacher_index = (self._teacher_index + 1) % len(children)
        c = children[self._teacher_index]
        self.var_teacher_child.set(c['key'])
        self.set_child(c['id'])
        if bool(getattr(self, 'var_teacher_autostart', tk.BooleanVar(value=False)).get()):
            # Auto-start only if not already running
            try:
                if getattr(self.game, 'state', None) in (None, GameState.IDLE, GameState.DONE):
                    self.start_game()
            except Exception:
                pass
    def start_session_auto(self, duration_min: int = 10):
        """Start a short, guided session adapted to the selected child."""
        if not self.current_child_id:
            messagebox.showwarning("Enfant", "Sélectionne d'abord un enfant.")
            return
        if len(self.stories.stories) == 0:
            messagebox.showerror("Stories", f"Aucune story chargée.\nChemin: {self.stories.path}")
            return

        child = None
        try:
            child = self.dl.get_child(int(self.current_child_id))
        except Exception:
            child = None

        # Convert sqlite3.Row to dict-like for safety
        child_dict = dict(child) if child is not None else None
        plan = build_session_plan(child_dict, duration_min=duration_min)

        # Reflect the plan in UI (read-only)
        try:
            self.var_rounds.set(int(plan.rounds))
        except Exception:
            pass

        self.set_status(f"🎮 Session auto : {plan.rounds} tours (~{plan.duration_min} min)")
        return self._start_with_rounds(plan.rounds, plan=plan)

    def _start_with_rounds(self, rounds: int, plan=None):
        """Internal helper to start the game safely with the given number of rounds."""
        try:
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
            # In child mode we keep pause/replay disabled
            if getattr(self, "var_child_mode", None) is not None and self.var_child_mode.get():
                self.btn_pause.config(state="disabled")
                self.btn_replay.config(state="disabled")
            else:
                self.btn_pause.config(state="normal")
                self.btn_replay.config(state="normal")
            self.game.start(rounds=int(rounds), plan=plan)
        except Exception as e:
            messagebox.showerror("Erreur", str(e))
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.btn_pause.config(state="disabled")
            self.btn_replay.config(state="disabled")


    def start_game(self):
        if not self.current_child_id:
            messagebox.showwarning("Enfant", "Sélectionne d'abord un enfant.")
            return
        if len(self.stories.stories) == 0:
            messagebox.showerror("Stories", f"Aucune story chargée.\nChemin: {self.stories.path}")
            return

        # Auto session for children: simplified UX
        if getattr(self, 'var_child_mode', None) is not None and self.var_child_mode.get():
            return self.start_session_auto(duration_min=3)

        try:
            key = (getattr(self, "var_plan_id", None) and self.var_plan_id.get()) or "libre"
            key = str(key).strip()
            plan = None
            try:
                plan = self._plan_key_to_plan.get(key)
            except Exception:
                plan = None

            # Persist last plan for "Reprendre"
            try:
                s = self.settings_mgr.load()
                if plan is not None:
                    s["last_plan_json"] = json.dumps(plan.to_json_dict(), ensure_ascii=False)
                    s["last_plan_name"] = getattr(plan, "name", "") or ""
                    s["last_plan_mode"] = getattr(plan, "mode", "") or ""
                self.settings_mgr.save(s)
            except Exception:
                pass

            self._start_with_rounds(int(self.var_rounds.get()), plan=plan)
        except Exception as e:
            self.on_end()
            messagebox.showerror("Erreur", str(e))


    def stop_game(self):
        self.game.stop()
        self.on_end()
        self.set_status("⏹️ Arrêté.")

    def toggle_pause(self):
        self.game.toggle_pause()
        self.btn_pause.config(
            text="▶️ Reprendre" if self.game.state == GameState.PAUSED else "⏸️ Pause"
        )

    def replay_phrase(self):
        self.game.replay_last()

    # ---- Callbacks
    def set_status(self, text: str):
        self.var_status.set(text)

    def on_sentence(self, story_title: str, k: int, total: int, expected: str, phoneme: str):
        self.lbl_story.config(text=f"Story: {story_title} — Tour {k}/{total}")
        self.lbl_sentence.config(text=f"Phrase: {expected}")
        self.lbl_target.config(text=f"Phonème cible: {phoneme}")
        # UX: conserver les derniers indicateurs + texte reconnu affichés
        # jusqu'à la fin de l'analyse du son suivant.
        # Donc: ne pas vider ici.

    def on_analysis(self, metrics: dict):
        self.analysis_panel.set_metrics(metrics)
        rec = metrics.get("recognized_text", "") or ""
        self.txt_rec.delete("1.0", "end")
        self.txt_rec.insert("end", rec)

    def on_end(self):
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_pause.config(state="disabled")
        self.btn_replay.config(state="disabled")
        self.btn_pause.config(text="⏸️ Pause")

        # Reward: card collection (child mode only, completed session only)
        try:
            if (
                getattr(self, 'var_child_mode', None) is not None
                and self.var_child_mode.get()
                and getattr(self.game, 'last_end_reason', '') == 'finished'
                and self.current_child_id
            ):
                # Update progress (adaptive XP/level/streak)
                prog = self.dl.upsert_progress_after_session(int(self.current_child_id), float(getattr(self.game, "last_final_score", 0.0) or 0.0))
                level = int(prog["level"] or 1) if prog else 1

                owned_ids = self.dl.list_owned_card_ids(int(self.current_child_id))
                card = choose_new_card_for_child(
                    catalog=getattr(self, "cards_catalog", []) or [],
                    owned_card_ids=owned_ids,
                    child_level=level,
                )

                if card is not None and self.dl.add_child_card_v2(int(self.current_child_id), card):
                    self._show_card_reward(card, prog)
                else:
                    # Collection complete for eligible cards (or insert ignored)
                    self._show_simple_reward(prog)
        except Exception:
            # Never fail end-of-session UX due to rewards.
            pass

    
    def _show_card_reward(self, card, prog=None):
        """Popup with card image + rarity + progress."""
        try:
            import tkinter as tk
            from tkinter import ttk
            from pathlib import Path

            win = tk.Toplevel(self)
            win.title("Récompense")
            win.geometry("360x420")
            win.resizable(False, False)
            win.transient(self)
            win.grab_set()

            frm = ttk.Frame(win, padding=12)
            frm.pack(fill="both", expand=True)

            title = f"🎉 Nouvelle carte !"
            ttk.Label(frm, text=title, font=("Segoe UI", 14, "bold")).pack(pady=(0,10))

            # Image
            import base64

            photo = None
            try:
                b = getattr(card, "icon_bytes", None)
                if b:
                    b64 = base64.b64encode(b).decode("ascii")
                    photo = tk.PhotoImage(data=b64)
            except Exception:
                photo = None

            img_path = Path(RESOURCES_DIR) / "cards" / str(getattr(card, "icon_path", "") or "")
            if photo is None and img_path.exists():
                try:
                    photo = tk.PhotoImage(file=str(img_path))
                    # reduce to ~140px
                    if photo.width() > 160:
                        photo = photo.subsample(max(1, photo.width() // 160))
                except Exception:
                    photo = None

            if photo is not None:
                lbl_img = ttk.Label(frm, image=photo)
                lbl_img.image = photo
                lbl_img.pack(pady=(0,10))

            rarity = getattr(card, "rarity", "common")
            name = getattr(card, "name", "Carte")
            ttk.Label(frm, text=f"{name}", font=("Segoe UI", 13, "bold")).pack()
            ttk.Label(frm, text=f"Rareté : {rarity}").pack(pady=(4,8))

            if prog is not None:
                try:
                    lvl = int(prog["level"] or 1)
                    xp = int(prog["xp"] or 0)
                    streak = int(prog["streak"] or 0)
                    ttk.Label(frm, text=f"Niveau : {lvl}   XP : {xp}").pack()
                    ttk.Label(frm, text=f"Série : {streak} jour(s)").pack(pady=(2,10))
                except Exception:
                    pass

            ttk.Button(frm, text="OK", command=win.destroy).pack(pady=8)
        except Exception:
            # fallback
            from tkinter import messagebox
            messagebox.showinfo("Récompense", f"🎴 Nouvelle carte : {getattr(card,'name','')}", parent=self)

    def _show_simple_reward(self, prog=None):
        from tkinter import messagebox
        msg = "✅ Bravo ! Session terminée."
        if prog is not None:
            try:
                msg += f"\nNiveau : {int(prog['level'] or 1)}  |  Série : {int(prog['streak'] or 0)} jour(s)"
            except Exception:
                pass
        messagebox.showinfo("Récompense", msg, parent=self)

def on_close(self):
        try:
            self.game.stop()
        except Exception:
            pass
        try:
            self.dl.close()
        except Exception:
            pass
        self.destroy()