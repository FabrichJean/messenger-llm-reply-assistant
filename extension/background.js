// Relais Connect — service worker.
// Rôle : quand TON hub le demande (code à usage unique), lire la session Messenger de TON navigateur et l'envoyer à TON hub.
// Il ne stocke rien (sauf, le temps de la connexion, le code en attente) et ne lit que les cookies de Messenger.
importScripts("config.js");   // CFG = { hub, loginUrl, cookieUrl } (écrit par ton hub au téléchargement)

const NEED = ["c_user", "xs", "datr"];
const KEEP = ["c_user", "xs", "datr", "sb", "fr", "wd", "presence", "dpr", "oo"];

async function pending() { return (await chrome.storage.session.get("p")).p || null; }
async function setPending(p) { await chrome.storage.session.set({ p }); }
async function clearPending() { await chrome.storage.session.remove("p"); }

async function jar() {
  const cs = await chrome.cookies.getAll({ url: CFG.cookieUrl });
  const m = {};
  for (const c of cs) if (KEEP.includes(c.name) && c.value) m[c.name] = c.value;
  return NEED.every((k) => m[k]) ? m : null;
}

function say(tabId, msg) { try { chrome.tabs.sendMessage(tabId, msg).catch(() => {}); } catch (e) { /* onglet fermé */ } }

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (!msg || msg.t !== "connect" || typeof msg.code !== "string") return;
  // uniquement depuis la page de TON hub
  if (!sender.tab || !sender.url || new URL(sender.url).origin !== CFG.hub) return;
  start(msg.code, sender.tab.id);
});

async function start(code, hubTab) {
  await setPending({ code, hubTab, t0: Date.now(), tab: null, rejected: "" });
  chrome.alarms.create("relais-expire", { delayInMinutes: 10 });
  const j = await jar();
  if (j) {   // déjà connecté à Messenger dans ce navigateur : un seul clic, rien à saisir
    say(hubTab, { t: "progress", step: "Session Messenger trouvée dans ton navigateur…" });
    await send(j);
    return;
  }
  const tab = await chrome.tabs.create({ url: CFG.loginUrl, active: true });
  const p = await pending(); if (p) { p.tab = tab.id; await setPending(p); }
  say(hubTab, { t: "progress", step: "Messenger est ouvert dans un nouvel onglet : connecte-toi." });
}

let inflight = false;     // verrou SYNCHRONE : plusieurs événements de cookies arrivent presque ensemble, un seul envoi doit partir
let settleTimer = null;

async function send(j) {
  if (inflight) return;
  inflight = true;
  try { await doSend(j); } finally { inflight = false; }
}

async function doSend(j) {
  const p = await pending();
  if (!p) return;
  p.sending = true; await setPending(p);
  let res = { ok: false, error: "Le hub ne répond pas." };
  try {
    const cookies = Object.entries(j).map(([k, v]) => k + "=" + v).join("; ");
    const r = await fetch(CFG.hub + "/api/accounts/import_ext", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Hub": "1" },
      body: JSON.stringify({ code: p.code, cookies }), cache: "no-store"
    });
    const d = await r.json().catch(() => ({}));
    res = d && d.ok ? { ok: true, name: d.name, reused: d.reused } : { ok: false, error: (d && d.error) || ("Le hub a refusé la connexion (" + r.status + ").") };
  } catch (e) { /* hub injoignable */ }
  const q = await pending() || p;
  if (res.ok) {
    await clearPending();
    chrome.alarms.clear("relais-expire");
    if (q.tab) chrome.tabs.remove(q.tab).catch(() => {});   // l'onglet de connexion que nous avions ouvert
    chrome.tabs.update(q.hubTab, { active: true }).catch(() => {});
    say(q.hubTab, { t: "result", ...res });
  } else {
    // session refusée (périmée ?) : on attend une NOUVELLE session (autre valeur de « xs ») en ouvrant Messenger
    q.sending = false; q.rejected = j.xs;
    await setPending(q);
    say(q.hubTab, { t: "result", ok: false, error: res.error });
    if (!q.tab) {
      const tab = await chrome.tabs.create({ url: CFG.loginUrl, active: true });
      q.tab = tab.id; await setPending(q);
    }
  }
}

// une session apparaît pendant que l'utilisateur se connecte dans l'onglet Messenger
chrome.cookies.onChanged.addListener(async (ch) => {
  if (ch.removed || !NEED.concat(["xs"]).includes(ch.cookie.name)) return;
  if (inflight || settleTimer) return;
  const p = await pending();
  if (!p || p.sending) return;
  const j = await jar();
  if (!j || j.xs === p.rejected) return;
  settleTimer = setTimeout(async () => {   // laisse les cookies se stabiliser (rotation juste après la connexion)
    settleTimer = null;
    const p2 = await pending(); if (!p2 || p2.sending) return;
    const j2 = await jar();
    if (j2 && j2.xs !== p2.rejected) send(j2);
  }, 4000);
});

chrome.alarms.onAlarm.addListener(async (a) => {
  if (a.name !== "relais-expire") return;
  const p = await pending();
  if (p) { say(p.hubTab, { t: "result", ok: false, error: "Délai dépassé : relance la connexion depuis le hub." }); await clearPending(); }
});
