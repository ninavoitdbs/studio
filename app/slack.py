"""Envoi d'un texte du Studio sur Slack (canal ou message privé) avec le bot du Studio."""
import re

import httpx

from . import config


class SlackError(Exception):
    pass


def to_mrkdwn(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"(?m)^#{1,6}\s*(.+)$", r"*\1*", text)
    return text


def format_message(item: dict, msg: dict, sender: str) -> str:
    title = item.get("title") or "Sans titre"
    if msg["kind"] in ("reel", "version") and (item.get("output_format") == "reel"):
        # Format téléprompteur de Nina : ligne 1 « Reel : nom », puis le texte brut
        return f"Reel : {title}\n{msg['content'].strip()}"
    label = {"accroches": "Accroches", "legende": "Légende", "carrousel": "Carrousel", "youtube": "Structure YouTube",
             "email": "Mail", "post": "Post", "linkedin": "Post LinkedIn", "reponse": "Réponse"}.get(msg["kind"], "Proposition")
    lines = [f"*{label} : {title}*  (envoyé du Studio par {sender})", "", to_mrkdwn(msg["content"].strip())]
    if item.get("source_url"):
        lines += ["", f"Source : {item['source_url']}"]
    return "\n".join(lines)


def post(dest_id: str, text: str):
    if not config.SLACK_BOT_TOKEN:
        raise SlackError("Slack n'est pas encore branché (jeton du bot manquant).")
    r = httpx.post("https://slack.com/api/chat.postMessage",
                   headers={"Authorization": f"Bearer {config.SLACK_BOT_TOKEN}"},
                   json={"channel": dest_id, "text": text, "unfurl_links": False, "unfurl_media": False},
                   timeout=20)
    data = r.json()
    if not data.get("ok"):
        hint = {"not_in_channel": " Invite le bot du Studio dans ce canal (/invite).",
                "channel_not_found": " Le bot ne voit pas ce canal : invite-le dedans."}.get(data.get("error"), "")
        raise SlackError(f"Slack a refusé : {data.get('error')}.{hint}")
