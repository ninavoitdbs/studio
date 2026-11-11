# Studio du Bon Sens

Appli web installable sur téléphone (Android : bouton « Partager » d'Instagram/Facebook → Studio). On y dépose un contenu qui inspire (réel, carrousel, post, mail, vidéo YouTube, captures, texte) ; le Studio le récupère, l'écoute, et Claude le réécrit dans l'univers de Nina (script de réel par défaut). Fil de commentaires (texte ou dictée), boutons Autre version / Accroches / Légende / Transformer en… / Pourquoi ça marche / Partager sur Slack. Utilisable par toute l'équipe (code d'équipe + prénom).

## Où ça tourne

- Serveur `nina-vps`, dossier `~/studio`, service systemd utilisateur `studio` (port local 127.0.0.1:8787).
- Réglages et secrets : `~/.config/studio/env` (chmod 600). Modèle : `deploy/env.example`.
- Données : `~/studio/data/` (base SQLite `studio.db`, fichiers de chaque contenu dans `items/<id>/`).
- Cerveau d'écriture : `~/studio/brain/` (voix, formats, doctrine, anecdotes de Nina). Il fait partie du dépôt Git : le modifier dans le clone, pousser, puis déployer (voir plus bas).

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

Tests (avec le Python du venv) :

```bash
venv/bin/python tests/test_envois.py
```

## Code et déploiement (depuis le 11/11/2026)

- Le code est sous Git : dépôt privé GitHub `ninavoitdbs/studio`. La branche `main` est ce qui tourne en prod.
- **Ne plus déployer avec `tar`** : ça contournerait l'historique et le retour arrière.
- Sur le PC : cloner le dépôt (`git clone git@github.com:ninavoitdbs/studio.git`), modifier, `git commit`, `git push`. Puis déployer :

```bash
ssh nina-vps ~/studio/deploy/deploy.sh
```

Le script refuse de tourner si des fichiers ont été modifiés directement sur le serveur, récupère `main`, réinstalle les dépendances si `requirements.lock` a changé, met à jour les unités systemd, redémarre et vérifie `/healthz`. Si le Studio ne répond pas, il revient tout seul à la version précédente.

- Dépendances : versions exactes dans `requirements.lock` (c'est lui qui est installé). `requirements.txt` sert seulement de liste de départ pour une mise à jour volontaire (par exemple yt-dlp quand Instagram ou Facebook changent).

## Sauvegardes

- Tous les jours vers 03:30 : `deploy/backup.sh` (timer `studio-backup`). Archives dans `~/backups/studio/` (7 quotidiennes + 4 hebdomadaires) : base, fichiers, réglages, fichier env.
- Pas de copie hors serveur (choix du 11/11/2026) : si le VPS est perdu, ce sont les sauvegardes Hostinger qui servent.
- Sauvegarde à la main : `systemctl --user start studio-backup`.
- Restaurer : arrêter le Studio, extraire l'archive (`tar xzf <archive> -C /tmp/restau`), remettre `data/` (et le fichier env si besoin) à sa place, redémarrer.

## Limites d'envoi

- Caddy refuse tout envoi de plus de 310 Mo. L'appli accepte 300 Mo par fichier et 20 fichiers par envoi.
- Bouton « Partager » sans session : rien n'est gardé sur le serveur, le lien est repris dans l'adresse et pré-rempli après connexion (les fichiers ne suivent pas).
- Brouillons de partage non utilisés effacés après 48 h.

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
