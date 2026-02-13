# speechcoach/tts.py
import os
import platform
import subprocess
import threading
import queue
import logging
from typing import Optional, Dict, Any, List

import soundfile as sf
import sounddevice as sd

logger = logging.getLogger("speechcoach.tts")
log = logging.getLogger(__name__)

# pyttsx3 optionnel (instable selon Python/Win). Conservé mais OFF par défaut.
try:
    import pyttsx3  # type: ignore
except Exception:
    pyttsx3 = None


# Child-friendly TTS profiles (voice selection is best-effort because installed voices vary by system).
CHILD_VOICE_PROFILES = {
    "warm": {"rate_ps": 0, "volume": 100},
    "gentle": {"rate_ps": -1, "volume": 100},
    "energetic": {"rate_ps": 1, "volume": 100},
    "playful": {"rate_ps": 2, "volume": 100},
    "storyteller": {"rate_ps": 0, "volume": 100},
}

CHILD_PROMPTS = [
    "Super ! Tu peux commencer à répéter.",
    "Top ! Quand tu es prêt, tu répètes.",
    "Génial ! Vas-y doucement, répète la phrase.",
    "Bravo ! On y va : tu peux répéter maintenant.",
]


def _xml_escape(s: str) -> str:
    """Minimal XML escaping for SSML."""
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _ps_run(script: str) -> subprocess.CompletedProcess:
    """
    Run PowerShell script (Windows). NoProfile = stable.
    CREATE_NO_WINDOW avoids popping a console window.
    """
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        creationflags=creationflags,
    )


def list_voices() -> List[str]:
    """Return list of installed Windows TTS voices (System.Speech)."""
    ps = r"""
    Add-Type -AssemblyName System.Speech
    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }
    """
    try:
        r = _ps_run(ps)
        if r.returncode != 0:
            log.error("list_voices error: %s", r.stderr)
            return []
        voices = [v.strip() for v in r.stdout.splitlines() if v.strip()]
        return sorted(set(voices))
    except Exception:
        log.exception("list_voices failed")
        return []


def list_edge_voices(locale_prefix: str = "fr-") -> List[str]:
    """Return available Edge Neural voices (best-effort).
    Non-blocking philosophy: on any error, return [].
    """
    try:
        import asyncio
        import edge_tts  # type: ignore
    except Exception:
        return []

    async def _run():
        vs = await edge_tts.list_voices()
        out: List[str] = []
        for v in vs or []:
            name = v.get("ShortName") or v.get("Name")
            locale = v.get("Locale") or ""
            if name and (not locale_prefix or str(locale).lower().startswith(locale_prefix.lower())):
                out.append(str(name))
        return sorted(set(out))

    try:
        return asyncio.run(_run())
    except Exception:
        return []


def _speak_edge_tts_to_mp3(text: str, voice: str, out_path: str, timeout_sec: int = 30) -> bool:
    """
    Edge Neural TTS via CLI, MP3 output (edge-tts 7.2.7 compatible).
    Returns True only if the output file exists and is non-empty.
    """
    try:
        import sys
    except Exception:
        return False

    text = (text or "").strip()
    if not text:
        return False

    voice = (voice or "").strip() or "fr-FR-DeniseNeural"

    try:
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        # IMPORTANT: edge-tts 7.2.7 CLI does NOT support --format
        cmd = [
            sys.executable,
            "-m",
            "edge_tts",
            "--voice",
            voice,
            "--text",
            text,
            "--write-media",
            out_path,
        ]

        logger.info("EDGE mp3 start voice=%s text_len=%s out=%s", voice, len(text), out_path)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)

        if p.returncode != 0:
            logger.warning("EDGE mp3 failed rc=%s stderr=%s", p.returncode, (p.stderr or "").strip())
            return False

        ok = os.path.exists(out_path) and os.path.getsize(out_path) > 0
        logger.info(
            "EDGE mp3 done ok=%s size=%s",
            ok,
            os.path.getsize(out_path) if os.path.exists(out_path) else 0,
        )
        return ok
    except Exception as e:
        logger.exception("EDGE mp3 exception: %s", e)
        return False


def _speak_powershell(text: str, voice: Optional[str], rate: int, volume: int) -> None:
    if platform.system().lower() != "windows":
        return

    text = (text or "").strip()
    if not text:
        return

    # articulation
    text = text.replace(".", ". ").replace(",", ", ").replace(";", "; ")

    wake_ms = 250
    pre_ms = 180
    ssml_text = _xml_escape(text)
    ssml_wake = f"<speak version='1.0' xml:lang='fr-FR'><break time='{wake_ms}ms'/></speak>"
    ssml_main = f"<speak version='1.0' xml:lang='fr-FR'><break time='{pre_ms}ms'/>{ssml_text}</speak>"

    safe_wake = ssml_wake.replace("\\", "\\\\").replace('"', '`"')
    safe_main = ssml_main.replace("\\", "\\\\").replace('"', '`"')

    voice_line = ""
    if voice:
        safe_voice = str(voice).replace("\\", "\\\\").replace('"', '`"')
        voice_line = f'$s.SelectVoice("{safe_voice}");'

    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"{voice_line}"
        f"$s.Rate = {int(max(-10, min(10, rate)))};"
        f"$s.Volume = {int(max(0, min(100, volume)))};"
        f'$s.SpeakSsml("{safe_wake}");'
        f'$s.SpeakSsml("{safe_main}");'
    )

    try:
        r = _ps_run(ps)
        if r.returncode != 0:
            log.error("TTS speak error: %s", r.stderr)
    except Exception:
        log.exception("TTS speak failed")


class TTSEngine:
    """
    Interface TTS historique du projet (compat audio.py).
    - Windows stable: PowerShell System.Speech (default)
    - Optionnel: pyttsx3
    - Optionnel: Edge Neural via edge-tts CLI (MP3) + soundfile+sounddevice playback
    """

    def __init__(self):
        self.rate = 150  # legacy
        self.voice: Optional[str] = None  # system voice name
        self.volume = 100  # 0..100
        self.use_pyttsx3 = False

        # backends: "system" | "edge"
        self.backend = "system"
        self.edge_voice = "fr-FR-DeniseNeural"

        self._lock = threading.Lock()
        self._is_windows = platform.system().lower() == "windows"
        self._pytts = None

        # Serial TTS queue (ensures ordered prompts)
        self._tts_queue: "queue.Queue[tuple]" = queue.Queue()
        self._tts_worker = threading.Thread(target=self._tts_loop, daemon=True)
        self._tts_worker.start()

    # ---------- basic settings ----------
    def set_rate(self, rate: int):
        self.rate = int(rate)

    def set_voice(self, voice: Optional[str]):
        self.voice = voice

    def set_volume(self, volume_0_100: int):
        self.volume = int(max(0, min(100, volume_0_100)))

    def enable_pyttsx3(self, enabled: bool):
        self.use_pyttsx3 = bool(enabled)
        if not enabled:
            self._pytts = None

    def warmup(self):
        self.speak(" ")

    # ---------- queue helpers ----------
    def say(self, text: str, *, block: bool = False):
        """Queue a TTS utterance (serialized). If block=True, wait until spoken."""
        ev = threading.Event()
        self._tts_queue.put(("speak", text, None, ev))
        if block:
            ev.wait(timeout=30)

    def say_child(self, text: str, *, style: str = "warm", block: bool = False):
        ev = threading.Event()
        self._tts_queue.put(("child", text, style, ev))
        if block:
            ev.wait(timeout=30)

    def say_child_prompt(self, *, style: str = "warm", block: bool = False):
        ev = threading.Event()
        self._tts_queue.put(("child_prompt", "", style, ev))
        if block:
            ev.wait(timeout=30)

    def _tts_loop(self):
        while True:
            kind, text, style, ev = self._tts_queue.get()
            try:
                if kind == "speak":
                    self.speak(text)
                elif kind == "child":
                    self.speak_child(text, style=style or "warm")
                elif kind == "child_prompt":
                    self.speak_child_prompt(style=style or "warm")
            except Exception:
                pass
            finally:
                try:
                    ev.set()
                except Exception:
                    pass

    # ---------- playback helpers ----------
    def _play_audio_file(self, path: str) -> bool:
        """Play an audio file (mp3/wav/...) using soundfile + sounddevice."""
        try:
            data, sr = sf.read(path, dtype="float32")
            sd.play(data, sr)
            sd.wait()
            logger.info("PLAY ok path=%s sr=%s frames=%s", path, sr, getattr(data, "shape", None))
            return True
        except Exception as e:
            logger.warning("PLAY failed path=%s err=%s", path, e)
            return False

    def _speak_edge_mp3(self, text: str) -> bool:
        """Generate Edge mp3 and play it. Returns True if spoken."""
        try:
            from pathlib import Path
            from .config import AUDIO_DIR
        except Exception:
            return False

        try:
            Path(AUDIO_DIR).mkdir(parents=True, exist_ok=True)
            out_path = str(Path(AUDIO_DIR) / "edge_tts_tmp.mp3")
            ok = _speak_edge_tts_to_mp3(text, self.edge_voice, out_path)
            if not ok:
                return False
            return self._play_audio_file(out_path)
        except Exception as e:
            logger.warning("EDGE mp3 pipeline failed: %s", e)
            return False

    # ---------- child speech ----------
    def speak_child(self, text: str, style: str = "warm"):
        prof = CHILD_VOICE_PROFILES.get(style, CHILD_VOICE_PROFILES["warm"])
        rate_ps = int(prof.get("rate_ps", 0))
        vol = int(prof.get("volume", self.volume))

        text = (text or "").strip()
        if not text:
            return

        if (self.backend or "system") == "edge":
            # edge path must never break the app
            if self._speak_edge_mp3(" " + text):
                return
            logger.info("EDGE child fallback to system")

        if self._is_windows:
            with self._lock:
                _speak_powershell(" " + text, self.voice, rate_ps, vol)
        else:
            self.speak(text)

    def speak_child_prompt(self, style: str = "warm"):
        import random
        self.speak_child(random.choice(CHILD_PROMPTS), style=style)

    # ---------- settings integration ----------
    def apply_settings(self, settings: Dict[str, Any]):
        """
        Accept settings dict from SettingsManager.
        - tts_backend: "system" | "edge"
        - tts_voice:   system voice name
        - edge_voice:  edge shortname (e.g., fr-FR-DeniseNeural)
        - tts_rate:    float (0.5..1.5)
        - tts_volume:  float (0.0..1.0)
        """
        if not settings:
            return

        if "tts_backend" in settings:
            self.backend = (settings.get("tts_backend") or "system").strip()

        # Important: tts_voice is SYSTEM voice. edge_voice is EDGE voice.
        if "tts_voice" in settings:
            self.set_voice(settings.get("tts_voice") or None)

        if "edge_voice" in settings:
            ev = (settings.get("edge_voice") or "").strip()
            if ev:
                self.edge_voice = ev

        if "tts_volume" in settings:
            self.set_volume(int(float(settings["tts_volume"]) * 100))

        if "tts_rate" in settings:
            factor = float(settings["tts_rate"])
            self.set_rate(int(165 + (factor - 1.0) * 30))

    # ---------- main speak ----------
    def speak(self, text: str):
        text = (text or "").strip()
        if not text:
            return

        if (self.backend or "system") == "edge":
            if self._speak_edge_mp3(text):
                return
            logger.info("EDGE fallback to system")

        # articulation
        text = text.replace(".", ". ").replace(",", ", ").replace(";", "; ")

        with self._lock:
            if self.use_pyttsx3 and pyttsx3 is not None:
                eng = self._ensure_pyttsx3()
                if eng is not None:
                    try:
                        eng.setProperty("rate", self.rate)
                        eng.setProperty("volume", max(0.0, min(1.0, self.volume / 100.0)))
                        if self.voice:
                            try:
                                eng.setProperty("voice", self.voice)
                            except Exception:
                                pass
                        eng.say(" ")
                        eng.say(text)
                        eng.runAndWait()
                        return
                    except Exception:
                        self._pytts = None

            self._speak_powershell_legacy(text)

    def _ensure_pyttsx3(self):
        if pyttsx3 is None:
            return None
        if self._pytts is not None:
            return self._pytts
        try:
            eng = pyttsx3.init()
            eng.setProperty("rate", self.rate)
            eng.setProperty("volume", max(0.0, min(1.0, self.volume / 100.0)))
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

    def _speak_powershell_legacy(self, text: str):
        if not self._is_windows:
            return
        r = max(-10, min(10, int((self.rate - 165) / 15)))
        _speak_powershell(text=text, voice=self.voice, rate=r, volume=self.volume)


def speak(text: str, settings: Optional[Dict[str, Any]] = None, async_: bool = True) -> None:
    """
    Convenience function for UI usage.
    settings:
      - tts_voice  (str)
      - tts_rate   (float 0.5..1.5)  # 1.0 = normal
      - tts_volume (float 0.0..1.0)
    """
    if not text or not text.strip():
        return

    settings = settings or {}
    voice = settings.get("tts_voice") or None
    rate_f = float(settings.get("tts_rate", 1.0))
    vol_f = float(settings.get("tts_volume", 1.0))

    rate = int(max(-10, min(10, (rate_f - 1.0) * 10)))
    volume = int(max(0, min(100, vol_f * 100)))

    def _job():
        _speak_powershell(text=text, voice=voice, rate=rate, volume=volume)

    if async_:
        threading.Thread(target=_job, daemon=True).start()
    else:
        _job()
