# Studio du Bon Sens

Appli web installable sur téléphone (Android : bouton « Partager » d'Instagram/Facebook → Studio). On y dépose un contenu qui inspire (réel, carrousel, post, mail, vidéo YouTube, captures, texte) ; le Studio le récupère, l'écoute, et Claude le réécrit dans l'univers de Nina (script de réel par défaut). Fil de commentaires (texte ou dictée), boutons Autre version / Accroches / Légende / Transformer en… / Pourquoi ça marche / Partager sur Slack. Utilisable par toute l'équipe (code d'équipe + prénom).

## Où ça tourne

- Serveur `nina-vps`, dossier `~/studio`, service systemd utilisateur `studio` (port local 127.0.0.1:8787).
- Réglages et secrets : `~/.config/studio/env` (chmod 600). Modèle : `deploy/env.example`.
- Données : `~/studio/data/` (base SQLite `studio.db`, fichiers de chaque contenu dans `items/<id>/`).
- Cerveau d'écriture : `~/studio/brain/` (voix, formats, doctrine, anecdotes de Nina). La source est `Second cerveau/Système/outils/studio/brain/` : la mettre à jour là puis redéployer.

## Comment ça marche

1. `app/fetch.py` récupère le contenu : Apify d'abord pour Instagram (Instagram bloque les serveurs), sinon yt-dlp ; page d'intégration Instagram en secours ; texte de la page pour le reste. YouTube : sous-titres d'abord, sinon l'audio.
2. `app/media.py` transcrit avec faster-whisper (modèle `WHISPER_MODEL`, sur le processeur) et fait des planches de captures pour lire le texte à l'écran.
3. `app/llm.py` appelle Claude Code (`claude -p`, compte de Nina sur le serveur) avec le cerveau en prompt système. Outils limités à Read/Grep/Glob, accès au cerveau et à l'Encyclopédie (`~/encyclopedie/corpus`). `--strict-mcp-config` est indispensable : sans lui, les connecteurs du compte ajoutent ~380 000 jetons à chaque appel.
4. `app/slack.py` poste avec le bot « Studio ». Un script de réel part au format téléprompteur (« Reel : titre » puis le texte brut).

## Commandes utiles (sur nina-vps)

```bash
systemctl --user status studio
journalctl --user -u studio -f
systemctl --user restart studio
```

Déployer depuis le PC (dans ce dossier) :

```bash
tar czf - app static brain deploy requirements.txt | ssh nina-vps 'cd ~/studio && tar xzf - && systemctl --user restart studio'
```

## Version locale sur le PC de Nina (depuis le 09/11/2026)

**Abandonnée** : Nina ne veut aucune étape technique (terminal, fichier de config). Elle utilise le Studio du serveur. Les fichiers ci-dessous peuvent être supprimés.

- Lancer : double-clic sur `Lancer le Studio.bat` (dans ce dossier). Le navigateur s'ouvre sur http://127.0.0.1:8787. Fermer la fenêtre noire arrête le Studio.
- Réglages et secrets : `C:\Users\Nina VOIT\.config\studio\env` (hors du second cerveau). Code d'équipe : `bonsens`. Nina y colle elle-même sa clé `APIFY_TOKEN`.
- Données : `C:\Users\Nina VOIT\.config\studio\data`. Python : `.venv` dans ce dossier (`pip install -r requirements.txt`).
- `lancer_local.py` lit le fichier env, trouve Claude Code (`~\.local\bin\claude.exe`, sinon celui fourni avec l'appli Claude) et lance le serveur. Claude Code doit être connecté une fois au compte de Nina (`claude` puis `/login`).
- Pas de Slack ni de dictée sur téléphone en local, et pas d'Encyclopédie (pas de copie du corpus sur le PC).

## Adresse

https://studio-dbs.fr (domaine OVH, compte vn134143-ovh, enregistrements A `@` et `www` → 76.13.252.64). Caddy sur nina-vps (`/etc/caddy/Caddyfile`) : HTTPS automatique, `X-Robots-Tag noindex`, robots.txt qui interdit tout, puis reverse_proxy vers 127.0.0.1:8787. `PUBLIC_URL=https://studio-dbs.fr` dans le fichier env (cookie sécurisé : le tunnel SSH en http ne permet plus de se connecter).

## Clé Apify

Collée par Nina dans Studio › Réglages (menu prénom). Elle est vérifiée auprès d'Apify et gardée dans `data/settings.json`, qui passe avant `APIFY_TOKEN` du fichier env.

## Reste à brancher

- App Slack depuis `deploy/slack_app_manifest.yaml` → `SLACK_BOT_TOKEN`, et inviter le bot dans #scripts-reels-pub.
