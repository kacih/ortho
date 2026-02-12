from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np
except Exception:
    np = None

try:
    import librosa
except Exception:
    librosa = None

from .config import DEFAULT_SAMPLE_RATE
from .utils_text import normalize_text_fr

import soundfile as sf

def clamp(x, a, b):
    return max(a, min(b, x))

def cosine_similarity(a: "np.ndarray", b: "np.ndarray") -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
    return float(np.dot(a, b) / denom)

def load_audio_strict(wav_path, target_sr):
    y, sr = sf.read(wav_path, dtype="float32", always_2d=False)

    # mono
    if getattr(y, "ndim", 1) > 1:
        y = np.mean(y, axis=1).astype("float32")

    # resample si nécessaire
    if sr != target_sr:
        y = librosa.resample(y, orig_sr=sr, target_sr=target_sr).astype("float32")
        sr = target_sr

    return y, sr

def extract_features(wav_path: str, start_sec: float = 0.0, end_sec: Optional[float] = None) -> Dict[str, Any]:
    if np is None or librosa is None:
        return {}
    y, sr = load_audio_strict(wav_path, DEFAULT_SAMPLE_RATE)

    if end_sec is None:
        end_sec = len(y) / sr
    a = int(clamp(start_sec, 0, 1e9) * sr)
    b = int(clamp(end_sec, 0, 1e9) * sr)
    y = y[a:b] if b > a else y
    if len(y) < int(0.08 * sr):
        return {}

    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    mfcc_mean = np.mean(mfcc, axis=1)
    zcr = float(np.mean(librosa.feature.zero_crossing_rate(y)))
    rms = float(np.mean(librosa.feature.rms(y=y)))
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    rolloff = float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr)))

    return {
        "mfcc_mean": mfcc_mean.tolist(),
        "zcr": zcr,
        "rms": rms,
        "centroid": centroid,
        "rolloff": rolloff,
        "sr": sr,
        "dur_sec": len(y)/float(sr),
    }

def vectorize_features(feat: Dict[str, Any]) -> Optional["np.ndarray"]:
    if np is None or not feat:
        return None
    v = []
    mm = feat.get("mfcc_mean", [])
    if isinstance(mm, list) and mm:
        v.extend([float(x) for x in mm])
    for k in ["zcr", "rms", "centroid", "rolloff"]:
        if k in feat:
            v.append(float(feat[k]))
    if not v:
        return None
    arr = np.array(v, dtype=np.float32)
    arr = (arr - np.mean(arr)) / (np.std(arr) + 1e-6)
    return arr

def acoustic_score_from_features(feat: Dict[str, Any], ref: Dict[str, Any]) -> float:
    if np is None:
        return 0.0
    a = vectorize_features(feat)
    b = vectorize_features(ref)
    if a is None or b is None:
        return 0.0
    return cosine_similarity(a, b)

def phoneme_confidence_score(target_sim: float, contrast_sim: float) -> float:
    return float(target_sim - contrast_sim)

def final_score_v71(wer_value: float, acoustic: float) -> float:
    wer_value = clamp(wer_value, 0.0, 1.0)
    acoustic01 = clamp((acoustic + 1.0) / 2.0, 0.0, 1.0)
    return float(0.35 * (1.0 - wer_value) + 0.65 * acoustic01)

def find_focus_window(words: List[Dict[str, Any]], target_word: str) -> Tuple[float, float]:
    tgt = normalize_text_fr(target_word)
    if not words:
        return 0.0, 1.2
    if not tgt:
        s = float(words[0].get("start", 0.0))
        e = float(words[-1].get("end", 1.0))
        return max(0.0, s), e + 0.2

    for w in words:
        ww = normalize_text_fr(w.get("word", ""))
        if ww == tgt or tgt in ww or ww in tgt:
            s = float(w.get("start", 0.0))
            e = float(w.get("end", s + 0.2))
            return max(0.0, s - 0.12), e + 0.18

    mid = words[len(words)//2]
    s = float(mid.get("start", 0.0))
    e = float(mid.get("end", s + 0.2))
    return max(0.0, s - 0.12), e + 0.18
