// Relais Connect — script de page (uniquement sur ton hub). Il fait le lien entre la page du hub et l'extension.
// Il ne lit rien d'autre : la page envoie un code à usage unique, l'extension renvoie seulement le résultat.
document.documentElement.dataset.relaisExt = "1";   // « l'extension est installée »

window.addEventListener("message", (e) => {
  if (e.source !== window || e.origin !== location.origin) return;
  const d = e.data;
  if (d && d.relais === "connect" && typeof d.code === "string" && d.code.length < 200) {
    chrome.runtime.sendMessage({ t: "connect", code: d.code });
  }
});

chrome.runtime.onMessage.addListener((m) => {
  if (m && m.t === "result") window.postMessage({ relais: "result", ok: !!m.ok, name: m.name || "", error: m.error || "", reused: !!m.reused }, location.origin);
  if (m && m.t === "progress") window.postMessage({ relais: "progress", step: String(m.step || "") }, location.origin);
});
