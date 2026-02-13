import os

APP_NAME = "Speech Coach"
APP_VERSION = "7.10.4"

DEFAULT_SAMPLE_RATE = 16000

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
AUDIO_DIR = os.path.join(DATA_DIR, "audio_sessions")

DEFAULT_DB_PATH = os.path.join(DATA_DIR, "coach.db")

# stories.json: d'abord data/, sinon dossier projet
DEFAULT_STORIES_PATH = os.path.join(DATA_DIR, "stories.json")
FALLBACK_STORIES_PATH = os.path.join(PROJECT_ROOT, "stories.json")
