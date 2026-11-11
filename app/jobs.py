"""File de travail : récupérer, écouter, écrire. Tourne en arrière-plan dans le serveur."""
import json
import logging
import re
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, db, fetch, llm, media, prompts

log = logging.getLogger("studio.jobs")
executor = ThreadPoolExecutor(max_workers=config.WORKERS)

ACTIVE = ("queued", "fetching", "transcribing", "writing")
FORMAT_KINDS = {"reel", "carrousel", "post", "linkedin", "youtube", "email"}


def item_dir(iid: str) -> Path:
    d = config.DATA_DIR / "items" / iid
    d.mkdir(parents=True, exist_ok=True)
    return d


def submit_create(iid: str):
    executor.submit(_guard, _process_item, iid)


def submit_action(iid: str, mid: str, action: str, request: dict):
    executor.submit(_guard_action, iid, mid, action, request)


def resume_interrupted():
    """Au redémarrage : relance les contenus en cours et clôt les réponses restées en suspens."""
    for it in db.query(f"SELECT id FROM items WHERE status IN ({','.join('?' * len(ACTIVE))})", ACTIVE):
        submit_create(it["id"])
    db.execute("UPDATE messages SET status='error', content='Interrompu par un redémarrage du serveur. Relance la demande.' "
               "WHERE status='pending'")


def _guard(fn, iid):
    try:
        fn(iid)
    except Exception as e:
        log.error("item %s : %s", iid, traceback.format_exc())
        msg = str(e) if isinstance(e, (fetch.FetchError, llm.LLMError)) else f"Erreur inattendue : {e}"
        db.update_item(iid, status="error", error=msg, progress=None)


def _guard_action(iid, mid, action, request):
    try:
        _process_action(iid, mid, action, request)
    except Exception as e:
        log.error("action %s/%s : %s", iid, mid, traceback.format_exc())
        msg = str(e) if isinstance(e, llm.LLMError) else f"Erreur inattendue : {e}"
        db.update_message(mid, status="error", content=msg)


def guess_formats(target: str, src: dict) -> list[str]:
    if target and target != "auto":
        return [target]
    kind, plat = src.get("kind"), src.get("platform")
    if plat == "youtube" or kind == "youtube":
        return ["youtube"]
    if kind == "video":
        return ["reel"]
    if kind == "carrousel":
        return ["carrousel"]
    if plat == "linkedin":
        return ["linkedin"]
    if src.get("text") and not src.get("images"):
        return ["email", "post", "reel"]
    return ["post", "reel"]


def _parse_output(out: str) -> tuple[str, dict | None]:
    """Livrable propre (sans ligne « Reel : » ni note) + note éventuelle à part."""
    livrable = llm.tag(out, "livrable") or out.strip()
    livrable = re.sub(r"<note>.*$", "", livrable, flags=re.S).strip()
    livrable = re.sub(r"^\s*(Reel|Réel|Pub)\s*:[^\n]*\n+", "", livrable, flags=re.I)
    note = llm.tag(out, "note")
    return livrable, ({"note": note} if note else None)


def _process_item(iid: str):
    item = db.get_item(iid)
    work = item_dir(iid)
    db.update_item(iid, status="fetching", progress="Je récupère le contenu…", error=None)

    src: dict = {"url": item.get("source_url") or "", "platform": None, "kind": None, "videos": [], "audios": [],
                 "images": [], "caption": "", "text": "", "notes": []}
    uploads = sorted((work / "uploads").glob("*")) if (work / "uploads").is_dir() else []
    if item.get("source_url"):
        try:
            src = fetch.fetch_url(item["source_url"], work)
        except fetch.FetchError:
            if not uploads and not item.get("source_text"):
                raise
            src["notes"].append("lien non récupéré, on travaille avec les fichiers / le texte fournis")
    for f in uploads:
        kind = fetch.classify_upload(f.name)
        rel = f"uploads/{f.name}"
        if kind == "video":
            src["videos"].append(rel)
        elif kind == "audio":
            src["audios"].append(rel)
        elif kind == "image":
            src["images"].append(rel)
    if item.get("source_text"):
        src["text"] = ((src.get("text") or "") + "\n\n" + item["source_text"]).strip()
    if not src.get("platform"):
        src["platform"] = "fichier" if uploads else "texte"
    if not src.get("kind") or uploads:
        src["kind"] = ("video" if src["videos"] else "carrousel" if len(src["images"]) > 1
                       else "image" if src["images"] else "texte")
    if not (src["videos"] or src["audios"] or src["images"] or src.get("caption") or src.get("text") or src.get("subtitles")):
        raise fetch.FetchError("Il me faut un lien, un texte ou des fichiers pour travailler.")

    # Écoute : transcription + planches de captures pour les vidéos courtes
    src["transcripts"], src["sheets"] = [], []
    to_listen = [(v, True) for v in src["videos"][:3]] + [(a, False) for a in src["audios"][:2]]
    for i, (rel, is_video) in enumerate(to_listen, 1):
        path = work / rel
        dur = media.duration_seconds(path) or 0
        mins = f" ({int(dur // 60)} min)" if dur > 120 else ""
        db.update_item(iid, status="transcribing", progress=f"J'écoute{mins}…")
        if media.has_audio(path):
            text, lang = media.transcribe(path)
            src["transcripts"].append({"file": rel, "lang": lang, "text": text})
        if is_video and dur <= 15 * 60:
            sheet_dir = work / f"planches_{i}"
            sheet_dir.mkdir(exist_ok=True)
            src["sheets"] += [f"{sheet_dir.name}/{p.name}" for p in media.contact_sheets(path, sheet_dir)]
        if dur and not src.get("duration"):
            src["duration"] = dur

    db.update_item(iid, status="writing", progress="J'écris…", platform=src.get("platform"),
                   source_json=json.dumps(src, ensure_ascii=False))
    item = db.get_item(iid)
    formats = guess_formats(item.get("target_format"), src)
    out = llm.run(prompts.system_prompt(formats), prompts.create_prompt(item, src), work,
                  add_dirs=[str(config.BRAIN_DIR), config.ENCYCLOPEDIE_DIR])
    livrable, meta = _parse_output(out)
    fmt = llm.tag(out, "format").split("|")[0].strip().lower() or formats[0]
    if fmt not in FORMAT_KINDS:
        fmt = formats[0]
    db.add_message(iid, "Studio", "assistant", fmt, livrable, meta=meta)
    db.update_item(iid, status="ready", progress=None, title=llm.tag(out, "titre")[:120] or None,
                   analysis=llm.tag(out, "analyse"), output_format=fmt)


def _process_action(iid: str, mid: str, action: str, request: dict):
    item = db.get_item(iid)
    work = item_dir(iid)
    src = json.loads(item.get("source_json") or "{}")
    thread = [m for m in db.messages_for(iid) if m["id"] != mid]
    formats = [item.get("output_format") or "reel"]
    if action == "caption":
        formats.append(request.get("platform") or "instagram")
    elif action == "format":
        formats = [request.get("format") or "reel"]
    out = llm.run(prompts.system_prompt(formats), prompts.followup_prompt(item, src, thread, action, request), work,
                  add_dirs=[str(config.BRAIN_DIR), config.ENCYCLOPEDIE_DIR])
    kind = llm.tag(out, "type").split("|")[0].strip().lower() or "version"
    if action == "format":
        kind = request.get("format") or "reel"
        db.update_item(iid, output_format=kind)
    elif action == "comment" and kind not in ("reponse", "accroches", "legende"):
        kind = "version"
    livrable, meta = _parse_output(out)
    db.update_message(mid, status="done", kind=kind, content=livrable, meta=meta)
