import platform
import subprocess
import threading
from typing import Optional

# pyttsx3 optionnel (instable selon Python/Win). On le gardera, mais OFF par défaut.
try:
    import pyttsx3
except Exception:
    pyttsx3 = None

class TTSEngine:
    """
    Interface unique TTS.
    - Windows stable: PowerShell System.Speech (default)
    - Optionnel: pyttsx3
    """
    def __init__(self):
        self.rate = 150
        self.voice: Optional[str] = None
        self.use_pyttsx3 = False
        self._lock = threading.Lock()
        self._is_windows = platform.system().lower() == "windows"
        self._pytts = None

    def set_rate(self, rate: int):
        self.rate = int(rate)

    def set_voice(self, voice: Optional[str]):
        self.voice = voice

    def enable_pyttsx3(self, enabled: bool):
        self.use_pyttsx3 = bool(enabled)
        if not enabled:
            self._pytts = None

    def warmup(self):
        self.speak(" ")

    def speak(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        # articulation
        text = text.replace(".", ". ").replace(",", ", ").replace(";", "; ")

        with self._lock:
            if self.use_pyttsx3 and pyttsx3 is not None:
                eng = self._ensure_pyttsx3()
                if eng is not None:
                    try:
                        eng.setProperty("rate", self.rate)
                        eng.say(" ")
                        eng.say(text)
                        eng.runAndWait()
                        return
                    except Exception:
                        self._pytts = None
            # fallback stable
            self._speak_powershell(text)

    def _ensure_pyttsx3(self):
        if pyttsx3 is None:
            return None
        if self._pytts is not None:
            return self._pytts
        try:
            eng = pyttsx3.init()
            eng.setProperty("rate", self.rate)
            if self.voice:
                try:
                    eng.setProperty("voice", self.voice)
                except Exception:
                    pass
            self._pytts = eng
            return eng
        except Exception:
            self._pytts = None
            return None

    def _speak_powershell(self, text: str):
        if not self._is_windows:
            return
        r = max(-10, min(10, int((self.rate - 165) / 15)))

        safe_text = (text or "").replace("\\", "\\\\").replace('"', '\\"')
        voice_line = ""
        if self.voice:
            safe_voice = str(self.voice).replace("\\", "\\\\").replace('"', '\\"')
            voice_line = f'$s.SelectVoice("{safe_voice}");'

        ps = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            f"{voice_line}"
            f"$s.Rate = {r};"
            f'$s.Speak("{safe_text}");'
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                capture_output=True,
                text=True
            )
        except Exception:
            pass
