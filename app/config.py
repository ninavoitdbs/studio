"""Réglages du Studio, lus dans l'environnement (fichier ~/.config/studio/env sur le serveur)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("STUDIO_DATA_DIR", ROOT / "data"))
BRAIN_DIR = Path(os.environ.get("STUDIO_BRAIN_DIR", ROOT / "brain"))
STATIC_DIR = ROOT / "static"

# Accès équipe : un code commun + le prénom de chacun
TEAM_CODE = os.environ.get("TEAM_CODE", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "")

# Claude (Claude Code en mode non interactif, connecté au compte de Nina)
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", str(Path.home() / ".local/bin/claude"))
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "opus")
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "600"))
# Dossier de l'Encyclopédie, pour aller chercher anecdotes et positions de Nina (facultatif)
ENCYCLOPEDIE_DIR = os.environ.get("ENCYCLOPEDIE_DIR", str(Path.home() / "encyclopedie/corpus"))

# Transcription locale
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")

# Récupération des contenus : Apify en secours quand yt-dlp n'y arrive pas (carrousels, posts photo)
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
# Cookies Instagram/Facebook au format Netscape (facultatif, aide yt-dlp)
COOKIES_FILE = os.environ.get("COOKIES_FILE", "")

# Slack : jeton du bot + destinations « Nom|ID;Nom|ID »
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_DESTINATIONS = os.environ.get("SLACK_DESTINATIONS", "")

PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "300"))
WORKERS = int(os.environ.get("STUDIO_WORKERS", "2"))


def slack_destinations() -> list[dict]:
    out = []
    for part in SLACK_DESTINATIONS.split(";"):
        if "|" in part:
            name, dest = part.split("|", 1)
            out.append({"name": name.strip(), "id": dest.strip()})
    return out


# --- Réglages modifiables depuis l'interface (page Réglages), gardés dans data/settings.json ---
import json as _json

SETTINGS_FILE = DATA_DIR / "settings.json"


def _settings() -> dict:
    try:
        return _json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_setting(key: str, value: str) -> None:
    data = _settings()
    if value:
        data[key] = value
    else:
        data.pop(key, None)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(_json.dumps(data), encoding="utf-8")
    try:
        os.chmod(SETTINGS_FILE, 0o600)
    except OSError:
        pass


def apify_token() -> str:
    """Clé Apify : celle collée dans l'interface d'abord, sinon celle du fichier env."""
    return _settings().get("apify_token") or APIFY_TOKEN
