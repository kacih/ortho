import threading
from typing import Any, Dict, List, Tuple

try:
    from faster_whisper import WhisperModel
except Exception:
    WhisperModel = None

class ASREngine:
    """Whisper local (faster-whisper)"""
    def __init__(self, model_size: str = "small"):
        self.model_size = model_size
        self.device = "cpu"
        self.compute_type = "int8"
        self._model = None
        self._lock = threading.Lock()

    def set_model(self, size: str):
        self.model_size = size
        with self._lock:
            self._model = None

    def _ensure_model(self):
        if WhisperModel is None:
            return None
        with self._lock:
            if self._model is None:
                try:
                    self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
                except Exception:
                    self._model = None
            return self._model

    def transcribe_words(self, wav_path: str) -> Tuple[str, List[Dict[str, Any]]]:
        model = self._ensure_model()
        if model is None:
            return "", []
        try:
            segments, _info = model.transcribe(
                wav_path, language="fr", word_timestamps=True, vad_filter=True, beam_size=5
            )
            words = []
            texts = []
            for seg in segments:
                if seg.text:
                    texts.append(seg.text.strip())
                if getattr(seg, "words", None):
                    for w in seg.words:
                        words.append({
                            "word": (getattr(w, "word", "") or "").strip(),
                            "start": float(getattr(w, "start", 0.0) or 0.0),
                            "end": float(getattr(w, "end", 0.0) or 0.0),
                        })
            return " ".join(texts).strip(), words
        except Exception:
            return "", []
