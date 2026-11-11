"""Studio du Bon Sens : serveur web (API + appli installable sur le téléphone)."""
import base64
import hashlib
import hmac
import json
import logging
import re
import shutil
import time

import httpx
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, fetch, jobs, media, slack

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
COOKIE = "studio_session"
COOKIE_AGE = 365 * 24 * 3600


@asynccontextmanager
async def lifespan(app):
    if not config.TEAM_CODE or not config.SECRET_KEY:
        raise RuntimeError("TEAM_CODE et SECRET_KEY doivent être définis (fichier env).")
    db.conn()
    jobs.resume_interrupted()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


# --- session : prénom signé dans un cookie ---

def _sign(value: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]


def make_session(name: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"n": name, "t": int(time.time())}).encode()).decode()
    return f"{payload}.{_sign(payload)}"


def read_session(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(payload))["n"]
    except Exception:
        return None


def user(request: Request) -> str:
    name = read_session(request.cookies.get(COOKIE))
    if not name:
        raise HTTPException(401, "Connecte-toi d'abord.")
    return name


_attempts: dict[str, list[float]] = {}


@app.post("/api/login")
def login(request: Request, name: str = Form(...), code: str = Form(...)):
    ip = request.client.host if request.client else "?"
    recent = [t for t in _attempts.get(ip, []) if time.time() - t < 600]
    if len(recent) >= 10:
        raise HTTPException(429, "Trop d'essais, attends 10 minutes.")
    name = re.sub(r"\s+", " ", name).strip()[:40]
    if not name or not hmac.compare_digest(code.strip().lower(), config.TEAM_CODE.strip().lower()):
        _attempts[ip] = recent + [time.time()]
        raise HTTPException(403, "Code d'équipe incorrect.")
    resp = JSONResponse({"name": name})
    resp.set_cookie(COOKIE, make_session(name), max_age=COOKIE_AGE, httponly=True, samesite="lax",
                    secure=config.PUBLIC_URL.startswith("https"))
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/api/me")
def me(name: str = Depends(user)):
    return {"name": name, "slack": [d["name"] for d in config.slack_destinations()] if config.SLACK_BOT_TOKEN else []}


# --- réglages (page Réglages de l'interface) ---

@app.get("/api/settings")
def get_settings(name: str = Depends(user)):
    tok = config.apify_token()
    return {"apify": bool(tok), "apify_end": tok[-4:] if tok else ""}


@app.post("/api/settings/apify")
async def set_apify(request: Request, name: str = Depends(user)):
    body = await request.json()
    token = re.sub(r"\s+", "", str(body.get("token", "")))
    if token:
        try:
            r = httpx.get("https://api.apify.com/v2/users/me", params={"token": token}, timeout=20)
        except Exception:
            raise HTTPException(502, "Apify ne répond pas, réessaie dans un moment.")
        if r.status_code != 200:
            raise HTTPException(400, "Apify refuse cette clé. Vérifie que tu l'as copiée en entier.")
    config.save_setting("apify_token", token)
    logging.getLogger("studio").info("Clé Apify %s par %s", "enregistrée" if token else "retirée", name)
    return get_settings(name)


# --- contenus ---

def _public_item(it: dict) -> dict:
    src = json.loads(it.get("source_json") or "{}")
    it = {k: v for k, v in it.items() if k != "source_json"}
    it["source"] = {k: src.get(k) for k in ("platform", "kind", "author", "caption", "notes", "duration")}
    it["source"]["has_transcript"] = bool(src.get("transcripts") or src.get("subtitles"))
    return it


@app.get("/api/items")
def items(q: str = "", mine: bool = False, name: str = Depends(user)):
    return db.list_items(q.strip(), author=name if mine else None)


def _save_uploads(files: list[UploadFile], dest: Path) -> list[str]:
    saved = []
    dest.mkdir(parents=True, exist_ok=True)
    for f in files or []:
        if not f or not f.filename:
            continue
        safe = re.sub(r"[^\w.\-]+", "_", Path(f.filename).name)[-80:] or "fichier"
        target = dest / f"{len(saved) + 1:02d}_{safe}"
        with open(target, "wb") as out:
            shutil.copyfileobj(f.file, out, length=1024 * 1024)
        if target.stat().st_size > config.MAX_UPLOAD_MB * 1024 * 1024:
            target.unlink()
            raise HTTPException(413, f"Fichier trop lourd (max {config.MAX_UPLOAD_MB} Mo).")
        saved.append(target.name)
    return saved


@app.post("/api/items")
def create_item(url: str = Form(""), text: str = Form(""), instructions: str = Form(""), format: str = Form("auto"),
                draft: str = Form(""), files: list[UploadFile] = File(default=[]), name: str = Depends(user)):
    url = url.strip()
    if url and not url.startswith("http"):
        url = fetch.extract_url(url) or ""
    if not url and text and fetch.extract_url(text) and len(text.strip()) < 300:
        url, text = fetch.extract_url(text), ""
    d = db.get_draft(draft) if draft else None
    if not (url or text.strip() or files or d):
        raise HTTPException(400, "Mets un lien, un texte ou des fichiers.")
    iid = db.create_item(name, url or None, text.strip() or None, instructions.strip() or None, format)
    up = jobs.item_dir(iid) / "uploads"
    _save_uploads(files, up)
    if d:
        draft_dir = config.DATA_DIR / "drafts" / d["id"]
        for f in json.loads(d["files_json"] or "[]"):
            if (draft_dir / f).exists():
                up.mkdir(parents=True, exist_ok=True)
                shutil.move(str(draft_dir / f), up / f)
    jobs.submit_create(iid)
    return {"id": iid}


@app.get("/api/items/{iid}")
def item(iid: str, name: str = Depends(user)):
    it = db.get_item(iid)
    if not it:
        raise HTTPException(404, "Introuvable.")
    out = _public_item(it)
    out["messages"] = [{**{k: m[k] for k in ("id", "created_at", "author", "role", "kind", "content", "status")},
                        "note": json.loads(m["meta_json"] or "{}").get("note")}
                       for m in db.messages_for(iid)]
    return out


@app.post("/api/items/{iid}/retry")
def retry(iid: str, name: str = Depends(user)):
    it = db.get_item(iid)
    if not it:
        raise HTTPException(404, "Introuvable.")
    if it["status"] in jobs.ACTIVE:
        return {"ok": True}
    db.update_item(iid, status="queued", progress="En attente…", error=None)
    jobs.submit_create(iid)
    return {"ok": True}


@app.post("/api/items/{iid}/archive")
def archive(iid: str, name: str = Depends(user)):
    db.update_item(iid, archived=1)
    return {"ok": True}


@app.post("/api/items/{iid}/actions")
async def action(iid: str, request: Request, name: str = Depends(user)):
    body = await request.json()
    act = body.get("action")
    it = db.get_item(iid)
    if not it:
        raise HTTPException(404, "Introuvable.")
    if it["status"] != "ready":
        raise HTTPException(409, "Attends que la première proposition soit prête.")
    if act not in ("comment", "version", "hooks", "caption", "format"):
        raise HTTPException(400, "Action inconnue.")
    labels = {"version": "Autre version, s'il te plaît.", "hooks": "Plusieurs accroches, s'il te plaît.",
              "caption": f"Une légende {str(body.get('platform', 'instagram')).capitalize()}, s'il te plaît.",
              "format": f"Transforme-le en {body.get('format_label') or body.get('format')}, s'il te plaît."}
    text = (body.get("text") or "").strip() if act == "comment" else labels[act]
    if act == "comment" and not text:
        raise HTTPException(400, "Écris ou dicte ton commentaire.")
    db.add_message(iid, name, "user", "comment", text)
    mid = db.add_message(iid, "Studio", "assistant", "pending", "", status="pending")
    jobs.submit_action(iid, mid, act, {"author": name, "text": text, "platform": body.get("platform"),
                                       "format": body.get("format")})
    return {"ok": True, "message_id": mid}


@app.post("/api/items/{iid}/slack")
async def share_slack(iid: str, request: Request, name: str = Depends(user)):
    body = await request.json()
    it = db.get_item(iid)
    msg = db.get_message(body.get("message_id", ""))
    dest = next((d for d in config.slack_destinations() if d["name"] == body.get("destination")), None)
    if not it or not msg or msg["item_id"] != iid:
        raise HTTPException(404, "Introuvable.")
    if not dest:
        raise HTTPException(400, "Destination Slack inconnue.")
    try:
        slack.post(dest["id"], slack.format_message(it, msg, name))
    except slack.SlackError as e:
        raise HTTPException(502, str(e))
    return {"ok": True}


@app.post("/api/dictate")
def dictate(audio: UploadFile = File(...), name: str = Depends(user)):
    tmp = config.DATA_DIR / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / f"dictee_{int(time.time() * 1000)}.webm"
    with open(path, "wb") as out:
        shutil.copyfileobj(audio.file, out)
    try:
        text, _ = media.transcribe(path, language="fr", timestamps=False)
    finally:
        path.unlink(missing_ok=True)
    return {"text": text.strip()}


# --- bouton « Partager » d'Android (Web Share Target) ---

@app.post("/share")
async def share_target(request: Request):
    form = await request.form()
    name = read_session(request.cookies.get(COOKIE))
    blob = " ".join(str(form.get(k) or "") for k in ("url", "text", "title"))
    url = fetch.extract_url(blob) or ""
    text = "" if url else str(form.get("text") or "").strip()
    files = [f for f in form.getlist("files") if hasattr(f, "filename") and f.filename]
    did = db.create_draft(name, url, text, [])
    saved = _save_uploads(files, config.DATA_DIR / "drafts" / did) if files else []
    if saved:
        db.execute("UPDATE drafts SET files_json=? WHERE id=?", (json.dumps(saved), did))
    return RedirectResponse(f"/?draft={did}#/nouveau", status_code=303)


@app.get("/share")
def share_target_get(url: str = "", text: str = "", title: str = ""):
    link = fetch.extract_url(f"{url} {text} {title}") or ""
    did = db.create_draft(None, link, "" if link else text, [])
    return RedirectResponse(f"/?draft={did}#/nouveau", status_code=303)


@app.get("/api/drafts/{did}")
def draft(did: str, name: str = Depends(user)):
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "Introuvable.")
    return {"id": d["id"], "url": d["url"], "text": d["text"], "files": json.loads(d["files_json"] or "[]")}


# --- appli ---

@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(config.STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    return FileResponse(config.STATIC_DIR / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
def health():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
