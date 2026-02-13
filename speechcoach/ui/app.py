import tkinter as tk
from speechcoach.game import GameState
from tkinter import ttk, messagebox
import threading

from speechcoach.config import (
    APP_NAME, APP_VERSION,
    DATA_DIR, AUDIO_DIR,
    DEFAULT_DB_PATH, DEFAULT_STORIES_PATH, FALLBACK_STORIES_PATH,
)
from speechcoach.utils_paths import ensure_dir, pick_existing
from speechcoach.db import DataLayer
from speechcoach.stories import StoryEngine
from speechcoach.audio import AudioEngine
from speechcoach.asr import ASREngine
from speechcoach.game import GameController

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

        ttk.Label(top, text="Tours:").pack(side="left")
        self.var_rounds = tk.IntVar(value=6)
        ttk.Spinbox(top, from_=1, to=20, textvariable=self.var_rounds, width=4).pack(side="left", padx=6)

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


    def start_game(self):
        if not self.current_child_id:
            messagebox.showwarning("Enfant", "Sélectionne d'abord un enfant.")
            return
        if len(self.stories.stories) == 0:
            messagebox.showerror("Stories", f"Aucune story chargée.\nChemin: {self.stories.path}")
            return

        try:
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
            self.btn_pause.config(state="normal")
            self.btn_replay.config(state="normal")
            self.game.start(rounds=int(self.var_rounds.get()))
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