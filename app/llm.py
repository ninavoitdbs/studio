"""Appel de Claude via Claude Code en mode non interactif (compte de Nina sur le serveur)."""
import json
import re
import subprocess
from pathlib import Path

from . import config


class LLMError(Exception):
    pass


def run(system: str, prompt: str, workdir: Path, add_dirs: list[str] = (), effort: str | None = None) -> str:
    sysfile = workdir / "_system.md"
    sysfile.write_text(system, encoding="utf-8")
    cmd = [
        config.CLAUDE_BIN, "-p",
        "--model", config.CLAUDE_MODEL,
        "--system-prompt-file", str(sysfile),
        "--tools", "Read,Grep,Glob",
        "--allowedTools", "Read,Grep,Glob",
        "--permission-mode", "dontAsk",
        # Sans ça, les connecteurs du compte gonflent chaque appel de plusieurs centaines de milliers de jetons
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--output-format", "json",
    ]
    if effort:
        cmd += ["--effort", effort]
    for d in add_dirs:
        if d and Path(d).is_dir():
            cmd += ["--add-dir", str(d)]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                           cwd=workdir, timeout=config.CLAUDE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise LLMError("Claude a mis trop de temps à répondre. Réessaie.")
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise LLMError(f"Réponse illisible de Claude ({r.returncode}) : {(r.stderr or r.stdout)[-500:]}")
    if data.get("is_error") or not data.get("result"):
        raise LLMError(f"Claude a renvoyé une erreur : {str(data.get('result') or data.get('subtype'))[:500]}")
    return data["result"]


def tag(text: str, name: str) -> str:
    m = re.search(rf"<{name}>(.*?)</{name}>", text, re.S)
    if m:
        return m.group(1).strip()
    m = re.search(rf"<{name}>(.*)$", text, re.S)  # balise fermante oubliée
    return m.group(1).strip() if m else ""
