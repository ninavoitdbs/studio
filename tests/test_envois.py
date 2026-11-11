"""Tests des envois (bouton Partager d'Android, fichiers joints).

Lancer depuis la racine du depot, avec le Python du venv :
    venv/bin/python tests/test_envois.py
(fonctionne aussi avec pytest s'il est installe). Utilise une base et un dossier
de donnees temporaires : ne touche jamais aux donnees de prod.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="studio-test-")
os.environ.update({
    "STUDIO_DATA_DIR": _TMP,
    "TEAM_CODE": "code-test",
    "SECRET_KEY": "cle-de-test-pas-secrete",
    "PUBLIC_URL": "",  # cookie non "secure" : le client de test parle en http
})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, main  # noqa: E402

DATA = Path(_TMP)


def _client(logged_in: bool) -> TestClient:
    c = TestClient(main.app, follow_redirects=False)
    c.__enter__()  # lance le lifespan (base, reprise des taches)
    if logged_in:
        r = c.post("/api/login", data={"name": "Testeur", "code": "code-test"})
        assert r.status_code == 200, r.text
    return c


def _count(table: str) -> int:
    return db.query(f"SELECT count(*) AS n FROM {table}")[0]["n"]


def _draft_files() -> list[Path]:
    d = DATA / "drafts"
    return [p for p in d.rglob("*") if p.is_file()] if d.exists() else []


def test_share_post_sans_connexion_ne_cree_rien():
    c = _client(False)
    before = _count("drafts")
    r = c.post("/share", data={"url": "https://www.instagram.com/reel/abc/"},
               files={"files": ("video.mp4", b"x" * 1000, "video/mp4")})
    assert r.status_code == 303, r.status_code
    loc = r.headers["location"]
    # Rien garde sur le serveur, mais le lien suit dans l'adresse (si Android n'envoie pas le cookie)
    assert loc == "/?partage=connexion&lien=https%3A%2F%2Fwww.instagram.com%2Freel%2Fabc%2F&fichiers=perdus#/nouveau", loc
    assert _count("drafts") == before
    assert _draft_files() == []


def test_share_get_sans_connexion_ne_cree_rien():
    c = _client(False)
    before = _count("drafts")
    r = c.get("/share", params={"url": "https://www.instagram.com/reel/abc/"})
    assert r.status_code == 303
    assert r.headers["location"] == "/?partage=connexion&lien=https%3A%2F%2Fwww.instagram.com%2Freel%2Fabc%2F#/nouveau"
    assert _count("drafts") == before


def test_share_sans_connexion_ni_lien():
    c = _client(False)
    r = c.post("/share", data={"text": "juste du texte"})
    assert r.headers["location"] == "/?partage=connexion#/nouveau", r.headers["location"]


def test_share_post_connecte_cree_le_brouillon():
    c = _client(True)
    r = c.post("/share", data={"text": "regarde https://www.instagram.com/reel/abc/"},
               files={"files": ("capture.png", b"png" * 100, "image/png")})
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/?draft="), loc
    did = loc.split("draft=")[1].split("#")[0]
    d = c.get(f"/api/drafts/{did}").json()
    assert d["url"] == "https://www.instagram.com/reel/abc/"
    assert d["files"] == ["01_capture.png"]


def test_share_get_connecte_cree_le_brouillon():
    c = _client(True)
    r = c.get("/share", params={"text": "https://youtu.be/xyz"})
    assert r.status_code == 303
    assert r.headers["location"].startswith("/?draft=")


def test_fichier_trop_lourd_refuse_sans_rien_laisser():
    c = _client(True)
    old = config.MAX_UPLOAD_MB
    config.MAX_UPLOAD_MB = 1
    try:
        before = _count("items")
        r = c.post("/api/items", data={"text": "test"},
                   files={"files": ("gros.mp4", b"0" * (2 * 1024 * 1024), "video/mp4")})
    finally:
        config.MAX_UPLOAD_MB = old
    assert r.status_code == 413, r.status_code
    assert _count("items") == before, "un contenu orphelin a ete cree"
    assert not list((DATA / "items").rglob("gros.mp4")) if (DATA / "items").exists() else True


def test_trop_de_fichiers_refuse():
    c = _client(True)
    files = [("files", (f"f{i}.png", b"x", "image/png")) for i in range(config.MAX_FILES + 1)]
    before = _count("drafts")
    r = c.post("/share", data={"text": "x"}, files=files)
    assert r.status_code == 400, r.status_code
    assert _count("drafts") == before


def test_vieux_brouillons_effaces():
    old = db.create_draft("Testeur", "https://exemple.fr", "", ["01_a.png"])
    db.execute("UPDATE drafts SET created_at=? WHERE id=?", (time.time() - 3 * 24 * 3600, old))
    (DATA / "drafts" / old).mkdir(parents=True, exist_ok=True)
    (DATA / "drafts" / old / "01_a.png").write_bytes(b"x")
    recent = db.create_draft("Testeur", "https://exemple.fr", "", [])
    main.purge_old_drafts()
    assert db.get_draft(old) is None
    assert not (DATA / "drafts" / old).exists()
    assert db.get_draft(recent) is not None


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK    {name}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"ECHEC {name} : {type(e).__name__} {e}")
    print(f"\n{fails} echec(s)")
    sys.exit(1 if fails else 0)
