import tkinter as tk
from tkinter import ttk, messagebox

from speechcoach.settings import SettingsManager
from speechcoach.tts import list_voices


class AudioSettingsDialog(tk.Toplevel):
    def __init__(self, parent, audio_engine=None):
        super().__init__(parent)
        self.audio_engine = audio_engine
        self.title("Voix TTS")
        self.resizable(False, False)

        self.manager = SettingsManager()
        self.settings = self.manager.load()

        # Backend
        ttk.Label(self, text="Moteur").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.backend = tk.StringVar(value=self.settings.get("tts_backend", "system"))
        self.backend_cb = ttk.Combobox(
            self,
            textvariable=self.backend,
            values=["system", "edge"],
            width=35,
            state="readonly",
        )
        self.backend_cb.grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(self, text="system = voix Windows | edge = voix Neural (Internet)").grid(
            row=1, column=0, columnspan=2, sticky="w", padx=5, pady=(0, 8)
        )

        voices = list_voices()

        # Voix
        ttk.Label(self, text="Voix (system)").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.voice = tk.StringVar(value=self.settings.get("tts_voice", ""))
        self.voice_cb = ttk.Combobox(
            self, textvariable=self.voice,
            values=voices, width=35, state="readonly"
        )
        self.voice_cb.grid(row=2, column=1, padx=5, pady=5)

        # Vitesse
        ttk.Label(self, text="Vitesse").grid(row=3, column=0, sticky="w", padx=5)
        self.rate = tk.DoubleVar(value=float(self.settings.get("tts_rate", 1.0)))
        ttk.Scale(self, from_=0.5, to=1.5, variable=self.rate).grid(row=3, column=1, sticky="ew", padx=5)

        # Volume
        ttk.Label(self, text="Volume").grid(row=4, column=0, sticky="w", padx=5)
        self.volume = tk.DoubleVar(value=float(self.settings.get("tts_volume", 1.0)))
        ttk.Scale(self, from_=0.0, to=1.0, variable=self.volume).grid(row=4, column=1, sticky="ew", padx=5)

        # Boutons
        btn = ttk.Frame(self)
        btn.grid(row=5, column=0, columnspan=2, pady=10)

        ttk.Button(btn, text="Tester", command=self.test).pack(side="left", padx=5)
        ttk.Button(btn, text="Enregistrer", command=self.save).pack(side="left", padx=5)
        ttk.Button(btn, text="Fermer", command=self.close).pack(side="left", padx=5)

        self.protocol("WM_DELETE_WINDOW", self.close)

    def current(self):
        return {
            "tts_voice": self.voice.get(),
            "tts_rate": self.rate.get(),
            "tts_volume": self.volume.get(),
            "tts_backend": self.backend.get(),
        }

    def save(self):
        self.manager.save(self.current())
        # Apply to app engine
        if self.audio_engine is not None and hasattr(self.audio_engine, "tts"):
            try:
                self.audio_engine.tts.apply_settings(self.current())
            except Exception:
                pass
        messagebox.showinfo("Voix TTS", "Réglages enregistrés.", parent=self)

    def test(self):
        s = self.current()
        # Apply settings to engine then speak
        if self.audio_engine is not None and hasattr(self.audio_engine, "tts"):
            try:
                self.audio_engine.tts.apply_settings(s)
                self.audio_engine.tts.speak("Ceci est un test de la voix.")
                return
            except Exception:
                pass
        messagebox.showwarning("Test", "Impossible de jouer le test TTS.", parent=self)

    def close(self):
        try:
            self.destroy()
        except Exception:
            pass
