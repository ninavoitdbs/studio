// Studio du Bon Sens : interface (bibliothèque, nouveau contenu, fil d'échanges).
const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
let me = null;
let pollTimer = null;
const state = { draftId: new URLSearchParams(location.search).get("draft"), showAnalysis: false };

const ICON = {
  mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12l16-8-6 16-2-7-8-1z"/></svg>',
  paste: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4V3h6v1"/></svg>',
};

const KIND_LABEL = {
  reel: "Script de réel", carrousel: "Carrousel", post: "Post", linkedin: "Post LinkedIn", youtube: "Structure YouTube",
  email: "Mail", version: "Nouvelle version", accroches: "Accroches", legende: "Légende", reponse: "Réponse",
};
const FORMATS = [["auto", "Auto"], ["reel", "Réel"], ["carrousel", "Carrousel"], ["post", "Post"],
  ["linkedin", "LinkedIn"], ["youtube", "YouTube"], ["email", "Mail"]];
const PLATFORM_LABEL = { instagram: "Instagram", facebook: "Facebook", youtube: "YouTube", tiktok: "TikTok",
  linkedin: "LinkedIn", web: "Web", fichier: "Fichiers", texte: "Texte", threads: "Threads", x: "X" };
const ACTIVE = ["queued", "fetching", "transcribing", "writing"];

// --- utilitaires ---

async function api(path, opts = {}) {
  const res = await fetch(path, { credentials: "same-origin", ...opts });
  if (res.status === 401) { showLogin(); throw new Error("auth"); }
  let data = null;
  try { data = await res.json(); } catch { /* réponse vide */ }
  if (!res.ok) throw new Error((data && data.detail) || `Erreur ${res.status}`);
  return data;
}
const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), ms);
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function inline(s) {
  return s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/(^|\s)_([^_\n]+)_/g, "$1<em>$2</em>");
}

// Markdown minimal : titres, gras, italique, listes, paragraphes
function md(text) {
  const lines = esc(text).split("\n");
  let html = "", list = null, para = [];
  const flushPara = () => { if (para.length) { html += `<p>${inline(para.join("<br>"))}</p>`; para = []; } };
  const flushList = () => { if (list) { html += `</${list}>`; list = null; } };
  for (const raw of lines) {
    const line = raw.trimEnd();
    let m;
    if (!line.trim()) { flushPara(); flushList(); continue; }
    if ((m = line.match(/^#{1,6}\s+(.*)/))) { flushPara(); flushList(); html += `<h3>${inline(m[1])}</h3>`; continue; }
    if ((m = line.match(/^\s*(?:[-•>]|-&gt;|&gt;)\s+(.*)/))) {
      flushPara(); if (list !== "ul") { flushList(); html += "<ul>"; list = "ul"; } html += `<li>${inline(m[1])}</li>`; continue;
    }
    if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) {
      flushPara(); if (list !== "ol") { flushList(); html += "<ol>"; list = "ol"; } html += `<li>${inline(m[1])}</li>`; continue;
    }
    flushList(); para.push(line);
  }
  flushPara(); flushList();
  return html;
}

function timeAgo(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "à l'instant";
  if (s < 3600) return `il y a ${Math.floor(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`;
  return new Date(ts * 1000).toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
}

function domain(url) { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; } }
function extractUrl(text) { const m = (text || "").match(/https?:\/\/\S+/); return m ? m[0].replace(/[).,;!?»"']+$/, "") : ""; }

async function copy(text) {
  try { await navigator.clipboard.writeText(text); }
  catch {
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove();
  }
  toast("Copié");
}

function sheet(title, options) {
  return new Promise((resolve) => {
    const el = $("#sheet");
    el.innerHTML = `<div class="sheet-panel"><h2>${esc(title)}</h2>${options.map((o, i) =>
      `<button class="btn ${o.ghost ? "ghost" : ""}" data-i="${i}">${esc(o.label)}</button>`).join("")}
      <button class="btn ghost" data-i="-1">Annuler</button></div>`;
    el.hidden = false;
    el.onclick = (e) => {
      const b = e.target.closest("button");
      if (!b && e.target !== el) return;
      el.hidden = true;
      const i = b ? Number(b.dataset.i) : -1;
      resolve(i >= 0 ? options[i].value : null);
    };
  });
}

// --- dictée (enregistrement → transcription sur le serveur) ---

let recorder = null;
async function dictate(btn, textarea) {
  if (recorder) { recorder.stop(); return; }
  if (!navigator.mediaDevices || !window.MediaRecorder) { toast("Dictée indisponible ici : utilise le micro du clavier."); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch { toast("Autorise le micro pour dicter."); return; }
  const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
  const chunks = [];
  recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : {});
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    recorder = null;
    btn.classList.remove("rec");
    btn.disabled = true;
    toast("Je transcris ta dictée…", 20000);
    try {
      const fd = new FormData();
      fd.append("audio", new Blob(chunks, { type: chunks[0]?.type || "audio/webm" }), "dictee.webm");
      const r = await api("/api/dictate", { method: "POST", body: fd });
      if (r.text) {
        textarea.value = (textarea.value.trim() ? textarea.value.trim() + " " : "") + r.text;
        textarea.dispatchEvent(new Event("input"));
      }
      toast(r.text ? "Dictée ajoutée" : "Je n'ai rien entendu");
    } catch (e) { toast(e.message); }
    btn.disabled = false;
  };
  recorder.start();
  btn.classList.add("rec");
  toast("J'écoute… touche encore pour arrêter", 4000);
}

function autoGrow(ta) {
  ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 160) + "px"; });
}

// --- connexion ---

function showLogin() {
  clearInterval(pollTimer);
  $("#who").hidden = true;
  view.innerHTML = `
    <form class="login" id="login">
      <h1>Bienvenue dans le Studio</h1>
      <p class="lead">Un réel, un post, un mail qui t'inspire devient un script à la façon de Nina.</p>
      <div class="field"><label for="name">Ton prénom</label><input class="input" id="name" autocomplete="given-name" required></div>
      <div class="field"><label for="code">Code d'équipe</label><input class="input" id="code" type="password" autocomplete="current-password" required></div>
      <button class="btn big">Entrer</button>
    </form>`;
  $("#login").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData();
    fd.append("name", $("#name").value);
    fd.append("code", $("#code").value);
    try {
      await api("/api/login", { method: "POST", body: fd });
      await loadMe();
      route();
    } catch (err) { toast(err.message); }
  };
}

async function loadMe() {
  me = await api("/api/me");
  const who = $("#who");
  who.textContent = me.name;
  who.hidden = false;
  who.onclick = async () => {
    const r = await sheet(`Connectée en tant que ${me.name}`, [{ label: "Réglages", value: "settings" },
      { label: "Se déconnecter", value: "out", ghost: true }]);
    if (r === "settings") location.hash = "#/reglages";
    if (r === "out") { await api("/api/logout", { method: "POST" }); showLogin(); }
  };
}

// --- bibliothèque ---

function itemCard(it) {
  const title = it.title || (it.source_url ? domain(it.source_url) : (it.instructions || "Contenu").slice(0, 60));
  let status = "";
  if (ACTIVE.includes(it.status)) status = `<span class="badge work">${esc(it.progress || "En cours…")}</span>`;
  else if (it.status === "error") status = `<span class="badge err">Erreur</span>`;
  const fmt = it.output_format ? `<span class="badge">${esc(KIND_LABEL[it.output_format] || it.output_format)}</span>` : "";
  return `<a class="card" href="#/c/${it.id}">
    <div class="card-title">${esc(title)}</div>
    <div class="card-meta">${fmt}${status}<span>${esc(PLATFORM_LABEL[it.platform] || "")}</span>
    <span>${esc(it.author)} · ${timeAgo(it.created_at)}</span></div></a>`;
}

function renderList() {
  view.innerHTML = `
    <div class="search"><input class="input" id="q" type="search" placeholder="Rechercher un script, un sujet…"></div>
    <div class="tabs"><button class="chip on" data-mine="0">Toute l'équipe</button><button class="chip" data-mine="1">Les miens</button></div>
    <div class="list" id="list"><div class="empty">Chargement…</div></div>
    <a class="btn fab" href="#/nouveau">+ Nouveau</a>`;
  let mine = false, q = "", t;
  const load = async () => {
    const items = await api(`/api/items?q=${encodeURIComponent(q)}&mine=${mine}`);
    const list = $("#list");
    if (!list) return;
    list.innerHTML = items.length ? items.map(itemCard).join("")
      : `<div class="empty">${q ? "Rien trouvé." : "Rien pour l'instant.<br>Partage un réel depuis Instagram ou touche « + Nouveau »."}</div>`;
    clearInterval(pollTimer);
    if (items.some((i) => ACTIVE.includes(i.status))) pollTimer = setInterval(load, 5000);
  };
  $("#q").oninput = (e) => { q = e.target.value; clearTimeout(t); t = setTimeout(load, 300); };
  view.querySelectorAll(".tabs .chip").forEach((b) => (b.onclick = () => {
    view.querySelectorAll(".tabs .chip").forEach((x) => x.classList.toggle("on", x === b));
    mine = b.dataset.mine === "1";
    load();
  }));
  load().catch((e) => e.message !== "auth" && toast(e.message));
}

// --- nouveau contenu ---

async function renderNew() {
  let format = "auto";
  let files = [];
  let draft = null;
  if (state.draftId) {
    try { draft = await api(`/api/drafts/${state.draftId}`); } catch { draft = null; }
  }
  view.innerHTML = `
    <h1>Nouveau contenu</h1>
    <div class="field">
      <label for="url">Lien du réel, du post ou de la vidéo</label>
      <div class="row"><input class="input" id="url" inputmode="url" placeholder="https://www.instagram.com/reel/…">
      <button class="icon-btn" id="paste" type="button" title="Coller">${ICON.paste}</button></div>
      <div class="files" id="files"></div>
      <div class="row" style="margin-top:10px;gap:16px;flex-wrap:wrap">
        <button class="disclose" id="addFiles" type="button">+ Ajouter des captures ou une vidéo</button>
        <button class="disclose" id="showText" type="button">+ Coller un texte (mail, post…)</button>
      </div>
      <input type="file" id="fileInput" accept="image/*,video/*,audio/*" multiple hidden>
    </div>
    <div class="field" id="textField" hidden>
      <label for="text">Texte à réécrire</label>
      <textarea class="input" id="text" rows="6" placeholder="Colle ici le mail ou le post qui t'inspire"></textarea>
    </div>
    <div class="field">
      <label>Je veux</label>
      <div class="chips" id="formats">${FORMATS.map(([v, l]) => `<button type="button" class="chip ${v === "auto" ? "on" : ""}" data-v="${v}">${l}</button>`).join("")}</div>
      <div class="hint">« Auto » garde le format de la source : un réel devient un script de réel.</div>
    </div>
    <div class="field">
      <label for="instr">Ton commentaire (facultatif)</label>
      <div class="row"><textarea class="input" id="instr" rows="3" placeholder="CTA, angle, cible, « traduis mot à mot »… écris ou dicte"></textarea>
      <button class="icon-btn" id="mic" type="button" title="Dicter">${ICON.mic}</button></div>
    </div>
    <button class="btn big" id="go">Lancer</button>`;

  const urlIn = $("#url"), textIn = $("#text");
  const showFiles = () => {
    const names = [...(draft?.files || []).map((f) => f.replace(/^\d+_/, "")), ...files.map((f) => f.name)];
    $("#files").innerHTML = names.map((n) => `<span class="file-pill">${esc(n)}</span>`).join("");
  };
  if (draft) {
    urlIn.value = draft.url || "";
    if (draft.text) { $("#textField").hidden = false; textIn.value = draft.text; }
    showFiles();
  }
  $("#paste").onclick = async () => {
    try { const t = await navigator.clipboard.readText(); urlIn.value = extractUrl(t) || t; }
    catch { toast("Colle le lien à la main (appui long dans le champ)."); }
  };
  $("#addFiles").onclick = () => $("#fileInput").click();
  $("#fileInput").onchange = (e) => { files = [...files, ...e.target.files]; showFiles(); };
  $("#showText").onclick = () => { $("#textField").hidden = false; textIn.focus(); };
  $("#formats").onclick = (e) => {
    const b = e.target.closest(".chip");
    if (!b) return;
    format = b.dataset.v;
    $("#formats").querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", x === b));
  };
  autoGrow($("#instr"));
  $("#mic").onclick = () => dictate($("#mic"), $("#instr"));
  $("#go").onclick = async () => {
    const raw = urlIn.value.trim();
    const url = raw.startsWith("http") ? raw : extractUrl(raw);
    if (!url && !textIn.value.trim() && !files.length && !draft?.files?.length) {
      toast("Mets un lien, un texte ou des fichiers.");
      return;
    }
    const fd = new FormData();
    fd.append("url", url || "");
    fd.append("text", textIn.value);
    fd.append("instructions", $("#instr").value);
    fd.append("format", format);
    if (draft) fd.append("draft", draft.id);
    files.forEach((f) => fd.append("files", f, f.name));
    $("#go").disabled = true;
    $("#go").textContent = files.length ? "Envoi des fichiers…" : "C'est parti…";
    try {
      const r = await api("/api/items", { method: "POST", body: fd });
      state.draftId = null;
      history.replaceState(null, "", "/" + `#/c/${r.id}`);
      route();
    } catch (e) {
      toast(e.message);
      $("#go").disabled = false;
      $("#go").textContent = "Lancer";
    }
  };
  if (!draft) urlIn.focus();
}

// --- un contenu et son fil ---

function outCard(m, item) {
  if (m.status === "pending") {
    return `<div class="out pending"><div class="out-body"><div class="spinner"></div>J'écris…</div></div>`;
  }
  if (m.status === "error") return `<div class="error-box">${esc(m.content)}</div>`;
  const raw = m.kind === "reel" || (m.kind === "version" && item.output_format === "reel");
  const slackBtn = me?.slack?.length ? `<button class="btn ghost small" data-slack="${m.id}">Partager sur Slack</button>` : "";
  return `<div class="out">
    <div class="out-head"><span class="badge">${esc(KIND_LABEL[m.kind] || "Proposition")}</span><span class="small muted">${timeAgo(m.created_at)}</span></div>
    <div class="out-body ${raw ? "raw" : ""}">${raw ? esc(m.content) : md(m.content)}</div>
    ${m.note ? `<div class="out-note">À vérifier : ${esc(m.note)}</div>` : ""}
    <div class="out-foot"><button class="btn ghost small" data-copy="${m.id}">Copier</button>${slackBtn}</div>
  </div>`;
}

function renderThread(item) {
  const parts = [];
  if (item.instructions) parts.push(`<div class="bubble"><span class="by">${esc(item.author)}</span>${esc(item.instructions)}</div>`);
  if (ACTIVE.includes(item.status)) {
    parts.push(`<div class="progress"><div class="spinner"></div><div><strong>${esc(item.progress || "En cours…")}</strong>
      <div class="small muted">Compte une à trois minutes. Tu peux fermer l'appli, ça continue.</div></div></div>`);
  }
  if (item.status === "error") {
    parts.push(`<div class="error-box">${esc(item.error || "Erreur")}<div style="margin-top:10px"><button class="btn small" id="retry">Réessayer</button></div></div>`);
  }
  for (const m of item.messages) {
    parts.push(m.role === "user" ? `<div class="bubble"><span class="by">${esc(m.author)}</span>${esc(m.content)}</div>` : outCard(m, item));
  }
  if (state.showAnalysis && item.analysis) {
    parts.push(`<div class="out analysis"><div class="out-head"><span class="badge">Pourquoi ça marche</span></div><div class="out-body">${md(item.analysis)}</div></div>`);
  }
  return parts.join("");
}

async function renderItem(id) {
  state.showAnalysis = false;
  view.innerHTML = `<div id="itemView"><div class="empty">Chargement…</div></div>`;
  let item = null, sig = "";

  const draw = () => {
    const busy = item.messages.some((m) => m.status === "pending");
    const src = item.source || {};
    const meta = [PLATFORM_LABEL[item.platform] || "", src.author ? `@${String(src.author).replace(/^@/, "")}` : "",
      `déposé par ${item.author} · ${timeAgo(item.created_at)}`].filter(Boolean).join(" · ");
    $("#itemView").innerHTML = `
      <div class="src">
        <h2>${esc(item.title || (ACTIVE.includes(item.status) ? "En préparation…" : "Contenu"))}</h2>
        ${item.source_url ? `<a href="${esc(item.source_url)}" target="_blank" rel="noopener">${esc(item.source_url)}</a>` : ""}
        <div class="small muted">${esc(meta)}</div>
      </div>
      <div class="thread" id="thread">${renderThread(item)}</div>
      ${item.status === "ready" ? `<div class="actions chips">
        <button class="chip" data-act="version" ${busy ? "disabled" : ""}>Autre version</button>
        <button class="chip" data-act="hooks" ${busy ? "disabled" : ""}>Accroches</button>
        <button class="chip" data-act="caption" ${busy ? "disabled" : ""}>Légende</button>
        <button class="chip" data-act="format" ${busy ? "disabled" : ""}>Transformer en…</button>
        ${item.analysis ? `<button class="chip ${state.showAnalysis ? "on" : ""}" data-act="analysis">Pourquoi ça marche</button>` : ""}
        <button class="chip" data-act="archive">Archiver</button>
      </div>` : ""}`;
    const composer = $("#composer");
    if (composer) composer.hidden = item.status !== "ready";
  };

  const load = async () => {
    item = await api(`/api/items/${id}`);
    const s = JSON.stringify([item.status, item.progress, item.messages.map((m) => [m.id, m.status, m.content.length])]);
    if (s !== sig) { sig = s; draw(); }
    const active = ACTIVE.includes(item.status) || item.messages.some((m) => m.status === "pending");
    clearInterval(pollTimer);
    if (active) pollTimer = setInterval(() => load().catch(() => {}), 2500);
  };

  // Barre de commentaire, fixe en bas de l'écran
  view.insertAdjacentHTML("beforeend", `
    <div class="composer" id="composer" hidden><div class="row">
      <textarea class="input" id="say" rows="1" placeholder="Ton retour : plus court, autre CTA, vise la Cure…"></textarea>
      <button class="icon-btn" id="sayMic" title="Dicter">${ICON.mic}</button>
      <button class="icon-btn" id="send" title="Envoyer" style="background:var(--rose);color:#fff;border-color:var(--rose)">${ICON.send}</button>
    </div></div>`);
  autoGrow($("#say"));
  $("#sayMic").onclick = () => dictate($("#sayMic"), $("#say"));

  const run = async (body) => {
    try {
      await postJSON(`/api/items/${id}/actions`, body);
      await load();
      setTimeout(() => window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }), 50);
    } catch (e) { toast(e.message); }
  };
  $("#send").onclick = async () => {
    const text = $("#say").value.trim();
    if (!text) { toast("Écris ou dicte ton retour."); return; }
    $("#say").value = "";
    $("#say").style.height = "auto";
    run({ action: "comment", text });
  };

  view.onclick = async (e) => {
    const b = e.target.closest("button");
    if (!b || !item) return;
    if (b.id === "retry") { await postJSON(`/api/items/${id}/retry`, {}); sig = ""; load(); return; }
    if (b.dataset.copy) { const m = item.messages.find((x) => x.id === b.dataset.copy); if (m) copy(m.content); return; }
    if (b.dataset.slack) {
      const dest = await sheet("Partager sur Slack", me.slack.map((d) => ({ label: d, value: d })));
      if (!dest) return;
      try { await postJSON(`/api/items/${id}/slack`, { message_id: b.dataset.slack, destination: dest }); toast(`Envoyé à ${dest}`); }
      catch (err) { toast(err.message, 5000); }
      return;
    }
    const act = b.dataset.act;
    if (!act) return;
    if (act === "analysis") { state.showAnalysis = !state.showAnalysis; draw(); return; }
    if (act === "archive") {
      const ok = await sheet("Archiver ce contenu ?", [{ label: "Archiver", value: true }]);
      if (ok) { await postJSON(`/api/items/${id}/archive`, {}); location.hash = "#/"; }
      return;
    }
    if (act === "caption") {
      const platform = await sheet("Légende pour…", [{ label: "Instagram", value: "instagram" },
        { label: "Facebook", value: "facebook" }, { label: "LinkedIn", value: "linkedin" }]);
      if (platform) run({ action: "caption", platform });
      return;
    }
    if (act === "format") {
      const f = await sheet("Transformer en…", FORMATS.filter(([v]) => v !== "auto").map(([v, l]) => ({ label: l, value: v })));
      if (f) run({ action: "format", format: f, format_label: FORMATS.find(([v]) => v === f)[1] });
      return;
    }
    run({ action: act });
  };

  try { await load(); } catch (e) { if (e.message !== "auth") $("#itemView").innerHTML = `<div class="error-box">${esc(e.message)}</div>`; }
}

// --- réglages ---

async function renderSettings() {
  view.innerHTML = `<div class="settings">
    <a href="#/" class="back">← Retour</a>
    <h1 class="settings-title">Réglages</h1>
    <section class="settings-card">
      <h2>Récupération Instagram et Facebook (Apify)</h2>
      <p class="hint">Instagram et Facebook bloquent le serveur du Studio. Apify récupère les réels et les posts à sa place.
        Sans clé, les liens Instagram risquent de ne pas marcher (les captures, le texte et les fichiers marchent toujours).</p>
      <div id="apify-status" class="status-line">Chargement…</div>
      <div class="field">
        <label for="apify">Ta clé Apify</label>
        <input class="input" id="apify" type="password" autocomplete="off" placeholder="apify_api_…">
      </div>
      <p class="hint">Où la trouver : sur <a href="https://console.apify.com/settings/integrations" target="_blank" rel="noopener">console.apify.com</a>,
        menu <strong>Settings</strong> puis <strong>API &amp; Integrations</strong>, bouton copier à côté de <strong>Personal API token</strong>.</p>
      <div class="settings-actions">
        <button class="btn" id="apify-save">Enregistrer la clé</button>
        <button class="btn ghost small" id="apify-remove" hidden>Retirer la clé</button>
      </div>
    </section>
  </div>`;
  const show = (st) => {
    $("#apify-status").innerHTML = st.apify
      ? `<span class="badge ok">Branchée</span> clé se terminant par <strong>…${esc(st.apify_end)}</strong>`
      : `<span class="badge err">Pas encore branchée</span>`;
    $("#apify-remove").hidden = !st.apify;
  };
  try { show(await api("/api/settings")); } catch (e) { if (e.message !== "auth") toast(e.message); }
  $("#apify-save").onclick = async () => {
    const token = $("#apify").value.trim();
    if (!token) return toast("Colle d'abord ta clé dans la case.");
    const b = $("#apify-save"); b.disabled = true; b.textContent = "Vérification auprès d'Apify…";
    try { show(await postJSON("/api/settings/apify", { token })); $("#apify").value = ""; toast("Clé enregistrée, Apify est branché."); }
    catch (e) { if (e.message !== "auth") toast(e.message, 4000); }
    finally { b.disabled = false; b.textContent = "Enregistrer la clé"; }
  };
  $("#apify-remove").onclick = async () => {
    const ok = await sheet("Retirer la clé Apify ?", [{ label: "Retirer", value: true }]);
    if (!ok) return;
    try { show(await postJSON("/api/settings/apify", { token: "" })); toast("Clé retirée."); } catch (e) { toast(e.message); }
  };
}

// --- navigation ---

function route() {
  clearInterval(pollTimer);
  view.onclick = null;
  const h = location.hash || "#/";
  window.scrollTo(0, 0);
  if (h.startsWith("#/c/")) return renderItem(h.slice(4));
  if (h.startsWith("#/nouveau")) return renderNew();
  if (h.startsWith("#/reglages")) return renderSettings();
  return renderList();
}

window.addEventListener("hashchange", () => me && route());

(async function init() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  try {
    await loadMe();
    route();
  } catch (e) {
    if (e.message !== "auth") view.innerHTML = `<div class="error-box">Le Studio ne répond pas : ${esc(e.message)}</div>`;
  }
})();
