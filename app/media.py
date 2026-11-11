"""Audio et images : transcription (faster-whisper, sur le serveur) et planches de captures d'une vidéo."""
import re
import subprocess
import threading
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np

from . import config

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

_model = None
_model_lock = threading.Lock()
_run_lock = threading.Lock()


def _whisper():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def duration_seconds(path: Path) -> float | None:
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def has_audio(path: Path) -> bool:
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    return "Audio:" in r.stderr


def to_wav(src: Path, dst: Path) -> Path:
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
                    "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(dst)], check=True)
    return dst


def transcribe(src: Path, language: str | None = None, timestamps: bool = True) -> tuple[str, str]:
    """Renvoie (texte, langue détectée). On passe par un wav lu avec numpy pour éviter les soucis de PyAV."""
    wav_path = to_wav(src, src.with_suffix(".16k.wav"))
    with wave.open(str(wav_path), "rb") as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    wav_path.unlink(missing_ok=True)
    if audio.size < 1600:
        return "", language or ""
    with _run_lock:
        segments, info = _whisper().transcribe(audio, language=language, vad_filter=True, beam_size=5)
        lines = []
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            if timestamps:
                m, s = divmod(int(seg.start), 60)
                lines.append(f"[{m:02d}:{s:02d}] {text}")
            else:
                lines.append(text)
    return ("\n".join(lines) if timestamps else " ".join(lines)), info.language


def contact_sheets(video: Path, out_dir: Path, max_frames: int = 12, per_sheet: int = 6) -> list[Path]:
    """Planches de captures (3 x 2) régulièrement espacées, pour lire le texte à l'écran et le format visuel."""
    dur = duration_seconds(video) or 30
    interval = max(1.5, dur / max_frames)
    sheets = max(1, min(max_frames // per_sheet, int(dur / interval / per_sheet + 0.999)))
    pattern = out_dir / "planche_%02d.jpg"
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
                    "-vf", f"fps=1/{interval:.2f},scale=420:-2,tile=3x2:padding=6:color=white",
                    "-frames:v", str(sheets), "-q:v", "3", str(pattern)], check=False)
    return sorted(out_dir.glob("planche_*.jpg"))
