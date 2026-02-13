import json
import os
import threading
import time
from enum import Enum
from typing import Callable, Optional

from .analysis import (
    acoustic_score_from_features,
    extract_features,
    final_score_v71,
    find_focus_window,
    phoneme_confidence_score,
)
from .utils_text import now_iso, pedagogic_wer
from .config import AUDIO_DIR


# ==========================================================
# STATE MACHINE
# ==========================================================

class GameState(Enum):
    IDLE = 0
    STARTING = 1
    PLAYING = 2
    LISTENING = 3
    ANALYZING = 4
    PAUSED = 5
    STOPPING = 6
    FINISHED = 7


# ==========================================================
# GAME CONTROLLER
# ==========================================================

class GameController:

    def __init__(
        self,
        stories,
        audio,
        asr,
        dl,
        ui_dispatch: Callable[[Callable[[], None]], None],
    ):
        self.stories = stories
        self.audio = audio
        self.asr = asr
        self.dl = dl
        self.ui_dispatch = ui_dispatch

        self.child_id: Optional[int] = None
        self.state = GameState.IDLE

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self.last_phrase: Optional[str] = None

        # End-of-session metadata (used by UI for rewards / UX)
        # Values: finished | stopped | error | idle
        self.last_end_reason: str = "idle"

        # UI callbacks
        self.on_status = None
        self.on_sentence = None
        self.on_analysis = None
        self.on_end = None

    # ==========================================================
    # PUBLIC API
    # ==========================================================

    def set_child(self, child_id: Optional[int]):
        self.child_id = child_id

    def start(self, rounds: int = 6):
        if self.state != GameState.IDLE:
            return

        if not self.child_id:
            raise ValueError("Aucun enfant sélectionné.")
        if not self.stories.stories:
            raise ValueError("Aucune story chargée.")
        if self.audio.input_device is None:
            raise ValueError("Aucun micro sélectionné.")

        self.state = GameState.STARTING
        self._stop_event.clear()
        self.last_end_reason = "idle"

        story = self.stories.pick()
        if story is None:
            raise ValueError("Impossible de sélectionner une story.")

        self._thread = threading.Thread(
            target=self._run,
            args=(story, int(rounds)),
            daemon=True
        )
        self._thread.start()

    def stop(self):
        if self.state in (GameState.IDLE, GameState.FINISHED):
            return
        self.state = GameState.STOPPING
        self._stop_event.set()

    def toggle_pause(self):
        if self.state == GameState.PAUSED:
            self.state = GameState.PLAYING
            self._status("▶️ Reprise")
        elif self.state in (GameState.PLAYING, GameState.LISTENING):
            self.state = GameState.PAUSED
            self._status("⏸️ Pause")

    def replay_last(self):
        if self.last_phrase:
            threading.Thread(
                target=lambda: self.audio.tts.speak(self.last_phrase),
                daemon=True
            ).start()

    # ==========================================================
    # CORE LOOP
    # ==========================================================

    def _run(self, story, rounds: int):

        try:
            self.state = GameState.PLAYING
            self._status("🎮 Session démarrée")

            if story.goal:
                self.audio.tts.speak(f"On s'entraîne : {story.goal}.")
                time.sleep(0.5)

            for i in range(rounds):

                if self._stop_event.is_set():
                    self.last_end_reason = "stopped"
                    break

                while self.state == GameState.PAUSED:
                    time.sleep(0.1)

                sent = story.sentences[i % len(story.sentences)]
                expected = sent.text
                self.last_phrase = expected

                # UI sentence
                self._dispatch(
                    lambda e=expected, k=i: self.on_sentence(
                        story.title, k + 1, rounds, e, sent.phoneme_target
                    )
                )

                # ---- TTS
                self._status("🔊 Écoute bien")
                self.audio.tts.speak(expected)
                time.sleep(0.4)

                # ---- RECORD
                self.state = GameState.LISTENING
                try:
                    # Kid-friendly prompt (serialized, no overlap)
                    self.audio.tts.say_child_prompt(style="warm", block=True)
                except Exception:
                    pass
                self._status("🎙️ Prêt ? Répète la phrase quand tu veux !")

                wav_path = os.path.join(
                    AUDIO_DIR,
                    f"{self.child_id}_{story.story_id}_{int(time.time())}_{i+1}.wav"
                )

                # ---- RECORD (robust)
                # Sur certains micros/drivers, le tout premier enregistrement peut être
                # trop court (stop_event, init stream, bruit). On retente une fois.
                dur, thr = 0.0, 0.0
                for attempt in range(2):
                    if self._stop_event.is_set():
                        break
                    cur_path = wav_path if attempt == 0 else wav_path.replace(".wav", f"_retry{attempt}.wav")
                    dur, thr = self.audio.record_until_silence_rms(
                        cur_path,
                        stop_event=self._stop_event
                    )
                    wav_path = cur_path
                    if dur >= 0.35:
                        break
                    # feedback + petit délai pour stabiliser
                    self._status("🎙️ Trop court, on recommence")
                    try:
                        self.audio.tts.speak("On recommence")
                    except Exception:
                        pass
                    time.sleep(0.2)

                if self._stop_event.is_set():
                    self.last_end_reason = "stopped"
                    break

                # Still too short after retries: skip this turn to avoid polluting DB/TDB
                if dur < 0.35:
                    self._status("⚠️ Enregistrement trop court")
                    try:
                        self.audio.tts.speak("Je n'ai pas bien entendu. On passe au suivant.")
                    except Exception:
                        pass
                    time.sleep(0.3)
                    continue

                # ---- ASR
                self.state = GameState.ANALYZING
                self._status("🧠 Analyse en cours")

                rec_text, words = self.asr.transcribe_words(wav_path)
                w = pedagogic_wer(expected, rec_text)

                fs, fe = find_focus_window(words, sent.target_word)
                feat = extract_features(wav_path, fs, fe)

                ref_target = self.dl.load_reference_profile(
                    self.child_id, sent.phoneme_target, "target"
                )
                ref_contrast = self.dl.load_reference_profile(
                    self.child_id, sent.phoneme_contrast, "contrast"
                )

                a_score = acoustic_score_from_features(feat, ref_target) if ref_target else 0.0
                a_contrast = acoustic_score_from_features(feat, ref_contrast) if ref_contrast else 0.0
                conf = phoneme_confidence_score(a_score, a_contrast)
                final = final_score_v71(w, a_score)

                self.dl.save_session({
                    "created_at": now_iso(),
                    "child_id": self.child_id,
                    "story_id": story.story_id,
                    "story_title": story.title,
                    "goal": story.goal,
                    "sentence_index": i,
                    "expected_text": expected,
                    "recognized_text": rec_text,
                    "wer": w,
                    "audio_path": wav_path,
                    "duration_sec": dur,
                    "phoneme_target": sent.phoneme_target,
                    "spectral_centroid_hz": feat.get("centroid", 0.0),
                    "phoneme_quality": a_score,
                    "features_json": json.dumps(feat, ensure_ascii=False),
                    "acoustic_score": a_score,
                    "acoustic_contrast": a_contrast,
                    "final_score": final,
                    "phoneme_confidence": conf,
                    "focus_start_sec": fs,
                    "focus_end_sec": fe,
                })

                # UI analysis
                self._dispatch(lambda: self.on_analysis({
                    "wer": w,
                    "acoustic_score": a_score,
                    "acoustic_contrast": a_contrast,
                    "phoneme_confidence": conf,
                    "final_score": final,
                    "focus_window": f"{fs:.2f}s → {fe:.2f}s",
                    "recognized_text": rec_text,
                }))

                self._status(f"✅ Tour {i+1}/{rounds} terminé")
                time.sleep(0.8)

            # If we reached here without an explicit stop, it is a normal completion.
            if self.last_end_reason != "stopped":
                self.last_end_reason = "finished"

            self.state = GameState.FINISHED
            self._status("🎉 Fin du jeu")
            self.audio.tts.speak("Bravo ! Tu as fini. Super travail !")

        except Exception as e:
            self.last_end_reason = "error"
            self._status(f"❌ Erreur: {e}")

        finally:
            self.state = GameState.IDLE
            if self.on_end:
                self._dispatch(self.on_end)

    # ==========================================================
    # UTILS
    # ==========================================================

    def _dispatch(self, fn):
        if fn:
            self.ui_dispatch(fn)

    def _status(self, text: str):
        if self.on_status:
            self._dispatch(lambda: self.on_status(text))