from dataclasses import dataclass
from typing import List

@dataclass
class StorySentence:
    text: str
    target_word: str = ""
    phoneme_target: str = ""
    phoneme_contrast: str = ""

@dataclass
class Story:
    story_id: str
    title: str
    goal: str = ""
    tags: List[str] = None
    weight: float = 1.0
    sentences: List[StorySentence] = None
