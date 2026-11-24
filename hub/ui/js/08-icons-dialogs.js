// ---- dialogues : bouton ×, clic sur le fond, onglets des réglages
document.querySelectorAll('[data-ic]').forEach(e=>e.replaceWith(ih(IC[e.dataset.ic])));
document.querySelectorAll('[data-fwd]').forEach(b=>b.onclick=()=>{closeDrops();document.getElementById(b.dataset.fwd).click()});
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>document.getElementById(b.dataset.close).close());
document.querySelectorAll('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d)d.close()}));
document.querySelectorAll('#dset .seg button').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('#dset .seg button').forEach(x=>x.classList.toggle('on',x===b));
  document.querySelectorAll('#dset section[data-sec]').forEach(x=>x.classList.toggle('on',x.dataset.sec===b.dataset.sec));
});

/* ===================== refonte v3 : icônes, vues, pages, panneau de droite ===================== */
const _svg=(d,x)=>'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'+(x||'')+'>'+d+'</svg>';
const ICN={
  hub:_svg('<path d="M4 5.5h16v11H10l-4.5 3.5v-3.5H4z"/><path d="M8 10h8M8 13h5"/>'),
  chat:_svg('<path d="M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4.2A8 8 0 1 1 20 12z"/>'),
  stats:_svg('<path d="M6 20V11M12 20V5M18 20v-6"/>'),
  hist:_svg('<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5"/><path d="M3.5 4v4.5H8M12 7.5V12l3 2"/>'),
  log:_svg('<rect x="4" y="3.5" width="16" height="17" rx="3"/><path d="M8 9h8M8 13h8M8 17h4"/>'),
  shield:_svg('<path d="M12 2.6 4.4 5.5v5.6c0 4.7 3.2 8.6 7.6 10.1 4.4-1.5 7.6-5.4 7.6-10.1V5.5z"/><path d="m8.6 12 2.5 2.5 4.4-4.8"/>'),
  gear:_svg('<circle cx="12" cy="12" r="3.2"/><path d="M19.4 13a7.9 7.9 0 0 0 0-2l2-1.5-2-3.4-2.4 1a7.7 7.7 0 0 0-1.7-1L15 3.5h-4l-.4 2.6a7.7 7.7 0 0 0-1.7 1l-2.4-1-2 3.4 2 1.5a7.9 7.9 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a7.7 7.7 0 0 0 1.7 1l.4 2.6h4l.4-2.6a7.7 7.7 0 0 0 1.7-1l2.4 1 2-3.4z"/>'),
  help:_svg('<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.1.9-1.1 1.8M12 17v.1"/>'),
  bell:_svg('<path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>'),
  out:_svg('<path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M10 16l-4-4 4-4M6 12h10"/>'),
  bolt:_svg('<path d="M13.6 2.5 5 13.5h6l-1 8 8.6-11h-6z"/>'),
  pause:_svg('<path d="M9 5v14M15 5v14"/>'),
  draft:_svg('<path d="M4 20h4L19 9l-4-4L4 16z"/>'),
  send:_svg('<path d="M21 3 10 14M21 3l-7 18-4-7-7-4z"/>'),
  lock:_svg('<rect x="5" y="10.5" width="14" height="9.5" rx="2.5"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>'),
  user:_svg('<circle cx="12" cy="8" r="3.6"/><path d="M4.5 20c.8-3.6 3.8-5.5 7.5-5.5s6.7 1.9 7.5 5.5"/>'),
  palette:_svg('<path d="M12 3a9 9 0 1 0 0 18c1.2 0 1.8-.8 1.8-1.6 0-1.4-1.2-1.4-1.2-2.6 0-1 .9-1.6 2-1.6H17a4 4 0 0 0 4-4C21 6.7 17 3 12 3z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7.5" r="1"/><circle cx="14.5" cy="7.5" r="1"/>'),
  info:_svg('<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.8v.1"/>'),
  chev:_svg('<path d="m9 6 6 6-6 6"/>'),
  eye:_svg('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>'),
  key:_svg('<circle cx="8" cy="15" r="4"/><path d="m11 12 8-8M16 7l3 3"/>'),
  link:_svg('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'),
  dl:_svg('<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>'),
};
function hydrate(root){(root||document).querySelectorAll('[data-i]').forEach(e=>{const sv=ICN[e.dataset.i];if(!sv)return;if(e.className){e.innerHTML=sv;e.removeAttribute('data-i')}else{const n=ih(sv);n.classList.add('ic');e.replaceWith(n)}})}
hydrate();

