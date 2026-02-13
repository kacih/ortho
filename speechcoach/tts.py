# speechcoach/tts.py
import os
import platform
import subprocess
import threading
import queue
import logging
logger = logging.getLogger("speechcoach.tts")
from typing import Optional, Dict, Any, List

# pyttsx3 optionnel (instable selon Python/Win). Conservé mais OFF par défaut.
try:
    import pyttsx3
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
log = logging.getLogger(__name__)


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
        out = []
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




def _play_wav_powershell(path: str) -> None:
    if platform.system().lower() != "windows":
        return
    if not path:
        return
    ps = f"""
    try {{
      Add-Type -AssemblyName System.Windows.Forms | Out-Null
      $p = '{path}'.Replace('\\','/')
      $sp = New-Object System.Media.SoundPlayer($p)
      $sp.PlaySync()
    }} catch {{}}
    """
    try:
        _ps_run(ps)
    except Exception:
        pass


def _speak_edge_tts_to_wav(text: str, voice: str, out_path: str) -> bool:
    """Best-effort Edge Neural TTS (non-blocking: caller falls back if False).

    We intentionally use the edge-tts CLI via subprocess because the Python API
    varies across versions. CLI supports --format for RIFF PCM (wav) output.
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
            "--format",
            "riff-24khz-16bit-mono-pcm",
        ]

        logger.info("EDGE speak start voice=%s text_len=%s out=%s", voice, len(text), out_path)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if p.returncode != 0:
            logger.warning("EDGE speak failed rc=%s stderr=%s", p.returncode, (p.stderr or "").strip())
            return False

        ok = os.path.exists(out_path) and os.path.getsize(out_path) > 0
        logger.info("EDGE speak done ok=%s size=%s", ok, os.path.getsize(out_path) if os.path.exists(out_path) else 0)
        return ok
    except Exception as e:
        logger.exception("EDGE speak exception: %s", e)
        return False

    text = (text or "").strip()
    if not text:
        return False

    async def _run():
        communicate = edge_tts.Communicate(
            text,
            voice=voice or "fr-FR-DeniseNeural",
            rate="+0%",
            volume="+0%",
        )
        # Produce WAV (riff) so SoundPlayer can play it directly
        await communicate.save(out_path, output_format="riff-24khz-16bit-mono-pcm")

    try:
        asyncio.run(_run())
        return os.path.exists(out_path)
    except Exception:
        return False

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

    # Map [0.5..1.5] to PowerShell Rate [-10..10]
    # 1.0 -> 0 ; 0.5 -> -5 ; 1.5 -> +5
    rate = int(max(-10, min(10, (rate_f - 1.0) * 10)))
    volume = int(max(0, min(100, vol_f * 100)))

    def _job():
        _speak_powershell(text=text, voice=voice, rate=rate, volume=volume)

    if async_:
        threading.Thread(target=_job, daemon=True).start()
    else:
        _job()


def _speak_powershell(text: str, voice: Optional[str], rate: int, volume: int) -> None:
    if platform.system().lower() != "windows":
        return

    # articulation
    text = (text or "").strip()
    if not text:
        return
    text = text.replace(".", ". ").replace(",", ", ").replace(";", "; ")

    # NOTE UX: certains périphériques "réveillent" la sortie audio et mangent
    # les premières lettres. On fait un "wake" explicite (silence SSML), puis
    # on parle le texte (avec un léger break). C'est volontairement un peu
    # conservateur: mieux vaut 200ms de latence que des syllabes tronquées.
    wake_ms = 250
    pre_ms = 180
    ssml_text = _xml_escape(text)
    ssml_wake = f"<speak version='1.0' xml:lang='fr-FR'><break time='{wake_ms}ms'/></speak>"
    ssml_main = f"<speak version='1.0' xml:lang='fr-FR'><break time='{pre_ms}ms'/>{ssml_text}</speak>"

    # Escape for PowerShell double-quoted string
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
    """

    def __init__(self):
        # Historique: rate ~ 150 (pyttsx3) ; on garde
        self.rate = 150                 # "WPM-like" for pyttsx3 path
        self.voice: Optional[str] = None
        self.volume = 100               # 0..100 for PowerShell path
        self.use_pyttsx3 = False
        self.backend = "system"  # system | edge
        self.edge_voice = "fr-FR-DeniseNeural"
        self._lock = threading.Lock()
        self._is_windows = platform.system().lower() == "windows"
        self._pytts = None

        # ---- Serial TTS queue (ensures ordered prompts)
        self._tts_queue: "queue.Queue[tuple]" = queue.Queue()
        self._tts_worker = threading.Thread(target=self._tts_loop, daemon=True)
        self._tts_worker.start()

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
                # Never let TTS break the app
                pass
            finally:
                try:
                    ev.set()
                except Exception:
                    pass

    def speak_child(self, text: str, style: str = "warm"):
        """Speak with kid-friendly settings (best-effort across Windows voices)."""
        prof = CHILD_VOICE_PROFILES.get(style, CHILD_VOICE_PROFILES["warm"])
        # PowerShell path uses SpeechSynthesizer.Rate (-10..10). We'll map gently around 0.
        rate_ps = int(prof.get("rate_ps", 0))
        vol = int(prof.get("volume", self.volume))

        if (getattr(self, "backend", "system") or "system") == "edge":
            try:
                from pathlib import Path
                from .config import AUDIO_DIR
                Path(AUDIO_DIR).mkdir(parents=True, exist_ok=True)
                out_path = str(Path(AUDIO_DIR) / "edge_tts_tmp.wav")
                ok = _speak_edge_tts_to_wav(' ' + text, getattr(self, "edge_voice", "fr-FR-DeniseNeural"), out_path)
                if ok:
                    _play_wav_powershell(out_path)
                    return
            except Exception:
                pass

        # We keep the configured voice if any; voice choice is user/system dependent.
        if self._is_windows:
            with self._lock:
                _speak_powershell(' ' + text, self.voice, rate_ps, vol)
        else:
            # fallback
            self.speak(text)

    def speak_child_prompt(self, style: str = "warm"):
        import random
        self.speak_child(random.choice(CHILD_PROMPTS), style=style)

    def apply_settings(self, settings: Dict[str, Any]):
        """
        Accept settings dict from SettingsManager.
        - tts_voice: str
        - tts_rate: float (0.5..1.5)
        - tts_volume: float (0.0..1.0)
        """
        if not settings:
            return
        if "tts_backend" in settings:
            self.backend = (settings.get("tts_backend") or "system").strip()
        if "tts_voice" in settings:
            self.set_voice(settings.get("tts_voice") or None)
        if "tts_volume" in settings:
            self.set_volume(int(float(settings["tts_volume"]) * 100))
        if "tts_rate" in settings:
            # Map factor -> approximate legacy rate integer
            # 1.0 ~ 165 baseline, keep your previous mapping behavior
            factor = float(settings["tts_rate"])
            self.set_rate(int(165 + (factor - 1.0) * 30))

    def speak(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        # Optional Edge Neural TTS (must never be blocking): fallback to system voice on any failure.
        if (getattr(self, "backend", "system") or "system") == "edge":
            try:
                import os
                from pathlib import Path
                from .config import AUDIO_DIR
                Path(AUDIO_DIR).mkdir(parents=True, exist_ok=True)
                out_path = str(Path(AUDIO_DIR) / "edge_tts_tmp.wav")
                ok = _speak_edge_tts_to_wav(text, getattr(self, "edge_voice", "fr-FR-DeniseNeural"), out_path)
                if ok:
                    _play_wav_powershell(out_path)
                    return
            except Exception:
                pass


        # articulation
        text = text.replace(".", ". ").replace(",", ", ").replace(";", "; ")

        with self._lock:
            if self.use_pyttsx3 and pyttsx3 is not None:
                eng = self._ensure_pyttsx3()
                if eng is not None:
                    try:
                        eng.setProperty("rate", self.rate)
                        # volume in pyttsx3 is 0.0..1.0
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

            # fallback stable (Windows PowerShell)
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

        # Historique : mapping rate int -> [-10..10]
        r = max(-10, min(10, int((self.rate - 165) / 15)))

        _speak_powershell(
            text=text,
            voice=self.voice,
            rate=r,
            volume=self.volume
        )