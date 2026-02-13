import tkinter as tk
from speechcoach.game import GameState
from tkinter import ttk, messagebox
import threading

from speechcoach.config import (
    APP_NAME, APP_VERSION,
    DATA_DIR, AUDIO_DIR,
    DEFAULT_DB_PATH, DEFAULT_STORIES_PATH, FALLBACK_STORIES_PATH,
    RESOURCES_DIR,
)
from speechcoach.utils_paths import ensure_dir, pick_existing
from speechcoach.db import DataLayer
from speechcoach.stories import StoryEngine
from speechcoach.audio import AudioEngine
from speechcoach.asr import ASREngine
from speechcoach.game import GameController
from speechcoach.session_manager import build_session_plan, get_preset_plan, preset_plans
from speechcoach.rewards import load_catalog, choose_new_card_for_child

from .dialogs_children import ChildManagerDialog
from .dialogs_dashboard import DashboardDialog
from .dialogs_audio import AudioSettingsDialog as AudioDevicesDialog
from .panels_analysis import AnalysisPanel
from speechcoach.ui.audio_settings import AudioSettingsDialog as TTSAudioSettingsDialog


class SpeechCoachApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} — {APP_VERSION}")
        self.geometry("1060x740")

        ensure_dir(DATA_DIR)
        ensure_dir(AUDIO_DIR)

        db_path = DEFAULT_DB_PATH
        stories_path = pick_existing(DEFAULT_STORIES_PATH, FALLBACK_STORIES_PATH)

        self.dl = DataLayer(db_path)
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

        m_child = tk.Menu(menubar, tearoff=0)
        m_child.add_command(label="Gérer les enfants…", command=self.open_children)
        menubar.add_cascade(label="Enfants", menu=m_child)

        m_audio = tk.Menu(menubar, tearoff=0)
        m_audio.add_command(label="Audio (micro/sortie)…", command=self.open_audio_devices)
        m_audio.add_command(label="Voix TTS…", command=self.open_tts_settings)
        m_audio.add_separator()
        menubar.add_cascade(label="Audio", menu=m_audio)

        m_dash = tk.Menu(menubar, tearoff=0)
        m_dash.add_command(label="Dashboard Pro…", command=self.open_dashboard)
        menubar.add_cascade(label="TDB", menu=m_dash)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="À propos", command=lambda: messagebox.showinfo("À propos", f"{APP_NAME}\n{APP_VERSION}"))
        menubar.add_cascade(label="Aide", menu=m_help)
        self.config(menu=menubar)

    def _build_ui(self):
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
        ttk.Button(top, text="Sélectionner…", command=self.open_children).pack(side="left", padx=6)

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)

        self.var_child_mode = tk.BooleanVar(value=False)
        self.chk_child_mode = ttk.Checkbutton(
            top,
            text="Mode enfant (auto)",
            variable=self.var_child_mode,
            command=self.on_toggle_mode
        )
        self.chk_child_mode.pack(side="left", padx=6)

        # Sprint 1: plan presets (adult mode)
        ttk.Label(top, text="Plan:").pack(side="left")
        self.var_plan_id = tk.StringVar(value="standard")
        self.cmb_plan = ttk.Combobox(
            top,
            textvariable=self.var_plan_id,
            state="readonly",
            width=12,
            values=["libre","decouverte","standard","intensif"]
        )
        self.cmb_plan.pack(side="left", padx=6)
        self.cmb_plan.bind("<<ComboboxSelected>>", lambda e: self.on_plan_change())

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

    def open_dashboard(self):
        DashboardDialog(
            self,
            self.dl,
            self.audio,
            self.current_child_id,
            on_pick=self.show_evolution_graph
        )

    def show_evolution_graph(self, session_id, child_id, phoneme):
        print("GRAPH:", session_id, child_id, phoneme)


    
    def on_plan_change(self):
        """Apply preset plan values to duration/rounds (Sprint 1)."""
        try:
            # Do not interfere with child mode
            if getattr(self, "var_child_mode", None) is not None and self.var_child_mode.get():
                return
            pid = (self.var_plan_id.get() or "libre").strip().lower()
            if pid in ("decouverte","standard","intensif"):
                plan = get_preset_plan(pid)
                try:
                    self.var_minutes.set(int(plan.duration_min))
                except Exception:
                    pass
                try:
                    self.var_rounds.set(int(plan.rounds))
                except Exception:
                    pass
            else:
                # Libre: keep current rounds
                pass
        except Exception:
            pass

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
            pid = (getattr(self, "var_plan_id", None) and self.var_plan_id.get()) or "libre"
            pid = str(pid).strip().lower()
            plan = get_preset_plan(pid) if pid in ("decouverte","standard","intensif") else None
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