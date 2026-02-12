from datetime import datetime

try:
    from jiwer import wer as jiwer_wer
except Exception:
    jiwer_wer = None

def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def normalize_text_fr(s: str) -> str:
    if not s:
        return ""
    s = s.lower().strip()
    repl = {
        "’": "'",
        "œ": "oe",
        "æ": "ae",
        "-": " ",
        ",": " ",
        ";": " ",
        ":": " ",
        "!": " ",
        "?": " ",
        ".": " ",
        "…": " ",
    }
    for k, v in repl.items():
        s = s.replace(k, v)
    return " ".join(s.split())

def pedagogic_wer(expected: str, recognized: str) -> float:
    exp = normalize_text_fr(expected)
    rec = normalize_text_fr(recognized)
    if not exp and not rec:
        return 0.0
    if jiwer_wer is None:
        return 1.0 if exp != rec else 0.0
    return float(jiwer_wer(exp, rec))
