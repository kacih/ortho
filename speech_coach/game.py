import json
import os
import threading
import time
from typing import Any, Callable, Dict, Optional

from .analysis import (
    acoustic_score_from_features,
    extract_features,
    final_score_v71,
    find_focus_window,
    phoneme_confidence_score,
)
from .db import DataLayer
from .stories import StoryEngine
from .audio import AudioEngine
from .asr import ASREngine
from .utils_text import now_iso, pedagogic_wer
from .config import AUDIO_DIR

class GameController:
    """
    Session runner.
    Important: UI must call this via callbacks (thread-safe with ui_dispatch).
    """
    def __init__(
        self,
        stories: StoryEngine,
        audio: AudioEngine,
        asr: ASREngine,
        dl: DataLayer,
        ui_dispatch: Callable[[Callable[[], None]], None],
    ):
        self.stories = stories
        self.audio = audio
        self.asr = asr
        self.dl = dl
        self.ui_dispatch = ui_dispatch

        self.child_id: Optional[int] = None
        self.running = False
        self.paused = False

        self.last_phrase: Optional[str] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # callbacks called via ui_dispatch
        self.on_status = None
        self.on_sentence = None
        self.on_analysis = None
        self.on_end = None

    def set_child(self, child_id: Optional[int]):
        self.child_id = child_id

    def start(self, rounds: int = 6):
        if self.running:
            return
        if not self.child_id:
            raise ValueError("Aucun enfant sélectionné.")
        if not self.stories.stories:
            raise ValueError("Aucune story chargée.")
        if self.audio.input_device is None:
            raise ValueError("Aucun micro sélectionné.")

        self.running = True
        self.paused = False
        self._stop_event.clear()

        story = self.stories.pick()
        if story is None:
            raise ValueError("Impossible de sélectionner une story.")

        self._thread = threading.Thread(target=self._run, args=(story, int(rounds)), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self.running = False
        self.paused = False

    def toggle_pause(self):
        if not self.running:
            return
        self.paused = not self.paused
        if self.on_status:
            self.ui_dispatch(lambda: self.on_status("⏸️ Pause" if self.paused else "▶️ Reprise"))

    def replay_last(self):
        if not self.last_phrase:
            return
        threading.Thread(target=lambda: self.audio.tts.speak(self.last_phrase), daemon=True).start()

    def _wait_if_paused(self):
        while self.running and self.paused and not self._stop_event.is_set():
            time.sleep(0.1)

    def _run(self, story, rounds: int):
        try:
            if self.on_status:
                self.ui_dispatch(lambda: self.on_status("Démarrage session…"))

            if story.goal:
                threading.Thread(target=lambda: self.audio.tts.speak(f"On s'entraîne : {story.goal}."), daemon=True).start()

            for k in range(rounds):
                if self._stop_event.is_set():
                    break
                self._wait_if_paused()

                sent = story.sentences[k % max(1, len(story.sentences))]
                expected = sent.text
                self.last_phrase = expected

                if self.on_sentence:
                    self.ui_dispatch(lambda e=expected, kk=k: self.on_sentence(story.title, kk+1, rounds, e, sent.phoneme_target))

                # TTS
                if self.on_status:
                    self.ui_dispatch(lambda: self.on_status("Écoute bien…"))
                self.audio.tts.speak(expected)

                # Record
                if self.on_status:
                    self.ui_dispatch(lambda: self.on_status("🎙️ À toi !"))
                wav_path = os.path.join(AUDIO_DIR, f"{self.child_id}_{story.story_id}_{int(time.time())}_{k+1}.wav")
                dur, thr = self.audio.record_until_silence_rms(wav_path, stop_event=self._stop_event)

                if self._stop_event.is_set():
                    break

                # ASR
                if self.on_status:
                    self.ui_dispatch(lambda: self.on_status("🧠 Analyse…"))
                rec_text, words = self.asr.transcribe_words(wav_path)
                w = pedagogic_wer(expected, rec_text)

                fs, fe = find_focus_window(words, sent.target_word)
                feat = extract_features(wav_path, fs, fe)
                centroid = float(feat.get("centroid", 0.0) or 0.0)

                ref_target = self.dl.load_reference_profile(self.child_id, sent.phoneme_target, "target") \
                    or self.dl.load_reference_profile(None, sent.phoneme_target, "target")
                ref_contrast = self.dl.load_reference_profile(self.child_id, sent.phoneme_contrast, "contrast") \
                    or self.dl.load_reference_profile(None, sent.phoneme_contrast, "contrast")

                a_score = acoustic_score_from_features(feat, ref_target) if ref_target else 0.0
                a_contrast = acoustic_score_from_features(feat, ref_contrast) if ref_contrast else 0.0
                conf = phoneme_confidence_score(a_score, a_contrast)
                final = final_score_v71(w, a_score)

                sess = {
                    "created_at": now_iso(),
                    "child_id": self.child_id,
                    "story_id": story.story_id,
                    "story_title": story.title,
                    "goal": story.goal,
                    "sentence_index": k,
                    "expected_text": expected,
                    "recognized_text": rec_text,
                    "wer": w,
                    "audio_path": wav_path,
                    "duration_sec": dur,
                    "phoneme_target": sent.phoneme_target,
                    "spectral_centroid_hz": centroid,
                    "phoneme_quality": a_score,
                    "features_json": json.dumps(feat, ensure_ascii=False),
                    "acoustic_score": a_score,
                    "acoustic_contrast": a_contrast,
                    "final_score": final,
                    "phoneme_confidence": conf,
                    "focus_start_sec": fs,
                    "focus_end_sec": fe,
                }
                self.dl.save_session(sess)

                if self.on_analysis:
                    self.ui_dispatch(lambda: self.on_analysis({
                        "wer": w, "wer_note": "",
                        "acoustic_score": a_score, "acoustic_note": "",
                        "acoustic_contrast": a_contrast, "contrast_note": "",
                        "phoneme_confidence": conf, "conf_note": "",
                        "final_score": final, "final_note": "",
                        "focus_window": f"{fs:.2f}s → {fe:.2f}s", "focus_note": f"thr={thr:.3f}",
                        "recognized_text": rec_text,
                    }))

                if self.on_status:
                    self.ui_dispatch(lambda kk=k: self.on_status(f"✅ Tour {kk+1}/{rounds} terminé"))

            if self.on_status:
                self.ui_dispatch(lambda: self.on_status("🎉 Fin du jeu"))
            self.audio.tts.speak("Bravo ! Tu as fini. Super travail !")

        finally:
            self.running = False
            self.paused = False
            if self.on_end:
                self.ui_dispatch(self.on_end)
