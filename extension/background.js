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
