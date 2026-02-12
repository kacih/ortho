import tkinter as tk
from tkinter import ttk

from speechcoach.settings import SettingsManager
from speechcoach.tts import speak, list_voices


class AudioSettingsDialog(tk.Toplevel):

    def __init__(self, parent, audio_engine=None):
        super().__init__(parent)
        self.audio_engine = audio_engine
        self.title("Réglages audio")
        self.resizable(False, False)

        self.manager = SettingsManager()
        self.settings = self.manager.load()

        voices = list_voices()

        # Voix
        ttk.Label(self, text="Voix").grid(row=0, column=0, sticky="w", padx=5, pady=5)

        self.voice = tk.StringVar(value=self.settings["tts_voice"])
        self.voice_cb = ttk.Combobox(
            self, textvariable=self.voice,
            values=voices, width=35, state="readonly"
        )
        self.voice_cb.grid(row=0, column=1, padx=5, pady=5)

        # Vitesse
        ttk.Label(self, text="Vitesse").grid(row=1, column=0, sticky="w", padx=5)

        self.rate = tk.DoubleVar(value=self.settings["tts_rate"])
        ttk.Scale(self, from_=0.5, to=1.5, variable=self.rate)\
            .grid(row=1, column=1, sticky="ew", padx=5)

        # Volume
        ttk.Label(self, text="Volume").grid(row=2, column=0, sticky="w", padx=5)

        self.volume = tk.DoubleVar(value=self.settings["tts_volume"])
        ttk.Scale(self, from_=0.0, to=1.0, variable=self.volume)\
            .grid(row=2, column=1, sticky="ew", padx=5)

        # Boutons
        btn = ttk.Frame(self)
        btn.grid(row=3, column=0, columnspan=2, pady=10)

        ttk.Button(btn, text="Tester", command=self.test).pack(side="left", padx=5)
        ttk.Button(btn, text="Fermer", command=self.close).pack(side="left", padx=5)

        self.protocol("WM_DELETE_WINDOW", self.close)

    def current(self):
        return {
            "tts_voice": self.voice.get(),
            "tts_rate": self.rate.get(),
            "tts_volume": self.volume.get()
        }

    def test(self):
        s = self.current()

        # Appliquer les settings au moteur TTS de l'app si disponible
        if self.audio_engine is not None and hasattr(self.audio_engine, "tts"):
            try:
                self.audio_engine.tts.apply_settings(s)
                self.audio_engine.tts.speak("Ceci est un test de la voix.")
                return
            except Exception:
                pass

        # Fallback (au cas où)
        speak("Ceci est un test de la voix.", s)


    def close(self):
        s = self.current()
        self.manager.save(s)

        if self.audio_engine is not None and hasattr(self.audio_engine, "tts"):
            try:
                self.audio_engine.tts.apply_settings(s)
            except Exception:
                pass

        self.destroy()

