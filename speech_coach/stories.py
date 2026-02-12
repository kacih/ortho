import json
import os
import random
from collections import Counter, deque
from typing import List, Optional

from .models import Story, StorySentence

class StoryEngine:
    """Charge stories.json + sélection pondérée avec anti-répétition."""
    def __init__(self, stories_path: str):
        self.path = stories_path
        self.stories: List[Story] = []
        self.recent_story_ids = deque(maxlen=8)
        self.recent_phonemes = deque(maxlen=12)

    def load(self) -> int:
        self.stories = []
        if not self.path or not os.path.exists(self.path):
            return 0
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_items = data.get("stories", []) if isinstance(data, dict) else data if isinstance(data, list) else []
        for item in raw_items:
            st = self._coerce_story(item)
            if st:
                self.stories.append(st)
        return len(self.stories)

    def _coerce_story(self, item: dict) -> Optional[Story]:
        if not isinstance(item, dict):
            return None

        raw_sentences = item.get("sentences", [])
        if not isinstance(raw_sentences, list) or not raw_sentences:
            return None

        tgt_list = item.get("target_phonemes", [])
        ctr_list = item.get("contrast_phonemes", [])

        phoneme_target = str(tgt_list[0]).strip() if isinstance(tgt_list, list) and tgt_list else ""
        phoneme_contrast = str(ctr_list[0]).strip() if isinstance(ctr_list, list) and ctr_list else ""

        sentences: List[StorySentence] = []
        for s in raw_sentences:
            if isinstance(s, str):
                txt = s.strip()
                if txt:
                    sentences.append(StorySentence(txt, "", phoneme_target, phoneme_contrast))
            elif isinstance(s, dict):
                txt = (s.get("text") or "").strip()
                if not txt:
                    continue
                sentences.append(StorySentence(
                    text=txt,
                    target_word=(s.get("target_word") or "").strip(),
                    phoneme_target=(s.get("phoneme_target") or phoneme_target).strip(),
                    phoneme_contrast=(s.get("phoneme_contrast") or phoneme_contrast).strip(),
                ))

        if not sentences:
            return None

        sid = str(item.get("id") or item.get("story_id") or "").strip()
        if not sid:
            sid = f"story_{abs(hash(json.dumps(item, ensure_ascii=False)))%10_000_000}"

        return Story(
            story_id=sid,
            title=(item.get("title") or sid).strip(),
            goal=(item.get("goal") or "").strip(),
            tags=item.get("tags") if isinstance(item.get("tags"), list) else [],
            weight=float(item.get("weight", 1.0) or 1.0),
            sentences=sentences,
        )

    def _score_story(self, story: Story) -> float:
        w = max(0.05, float(story.weight))
        if story.story_id in self.recent_story_ids:
            w *= 0.25

        phon = (story.sentences[0].phoneme_target if story.sentences else "").upper()
        recent_counts = Counter([p.upper() for p in self.recent_phonemes if p])
        if phon:
            w *= (0.85 ** recent_counts.get(phon, 0))

        if phon in ("CH", "ʃ") and recent_counts.get(phon, 0) >= 2:
            w *= 0.6

        w *= random.uniform(0.80, 1.20)
        return max(0.01, w)

    def pick(self) -> Optional[Story]:
        if not self.stories:
            return None
        weights = [self._score_story(s) for s in self.stories]
        total = sum(weights)
        r = random.uniform(0, total) if total > 0 else 0.0
        acc = 0.0
        chosen = self.stories[-1]
        for st, w in zip(self.stories, weights):
            acc += w
            if acc >= r:
                chosen = st
                break
        self.recent_story_ids.append(chosen.story_id)
        phon = (chosen.sentences[0].phoneme_target if chosen.sentences else "")
        if phon:
            self.recent_phonemes.append(phon)
        return chosen
