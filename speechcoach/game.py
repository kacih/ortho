import json
import os
import threading
import time
import logging
import random
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
# LOGGING
# ==========================================================

logger = logging.getLogger(__name__)

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
        self._paused_prev_state = GameState.PLAYING

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self.last_phrase: Optional[str] = None
        self.last_final_score: float = 0.0

        # Current session plan (Sprint 1: pacing + metadata)
        self.session_plan = None

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

    def start(self, rounds: int = 6, plan=None):
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

        # Sprint 1: attach optional session plan (pacing + DB metadata)
        self.session_plan = plan
        if plan is not None and getattr(plan, "rounds", None):
            rounds = int(plan.rounds)

        story = self.stories.pick()
        if story is None:
            raise ValueError("Impossible de sélectionner une story.")

        self._thread = threading.Thread(
            target=self._run,
            args=(story, int(rounds), plan),
            daemon=True
        )
        self._thread.start()

    def stop(self):
        if self.state in (GameState.IDLE, GameState.FINISHED):
            return
        self.state = GameState.STOPPING
        self._stop_event.set()

    def toggle_pause(self):
        # Keep track of the previous active state so resume returns to the right phase.
        if self.state == GameState.PAUSED:
            self.state = getattr(self, '_paused_prev_state', GameState.PLAYING) or GameState.PLAYING
            self._status("▶️ Reprise")
        elif self.state in (GameState.PLAYING, GameState.LISTENING, GameState.ANALYZING):
            self._paused_prev_state = self.state
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

    def _build_turn_sequence(self, story, rounds: int, plan=None):
        """Return a list of sentence indices for warm-up/core/cool-down (Sprint 1).

        Heuristic for difficulty (Sprint 1): shorter sentences are treated as easier.
        """
        n_sent = len(getattr(story, "sentences", []) or [])
        if n_sent <= 0 or rounds <= 0:
            return []

        # Sentence difficulty proxy: length of text
        idxs = list(range(n_sent))
        idxs_sorted = sorted(idxs, key=lambda j: len((story.sentences[j].text or "")))

        if plan is None:
            # default behavior close to v7.15.1
            return [i % n_sent for i in range(rounds)]

        try:
            warm_n = max(1, int(rounds * float(getattr(plan, "warmup_ratio", 0.0) or 0.0)))
        except Exception:
            warm_n = 0
        try:
            cool_n = max(1, int(rounds * float(getattr(plan, "cooldown_ratio", 0.0) or 0.0)))
        except Exception:
            cool_n = 0

        # Ensure totals make sense
        if warm_n + cool_n >= rounds:
            warm_n = max(1, rounds // 3)
            cool_n = max(1, rounds // 3)
        core_n = max(0, rounds - warm_n - cool_n)

        warmup = [idxs_sorted[i % n_sent] for i in range(warm_n)]
        cooldown = [idxs_sorted[i % n_sent] for i in range(cool_n)]

        # Core: biased random (avoid repeating the same sentence too much)
        core = []
        last = None
        for _ in range(core_n):
            cand = random.choice(idxs)
            if last is not None and n_sent > 1:
                for _k in range(3):
                    if cand != last:
                        break
                    cand = random.choice(idxs)
            core.append(cand)
            last = cand

        return warmup + core + cooldown

    def _run(self, story, rounds: int, plan=None):

        try:
            self.state = GameState.PLAYING
            self._status("🎮 Session démarrée")

            if story.goal:
                self.audio.tts.speak(f"On s'entraîne : {story.goal}.")
                time.sleep(0.5)

            seq = self._build_turn_sequence(story, rounds, plan)
            total = len(seq)
            # Minimal adaptation counters (repeat-on-fail)
            repeats = {}

            # Sprint 2: session-run summary
            run_id = None
            try:
                if plan is not None and self.child_id is not None:
                    run_id = self.dl.create_session_run(
                        child_id=int(self.child_id),
                        plan=getattr(plan, "to_json_dict", lambda: {})(),
                        planned_items=int(total),
                    )
            except Exception:
                run_id = None

            # Sprint 2: fatigue detection (very simple heuristics)
            recent_scores = []
            recent_durations = []
            ended_early = False
            completed_items = 0

            for i, sent_idx in enumerate(seq):

                if self._stop_event.is_set():
                    self.last_end_reason = "stopped"
                    break

                while self.state == GameState.PAUSED:
                    time.sleep(0.1)

                sent = story.sentences[sent_idx % len(story.sentences)]
                expected = sent.text
                self.last_phrase = expected

                # UI sentence
                self._dispatch(
                    lambda e=expected, k=i: self.on_sentence(
                        story.title, k + 1, total, e, sent.phoneme_target
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
                try:
                    self.last_final_score = float(final)
                except Exception:
                    self.last_final_score = 0.0
                # Sprint 1: minimal adaptation (repeat once if hard)
                try:
                    if (plan is not None
                        and getattr(plan, "repeat_on_fail", False)
                        and float(final or 0.0) < 0.45
                        and i + 1 < total):
                        used = int(repeats.get(sent_idx, 0))
                        max_r = int(getattr(plan, "max_repeats_per_sentence", 0) or 0)
                        if used < max_r:
                            repeats[sent_idx] = used + 1
                            # Replace the next planned turn with the same sentence (keeps total duration stable)
                            seq[i + 1] = sent_idx
                            self._status("🔁 On la refait une fois")
                except Exception:
                    pass


                self.dl.save_session({
                    "created_at": now_iso(),
                    "child_id": self.child_id,
                    "story_id": story.story_id,
                    "story_title": story.title,
                    "goal": story.goal,
                    "plan_id": getattr(plan, "plan_id", None),
                    "plan_name": getattr(plan, "name", None),
                    "plan_mode": getattr(plan, "mode", None),
                    "plan_json": json.dumps(getattr(plan, "to_json_dict", lambda: {})(), ensure_ascii=False) if plan else None,
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

                completed_items += 1
                try:
                    recent_scores.append(float(final))
                    recent_durations.append(float(dur))
                    if len(recent_scores) > 4:
                        recent_scores = recent_scores[-4:]
                    if len(recent_durations) > 4:
                        recent_durations = recent_durations[-4:]
                except Exception:
                    pass

                # Sprint 2: detect fatigue -> finish with short cooldown and stop early
                try:
                    if plan is not None and not ended_early and len(recent_scores) >= 4:
                        first2 = (recent_scores[0] + recent_scores[1]) / 2.0
                        last2 = (recent_scores[2] + recent_scores[3]) / 2.0
                        d_first2 = (recent_durations[0] + recent_durations[1]) / 2.0
                        d_last2 = (recent_durations[2] + recent_durations[3]) / 2.0
                        failures = sum(1 for s in recent_scores if s < 0.45)

                        if (failures >= 3) or ((last2 < first2 - 0.15) and (d_last2 > d_first2 * 1.2)):
                            ended_early = True
                            self.last_end_reason = "fatigue"
                            self._status("😮‍💨 On ralentit et on termine tranquillement…")

                            # Run a short cooldown (easiest sentences)
                            n_sent = len(getattr(story, "sentences", []) or [])
                            if n_sent > 0:
                                idxs = list(range(n_sent))
                                idxs_sorted = sorted(idxs, key=lambda j: len((story.sentences[j].text or "")))
                                cool_seq = [idxs_sorted[k % n_sent] for k in range(min(3, n_sent))]

                                for _cs in cool_seq:
                                    if self._stop_event.is_set():
                                        break
                                    sent2 = story.sentences[_cs % n_sent]
                                    self._status(f"✅ Dernière phrase : {sent2.text}")
                                    wav2 = self.audio.record_and_playback(sent2.text)
                                    rec2, w2, dur2 = self.asr.recognize_wav(wav2, expected_text=sent2.text)
                                    # We store it as a regular session row as well
                                    try:
                                        self.dl.save_session({
                                            "created_at": now_iso(),
                                            "child_id": self.child_id,
                                            "story_id": story.story_id,
                                            "story_title": story.title,
                                            "goal": story.goal,
                                            "plan_id": getattr(plan, "plan_id", None),
                                            "plan_name": getattr(plan, "name", None),
                                            "plan_mode": getattr(plan, "mode", None),
                                            "plan_json": json.dumps(getattr(plan, "to_json_dict", lambda: {})(), ensure_ascii=False) if plan else None,
                                            "sentence_index": i,
                                            "expected_text": sent2.text,
                                            "recognized_text": rec2 or "",
                                            "wer": w2,
                                            "audio_path": wav2,
                                            "duration_sec": dur2,
                                            "phoneme_target": getattr(sent2, "phoneme_target", "") or "",
                                            "spectral_centroid_hz": None,
                                            "phoneme_quality": None,
                                            "features_json": None,
                                            "acoustic_score": None,
                                            "acoustic_contrast": None,
                                            "final_score": None,
                                            "phoneme_confidence": None,
                                            "focus_start_sec": None,
                                            "focus_end_sec": None,
                                        })
                                        completed_items += 1
                                    except Exception:
                                        pass
                            break
                except Exception:
                    pass


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

                self._status(f"✅ Tour {i+1}/{total} terminé")
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
            try:
                if run_id is not None:
                    self.dl.finish_session_run(run_id, completed_items=int(locals().get('completed_items', 0) or 0), ended_early=bool(locals().get('ended_early', False)), reason=str(self.last_end_reason or ''))
            except Exception:
                pass
            self.state = GameState.IDLE
        self._paused_prev_state = GameState.PLAYING
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