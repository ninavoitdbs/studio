"""Construction des prompts : le cerveau de Nina + la source + la demande."""
from pathlib import Path

from . import config

FORMATS = {
    "reel": "script de réel",
    "carrousel": "carrousel",
    "post": "post (Facebook / Instagram)",
    "linkedin": "post LinkedIn",
    "youtube": "structure de vidéo YouTube",
    "email": "mail (newsletter)",
}

FORMAT_FILES = {
    "reel": ["reel.md"],
    "carrousel": ["carrousel.md"],
    "post": ["post-facebook.md", "post-instagram.md"],
    "linkedin": ["linkedin.md"],
    "youtube": ["youtube.md", "reel.md"],
    "email": ["email.md"],
    "instagram": ["post-instagram.md"],
    "facebook": ["post-facebook.md"],
}

LIVRABLE_RULES = {
    "reel": "Le texte à dire, et rien d'autre : texte brut d'un seul bloc, sans titre, sans label (HOOK, CTA…), sans emoji, "
            "sans tiret, sans ligne vide. Prêt à coller dans le téléprompteur. Arc : hook, promesse, corps avec boucles ouvertes, CTA. "
            "Longueur parlée proche de la source (environ 150 mots par minute), sauf consigne.",
    "carrousel": "Une ligne par slide : « Slide 1 : … », « Slide 2 : … ». Textes courts, lisibles sur une slide. "
                 "Pour la slide 1, une seule accroche (les variantes viendront avec le bouton dédié). Pas de légende sauf demande.",
    "post": "Le post complet, prêt à publier, pour la plateforme de la source (Facebook par défaut), au format de Nina.",
    "linkedin": "Le post LinkedIn complet, prêt à publier, au format LinkedIn de Nina.",
    "youtube": "En Markdown : 3 propositions de titre, la promesse de la vidéo, l'accroche des 30 premières secondes rédigée en entier "
               "(texte à dire), puis le plan partie par partie (idée clé, exemples/anecdotes à placer, boucle vers la suite), "
               "la conclusion et le CTA. C'est une structure à tourner, pas un texte intégral.",
    "email": "Deux propositions d'objet, puis le mail complet au format de l'équipe (Hello, une phrase par ligne…).",
}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def brain(formats: list[str]) -> str:
    parts = []
    for name in ("00_identite.md", "01_voix.md", "doctrine.md", "anecdotes.md"):
        txt = _read(config.BRAIN_DIR / name)
        if txt:
            parts.append(f"<cerveau fichier=\"{name}\">\n{txt}\n</cerveau>")
    seen = set()
    for f in formats:
        for fname in FORMAT_FILES.get(f, []):
            if fname in seen:
                continue
            seen.add(fname)
            txt = _read(config.BRAIN_DIR / "formats" / fname)
            if txt:
                parts.append(f"<cerveau fichier=\"formats/{fname}\">\n{txt}\n</cerveau>")
    return "\n\n".join(parts)


def system_prompt(formats: list[str]) -> str:
    enc = config.ENCYCLOPEDIE_DIR if Path(config.ENCYCLOPEDIE_DIR).is_dir() else None
    tools = (
        f"\n- Les fiches de tous les formats sont dans `{config.BRAIN_DIR / 'formats'}` : lis celle qu'il te faut si on te demande "
        "un format dont la fiche n'est pas ci-dessous."
    )
    if enc:
        tools += (
            f"\n- L'Encyclopédie de Nina (ses formations, conférences, doctrine) est dans `{enc}`. Quand ça renforce le contenu, "
            "cherches-y (Grep) une anecdote, une formule ou la position de Nina sur le sujet. Trois recherches au plus, ciblées."
        )
    return f"""Tu es la plume de Nina Voit (Du Bon Sens dans mon Assiette) dans le Studio : une appli où Nina et son équipe déposent un contenu qui les inspire (réel, carrousel, post, mail, vidéo YouTube d'un autre créateur, en français ou en anglais). Ton travail : en tirer un contenu prêt à tourner ou à publier pour Nina, dans SON univers, avec SA voix et SES enjeux.

Principes :
- On reprend ce qui fait marcher la source (la thématique, l'angle, la mécanique de l'accroche, la structure, le rythme), pas son texte, sauf si la consigne demande une traduction mot à mot. Le résultat doit sonner 100 % Nina et respecter sa doctrine (MTC, alimentation et métabolisme au cœur, biochimie en appui). Si la source affirme quelque chose de contraire à la doctrine de Nina, tu écris la position de Nina.
- Les consignes de la personne qui dépose le contenu priment sur tout le reste : traduction mot à mot, CTA imposé, longueur, angle, cible, format.
- Toujours en français, sauf consigne contraire.
- CTA : les CTA de Nina changent souvent, on te les donne en consigne. Sans consigne, termine par un appel simple et générique (s'abonner, commenter, partager, aller voir la vidéo) et n'invente jamais de mot-clé ManyChat, d'offre ou de lien.
- N'invente jamais de fait sur la vie de Nina. Une anecdote ne vient que de sa banque d'anecdotes ou de l'Encyclopédie ; sinon mets un repère entre crochets, par exemple [anecdote perso à placer].
- Le livrable est donné seul, sans phrase d'introduction ni commentaire autour. Pas de ligne « Reel : … » en tête (l'appli l'ajoute elle-même pour Slack). Les points à faire vérifier par Nina (fait non sourcé, plante ou dosage à valider…) vont dans la balise <note>, jamais dans le livrable.

Outils :{tools}
- Les fichiers de la source (planches de captures vidéo, slides, images) sont dans le dossier de travail : lis-les avec Read quand on te les signale.

Voici le cerveau de Nina. Respecte-le scrupuleusement.

{brain(formats)}
"""


def source_block(item: dict, src: dict) -> str:
    lines = ["<source>"]
    if src.get("url"):
        lines.append(f"Lien : {src['url']}")
    if src.get("platform"):
        lines.append(f"Plateforme : {src['platform']} ({src.get('kind') or '?'})")
    if src.get("author"):
        lines.append(f"Auteur : {src['author']}")
    if src.get("duration"):
        lines.append(f"Durée : {int(src['duration'])} s")
    if src.get("title") and src.get("title") != src.get("caption"):
        lines.append(f"Titre : {src['title']}")
    if src.get("caption"):
        lines.append(f"Légende / description d'origine :\n{src['caption'].strip()}")
    for t in src.get("transcripts", []):
        lines.append(f"Transcription audio de {t['file']} (langue détectée : {t.get('lang') or '?'}) :\n{t['text'] or '(pas de voix)'}")
    if src.get("subtitles"):
        lines.append(f"Sous-titres de la vidéo :\n{src['subtitles'][:60000]}")
    if src.get("text"):
        lines.append(f"Texte :\n{src['text'][:30000]}")
    if src.get("sheets"):
        lines.append("Planches de captures de la vidéo, dans l'ordre (texte à l'écran, format visuel) : " + ", ".join(src["sheets"]))
    if src.get("images"):
        lines.append("Images / slides, dans l'ordre : " + ", ".join(src["images"]))
    lines.append("</source>")
    return "\n".join(lines)


def create_prompt(item: dict, src: dict) -> str:
    fmt = item.get("target_format") or "auto"
    if fmt == "auto":
        fmt_line = ("auto : même nature que la source (réel ou vidéo courte → script de réel ; carrousel → carrousel ; "
                    "post photo ou texte → post ; vidéo YouTube longue → structure YouTube ; mail → mail), sauf si la consigne dit autre chose.")
    else:
        fmt_line = FORMATS.get(fmt, fmt)
    files_note = ""
    if src.get("sheets") or src.get("images"):
        files_note = "Commence par lire les planches et les images avec Read : le texte à l'écran fait partie du contenu.\n"
    rules = "\n".join(f"- {FORMATS[k]} : {v}" for k, v in LIVRABLE_RULES.items())
    return f"""{source_block(item, src)}

<consigne de="{item['author']}">
{(item.get('instructions') or '').strip() or '(aucune consigne particulière)'}
</consigne>

Format demandé : {fmt_line}

{files_note}Étapes :
1. Analyse la source pour toi : sujet et angle, l'accroche (type et mots exacts), la structure temps par temps, les mécaniques de rétention, le CTA, et ce qui fait vraiment marcher ce contenu (parfois c'est seulement la thématique, même si c'est mal construit). Puis comment tu le transposes chez Nina.
2. Écris le livrable en reconstruisant ce qui marche, dans l'univers de Nina.

Règles de livrable selon le format :
{rules}

Réponds exactement avec ces balises, rien d'autre :
<titre>titre interne court, 4 à 8 mots, en français</titre>
<format>reel | carrousel | post | linkedin | youtube | email</format>
<analyse>ton analyse, 8 à 15 lignes</analyse>
<livrable>le livrable</livrable>
<note>facultatif : points à vérifier, une ou deux lignes ; omets la balise s'il n'y a rien</note>"""


ACTIONS = {
    "version": "Propose une version vraiment différente du dernier livrable : autre angle, autre accroche ou autre structure. "
               "Même format et mêmes consignes. Renvoie le livrable complet.",
    "hooks": "Propose 5 accroches alternatives pour le dernier livrable, de types différents (question, chiffre, croyance renversée, "
             "scène vécue, interpellation, syndrome nommé…). Une par ligne, numérotées, rien d'autre.",
}


def followup_prompt(item: dict, src: dict, thread: list[dict], action: str, request: dict) -> str:
    hist = []
    for m in thread:
        if m["status"] != "done":
            continue
        who = m["author"] if m["role"] == "user" else "Toi (Studio)"
        hist.append(f"<message de=\"{who}\" type=\"{m['kind']}\">\n{m['content']}\n</message>")
    if action == "caption":
        plat = request.get("platform") or "instagram"
        ask = (f"Écris la légende {plat.capitalize()} qui accompagne ce contenu, selon le format de légende de Nina pour {plat}. "
               "Juste la légende, prête à coller.")
        kind = "legende"
    elif action == "format":
        fmt = request.get("format") or "reel"
        ask = (f"Transforme ce contenu en {FORMATS.get(fmt, fmt)}, toujours dans l'univers de Nina. "
               f"Règle de livrable : {LIVRABLE_RULES.get(fmt, '')}")
        kind = fmt
    elif action in ACTIONS:
        ask = ACTIONS[action]
        kind = "accroches" if action == "hooks" else "version"
    else:
        ask = (f"Nouvelle demande de {request.get('author', 'l’équipe')} :\n{request.get('text', '').strip()}\n\n"
               "Si c'est une demande de modification, renvoie le livrable complet modifié. Si c'est une question, réponds en quelques lignes.")
        kind = "auto"
    files_note = ""
    if src.get("sheets") or src.get("images"):
        files_note = "\n(Les planches et images de la source restent disponibles dans le dossier de travail si tu as besoin de les relire.)"
    return f"""{source_block(item, src)}

<analyse_de_la_source>
{item.get('analysis') or ''}
</analyse_de_la_source>

<consigne_de_depart de="{item['author']}">
{(item.get('instructions') or '').strip() or '(aucune)'}
</consigne_de_depart>

<fil>
{chr(10).join(hist)}
</fil>
{files_note}
{ask}

Réponds exactement avec ces balises, rien d'autre :
<type>{'version | reponse' if kind == 'auto' else kind}</type>
<livrable>le texte</livrable>
<note>facultatif : points à vérifier, une ou deux lignes ; omets la balise s'il n'y a rien</note>"""
