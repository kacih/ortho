import os
import threading
from typing import List, Optional, Tuple

try:
    import numpy as np
except Exception:
    np = None

try:
    import sounddevice as sd
except Exception:
    sd = None

try:
    import soundfile as sf
except Exception:
    sf = None

from .config import DEFAULT_SAMPLE_RATE
from .utils_paths import ensure_dir
from .tts import TTSEngine

class AudioEngine:
    """Audio record/play + devices + TTS wrapper."""
    def __init__(self):
        self.sample_rate = DEFAULT_SAMPLE_RATE
        self.tts = TTSEngine()
        self.input_device: Optional[int] = None
        self.output_device: Optional[int] = None

        if sd is not None:
            try:
                cur_in, cur_out = sd.default.device
                self.input_device, self.output_device = cur_in, cur_out
            except Exception:
                pass

    def list_input_devices(self) -> List[Tuple[int, str]]:
        if sd is None:
            return []
        out = []
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                out.append((i, d.get("name", f"device {i}")))
        return out

    def list_output_devices(self) -> List[Tuple[int, str]]:
        if sd is None:
            return []
        out = []
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_output_channels", 0) > 0:
                out.append((i, d.get("name", f"device {i}")))
        return out

    def set_devices(self, input_dev: Optional[int], output_dev: Optional[int]):
        self.input_device = input_dev
        self.output_device = output_dev
        if sd is None:
            return
        try:
            sd.default.device = (input_dev, output_dev)
        except Exception:
            pass

    def play_wav(self, path: str):
        if sd is None or sf is None:
            return
        if not os.path.exists(path):
            return
        data, sr = sf.read(path, dtype="float32", always_2d=False)
        # UX: certains drivers "mangent" l'attaque du son au démarrage.
        # On ajoute un très léger pré-roll (silence) pour fiabiliser.
        if np is not None and sr and sr > 0:
            try:
                pre = int(0.05 * float(sr))  # 50ms
                if pre > 0:
                    if getattr(data, "ndim", 1) == 1:
                        data = np.concatenate([np.zeros(pre, dtype=np.float32), data.astype(np.float32)])
                    else:
                        z = np.zeros((pre, data.shape[1]), dtype=np.float32)
                        data = np.concatenate([z, data.astype(np.float32)], axis=0)
            except Exception:
                pass
        try:
            sd.play(data, sr, device=self.output_device)
            sd.wait()
        except Exception:
            pass

    def record_until_silence_rms(
        self,
        out_path: str,
        stop_event: threading.Event,
        max_sec: float = 12.0,
        silence_sec: float = 1.0,
        base_threshold: float = 0.015,
        calibrate_sec: float = 0.45,
        threshold_mult: float = 3.0,
        min_total_sec: float = 1.2,
        min_speech_sec: float = 0.6,
    ) -> Tuple[float, float]:
        ensure_dir(os.path.dirname(out_path) or ".")
        if sd is None or sf is None or np is None:
            if sf is not None and np is not None:
                sf.write(out_path, np.zeros(int(self.sample_rate * 0.2), dtype=np.float32), self.sample_rate)
            return 0.2, 0.0

        if self.input_device is None:
            raise RuntimeError("Aucun micro sélectionné.")

        sr = self.sample_rate
        block_sec = 0.03
        bs = int(block_sec * sr)
        max_blocks = int(max_sec / block_sec)
        silence_need = int(silence_sec / block_sec)
        min_total = int(min_total_sec / block_sec)
        min_speech = int(min_speech_sec / block_sec)
        calib = max(1, int(calibrate_sec / block_sec))

        frames = []
        started = False
        silent = 0
        speech = 0
        total = 0

        def rms(x):
            return float(np.sqrt(np.mean(x * x))) if x.size else 0.0

        noise = []
        with sd.InputStream(samplerate=sr, channels=1, dtype="float32", device=self.input_device) as stream:
            for _ in range(calib):
                d, _ = stream.read(bs)
                noise.append(rms(d.flatten()))
            noise_med = float(np.median(noise)) if noise else 0.0
            thr = max(float(base_threshold), noise_med * float(threshold_mult))

            for _ in range(max_blocks):
                if stop_event.is_set():
                    break
                d, _ = stream.read(bs)
                x = d.flatten()
                total += 1
                r = rms(x)

                if r > thr:
                    started = True
                    silent = 0
                    speech += 1
                    frames.append(x.copy())
                else:
                    if started:
                        silent += 1
                        frames.append(x.copy())
                        if speech >= min_speech and total >= min_total and silent >= silence_need:
                            break

        audio = np.concatenate(frames) if frames else np.zeros(1, dtype="float32")
        sf.write(out_path, audio, sr)
        return float(audio.size) / float(sr), thr
