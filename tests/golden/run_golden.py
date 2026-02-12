import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json
import time

from speechcoach.asr import ASREngine

from speechcoach.analysis import (
    extract_features, acoustic_score_from_features, final_score_v71,
    find_focus_window, phoneme_confidence_score
)
from speechcoach.utils_text import pedagogic_wer
from speechcoach.db import DataLayer
from speechcoach.config import DEFAULT_DB_PATH

def iter_jsonl(p: Path):
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if line:
                yield json.loads(line)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default="data/datasets/D2.1/items.jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--child-id", type=int, default=None,
                    help="Optionnel: active les profils acoustiques en DB")
    ap.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = ap.parse_args()

    asr = ASREngine()
    dl = DataLayer(args.db) if args.child_id else None

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)

    with outp.open("w", encoding="utf-8") as fo:
        for item in iter_jsonl(Path(args.items)):
            t0 = time.time()
            wav = item["wav"]
            expected = item["expected"]
            target_word = item.get("target_word", expected)

            try:
                rec_text, words = asr.transcribe_words(wav)
                wer = pedagogic_wer(expected, rec_text)

                fs, fe = find_focus_window(words, target_word)
                feat = extract_features(wav, fs, fe)

                a_score = 0.0
                a_contrast = 0.0
                conf = 0.0

                if dl and item.get("phoneme_target"):
                    pt = item["phoneme_target"]
                    pc = item.get("phoneme_contrast", "")
                    ref_t = dl.load_reference_profile(args.child_id, pt, "target")
                    ref_c = dl.load_reference_profile(args.child_id, pc, "contrast") if pc else None
                    a_score = acoustic_score_from_features(feat, ref_t) if ref_t else 0.0
                    a_contrast = acoustic_score_from_features(feat, ref_c) if ref_c else 0.0
                    conf = phoneme_confidence_score(a_score, a_contrast)

                final = final_score_v71(wer, a_score)
                ok = True
                err = None
            except Exception as e:
                rec_text, words, wer, fs, fe, a_score, a_contrast, conf, final = "", [], 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
                ok = False
                err = str(e)

            row = {
                "id": item.get("id"),
                "wav": wav,
                "expected": expected,
                "recognized": rec_text,
                "wer": float(wer),
                "acoustic_score": float(a_score),
                "acoustic_contrast": float(a_contrast),
                "phoneme_confidence": float(conf),
                "final_score": float(final),
                "focus_start": float(fs),
                "focus_end": float(fe),
                "ok": ok,
                "error": err,
                "latency_ms": int((time.time() - t0) * 1000),
            }
            fo.write(json.dumps(row, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    main()
