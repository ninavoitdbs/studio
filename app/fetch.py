"""Récupération d'un contenu à partir de son lien : vidéo, légende, images d'un carrousel, texte d'une page."""
import html as htmllib
import json
import re
from pathlib import Path

import httpx
from yt_dlp import YoutubeDL

from . import config
from .media import FFMPEG

UA = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0 Mobile Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".3gp"}
AUDIO_EXT = {".m4a", ".mp3", ".aac", ".ogg", ".opus", ".wav", ".weba"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif"}


class FetchError(Exception):
    pass


def platform_of(url: str) -> str:
    u = url.lower()
    for key, name in (("instagram.com", "instagram"), ("facebook.com", "facebook"), ("fb.watch", "facebook"),
                      ("youtube.com", "youtube"), ("youtu.be", "youtube"), ("tiktok.com", "tiktok"),
                      ("linkedin.com", "linkedin"), ("threads.", "threads"), ("x.com", "x"), ("twitter.com", "x")):
        if key in u:
            return name
    return "web"


def extract_url(text: str) -> str | None:
    m = re.search(r"https?://\S+", text or "")
    return m.group(0).rstrip(").,;!?»\"'") if m else None


def fetch_url(url: str, workdir: Path) -> dict:
    """Renvoie un dict source. Les fichiers (vidéos, images, sous-titres) sont écrits dans workdir."""
    plat = platform_of(url)
    src = {"url": url, "platform": plat, "kind": None, "author": "", "title": "", "caption": "",
           "videos": [], "audios": [], "images": [], "subtitles": "", "text": "", "notes": []}

    if plat == "youtube":
        _youtube(url, workdir, src)
        return src

    # Instagram bloque vite les serveurs : Apify d'abord quand il est branché
    if plat == "instagram" and config.apify_token():
        _try(src, "Apify Instagram", _apify_instagram, url, workdir, src)
        if src["videos"] or src["images"]:
            return _finish(src)

    if plat in ("instagram", "facebook", "tiktok", "threads", "x", "linkedin", "web"):
        try:
            _ytdlp_video(url, workdir, src)
        except Exception as e:  # pas de vidéo, compte privé, blocage…
            src["notes"].append(f"yt-dlp : {_short(e)}")

    if not src["videos"] and not src["images"]:
        if plat == "instagram":
            _try(src, "embed Instagram", _instagram_embed, url, workdir, src)
        elif plat == "facebook" and config.apify_token():
            _try(src, "Apify Facebook", _apify_facebook, url, workdir, src)

    if not (src["videos"] or src["images"] or src["caption"]):
        _try(src, "page", _page, url, workdir, src)
    return _finish(src)


def _finish(src: dict) -> dict:
    if src["kind"] is None:
        src["kind"] = ("video" if src["videos"] else "carrousel" if len(src["images"]) > 1
                       else "image" if src["images"] else "texte")
    if not (src["videos"] or src["images"] or src["caption"] or src["text"]):
        raise FetchError("Je n'ai rien pu récupérer à partir de ce lien (compte privé, contenu supprimé ou plateforme qui bloque). "
                         "Envoie-moi des captures d'écran ou la vidéo enregistrée, ça marche à tous les coups.")
    return src


def _try(src, label, fn, *args):
    try:
        fn(*args)
    except Exception as e:
        src["notes"].append(f"{label} : {_short(e)}")


def _short(e: Exception) -> str:
    return re.sub(r"\s+", " ", str(e))[:300]


def _ydl_opts(workdir: Path, **extra) -> dict:
    opts = {
        "outtmpl": str(workdir / "media_%(playlist_index|0)s.%(ext)s"),
        "ffmpeg_location": FFMPEG,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 30,
        "retries": 2,
        "max_filesize": config.MAX_UPLOAD_MB * 1024 * 1024,
        "http_headers": {"Accept-Language": UA["Accept-Language"]},
    }
    if config.COOKIES_FILE and Path(config.COOKIES_FILE).exists():
        opts["cookiefile"] = config.COOKIES_FILE
    opts.update(extra)
    return opts


def _fill_meta(info: dict, src: dict):
    src["title"] = src["title"] or (info.get("title") or "")[:300]
    src["caption"] = src["caption"] or info.get("description") or ""
    src["author"] = src["author"] or info.get("uploader") or info.get("channel") or info.get("uploader_id") or ""
    if info.get("duration"):
        src["duration"] = info["duration"]


def _ytdlp_video(url: str, workdir: Path, src: dict):
    fmt = "best[height<=720][ext=mp4]/best[height<=720]/bv*[height<=720]+ba/best"
    with YoutubeDL(_ydl_opts(workdir, format=fmt, noplaylist=False)) as ydl:
        info = ydl.extract_info(url, download=True)
    _fill_meta(info, src)
    for entry in (info.get("entries") or [info]):
        if entry:
            _fill_meta(entry, src)
    src["videos"] = sorted(p.name for p in workdir.glob("media_*") if p.suffix.lower() in VIDEO_EXT)


def _youtube(url: str, workdir: Path, src: dict):
    with YoutubeDL(_ydl_opts(workdir, skip_download=True, noplaylist=True)) as ydl:
        info = ydl.extract_info(url, download=False)
    _fill_meta(info, src)
    src["kind"] = "youtube"
    lang = (info.get("language") or "").split("-")[0]
    wanted = [l for l in (lang, f"{lang}-orig", "fr", "fr-orig", "en", "en-orig") if l and l != "-orig"]
    # Sous-titres d'abord (rapide), sinon l'audio pour la transcription
    try:
        with YoutubeDL(_ydl_opts(workdir, skip_download=True, noplaylist=True, writesubtitles=True,
                                 writeautomaticsub=True, subtitleslangs=wanted, subtitlesformat="vtt")) as ydl:
            ydl.extract_info(url, download=True)
        vtts = list(workdir.glob("*.vtt"))
        vtts.sort(key=lambda p: next((i for i, l in enumerate(wanted) if p.name.endswith(f".{l}.vtt")), 99))
        if vtts:
            src["subtitles"] = _vtt_to_text(vtts[0].read_text(encoding="utf-8", errors="ignore"))
    except Exception as e:
        src["notes"].append(f"sous-titres : {_short(e)}")
    if not src["subtitles"]:
        with YoutubeDL(_ydl_opts(workdir, format="ba[ext=m4a]/ba/b", noplaylist=True)) as ydl:
            ydl.extract_info(url, download=True)
        src["audios"] = sorted(p.name for p in workdir.glob("media_*") if p.suffix.lower() in AUDIO_EXT | VIDEO_EXT)


def _vtt_to_text(vtt: str) -> str:
    out, last = [], ""
    stamp = ""
    for line in vtt.splitlines():
        line = line.strip()
        m = re.match(r"(\d+):(\d+):(\d+)\.\d+ -->", line) or re.match(r"(\d+):(\d+)\.\d+ -->", line)
        if m:
            parts = [int(x) for x in m.groups()]
            secs = parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]
            stamp = f"[{secs // 60:02d}:{secs % 60:02d}] "
            continue
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or line.isdigit():
            continue
        text = re.sub(r"<[^>]+>", "", line).strip()
        if text and text != last:
            out.append(stamp + text)
            stamp = ""
            last = text
    return "\n".join(out)


def _download_images(urls: list[str], workdir: Path, src: dict):
    seen = set()
    for u in urls:
        if not u or u in seen:
            continue
        seen.add(u)
        r = httpx.get(u, headers=UA, timeout=30, follow_redirects=True)
        if r.status_code == 200 and r.content:
            name = f"slide_{len(src['images']) + 1:02d}.jpg"
            (workdir / name).write_bytes(r.content)
            src["images"].append(name)


def _download_videos(urls: list[str], workdir: Path, src: dict):
    for u in urls:
        if not u:
            continue
        name = f"media_{len(src['videos']) + 1}.mp4"
        with httpx.stream("GET", u, headers=UA, timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            with open(workdir / name, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        src["videos"].append(name)


def _instagram_embed(url: str, workdir: Path, src: dict):
    m = re.search(r"instagram\.com/(?:[^/]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", url)
    if not m:
        raise FetchError("lien Instagram non reconnu")
    r = httpx.get(f"https://www.instagram.com/p/{m.group(1)}/embed/captioned/", headers=UA, timeout=30,
                  follow_redirects=True)
    page = r.text
    cap = re.search(r'class="Caption"[^>]*>(.*?)</div>', page, re.S)
    if cap:
        text = re.sub(r"<br\s*/?>", "\n", cap.group(1))
        text = htmllib.unescape(re.sub(r"<[^>]+>", "", text)).strip()
        text = re.sub(r"\s*View all \d+ comments\s*$", "", text)
        src["caption"] = src["caption"] or text
    user = re.search(r'class="UsernameText"[^>]*>([^<]+)<', page)
    if user:
        src["author"] = src["author"] or user.group(1).strip()
    urls = [htmllib.unescape(u) for u in re.findall(r'class="EmbeddedMediaImage"[^>]*?src="([^"]+)"', page)]
    urls += [json.loads(f'"{u}"') for u in re.findall(r'\\?"display_url\\?":\\?"(.*?)\\?"', page)]
    _download_images(urls[:20], workdir, src)


def _apify(actor: str, payload: dict) -> list[dict]:
    r = httpx.post(f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
                   params={"token": config.apify_token(), "timeout": 150}, json=payload, timeout=200)
    r.raise_for_status()
    return r.json()


def _apify_instagram(url: str, workdir: Path, src: dict):
    items = _apify("apify~instagram-scraper", {"directUrls": [url], "resultsType": "posts", "resultsLimit": 1})
    if not items or items[0].get("error"):
        raise FetchError((items[0].get("errorDescription") if items else None) or "aucun résultat")
    it = items[0]
    src["caption"] = src["caption"] or it.get("caption") or ""
    src["author"] = src["author"] or it.get("ownerUsername") or ""
    children = it.get("childPosts") or []
    videos = [it.get("videoUrl")] if it.get("videoUrl") else [c.get("videoUrl") for c in children if c.get("videoUrl")]
    images = it.get("images") or [c.get("displayUrl") for c in children if c.get("displayUrl")] or [it.get("displayUrl")]
    _download_videos(videos[:3], workdir, src)
    if not src["videos"] or len(images) > 1:
        _download_images(images[:20], workdir, src)


def _apify_facebook(url: str, workdir: Path, src: dict):
    items = _apify("apify~facebook-posts-scraper", {"startUrls": [{"url": url}], "resultsLimit": 1})
    if not items:
        raise FetchError("aucun résultat")
    it = items[0]
    src["caption"] = src["caption"] or it.get("text") or it.get("message") or ""
    src["author"] = src["author"] or (it.get("user") or {}).get("name") or it.get("pageName") or ""
    images = []
    for m in it.get("media") or []:
        images.append((m.get("photo_image") or {}).get("uri") or m.get("thumbnail") or m.get("url"))
    _download_images([u for u in images if u][:20], workdir, src)


def _page(url: str, workdir: Path, src: dict):
    r = httpx.get(url, headers=UA, timeout=30, follow_redirects=True)
    page = r.text

    def meta(prop):
        m = re.search(rf'<meta[^>]+(?:property|name)="{prop}"[^>]+content="([^"]*)"', page) or \
            re.search(rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{prop}"', page)
        return htmllib.unescape(m.group(1)) if m else ""

    src["title"] = src["title"] or meta("og:title") or htmllib.unescape(
        (re.search(r"<title>(.*?)</title>", page, re.S) or [None, ""])[1]).strip()
    desc = meta("og:description") or meta("description")
    body = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", page)
    body = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", body)
    body = htmllib.unescape(re.sub(r"<[^>]+>", " ", body))
    body = "\n".join(l.strip() for l in body.splitlines() if len(l.strip()) > 2)
    src["text"] = (desc + "\n\n" + body).strip()[:20000]
    img = meta("og:image")
    if img and not src["images"]:
        _download_images([img], workdir, src)


def classify_upload(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in IMAGE_EXT:
        return "image"
    return "other"
