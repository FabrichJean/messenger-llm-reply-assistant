async function api(path,body){
  const r=await fetch(path,body?{method:'POST',headers:{'X-Hub':'1','Content-Type':'application/json'},body:JSON.stringify(body)}:{});
  if(r.status===401){location.href='/login';throw new Error('session expirée')}
  return r.json();
}
let S=null, sel=null, chatCache=null, dirty=false;
function initials(c){const n=(c.name||'').trim();if(!n||/^\d+$/.test(n))return '#';const p=n.split(/\s+/);return ((p[0][0]||'')+(p.length>1?(p[p.length-1][0]||''):'')).toUpperCase()}
function placeholder(c,cls){let h=0;for(const ch of (c.name||c.key))h=(h*31+ch.charCodeAt(0))%360;const d=el('div',{className:'av '+cls,textContent:initials(c)});d.style.background=`hsl(${h} 38% 34%)`;return d}
function avatar(c,cls=''){
  if(!c.pic)return placeholder(c,cls);
  const img=el('img',{className:'av '+cls,alt:'',loading:'lazy',src:'/api/avatar?key='+encodeURIComponent(c.key)+'&v='+c.pic});
  img.onerror=()=>img.replaceWith(placeholder(c,cls));
  return img;
}
const fmt=ts=>{if(!ts)return'';const d=new Date(ts),n=new Date();if(d.toDateString()===n.toDateString())return d.toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'});if(d.toDateString()===new Date(Date.now()-864e5).toDateString())return'Hier';return d.toLocaleDateString('fr-FR',{day:'2-digit',month:'2-digit'})};

function histInfo(){const sel=$('#h_acc');const a=(sel&&sel.value&&S.accounts.find(x=>x.name===sel.value))||S.accounts.find(x=>x.history)||S.accounts[0]||{};return {state:a.history||'inconnu',err:a.history_err||'',att:a.history_attempts}}
function renderHist(){
  const h=histInfo(),b=$('#bhist');
  const lab={enrolled:'Historique chiffré actif',enrolling:'Restauration en cours…'}[h.state]||'Historique chiffré';
  b.title=lab;
  const m={enrolled:'Accès restauré : « Importer l\'historique » fonctionne aussi sur les conversations chiffrées.',enrolling:'Restauration en cours, patiente quelques secondes…',backup_available:'Une sauvegarde par PIN existe sur ton compte.',no_backup:'Aucune sauvegarde par PIN trouvée sur ton compte : l\'historique chiffré n\'est pas récupérable.',error:'Échec : '+h.err+(h.att!=null?' — '+h.att+' essai(s) restant(s).':''),'inconnu':'État inconnu (canal chiffré pas encore connecté ?).'}[h.state]||'';
  $('#h_status').textContent=m;
  $('#h_status').style.color=h.state==='error'?'var(--bad)':'var(--muted)';
  const can=h.state==='backup_available'||h.state==='error';
  $('#h_form').style.display=can?'block':'none';$('#h_go').style.display=can?'inline-block':'none';
}
const LS=(k,v)=>{try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}};
function toggleCset(){LS('hub_cset',LS('hub_cset')==='1'?'0':'1');applyView()}
function applyView(){
  const cs=LS('hub_cset')==='1';
  const c=$('#cset');if(c)c.classList.toggle('open',cs);
}
const taskEls={};
const IC_TASK={run:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 3a9 9 0 1 0 9 9" /></svg>',done:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12.500 3 3 5-6"/></svg>',err:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7.500v5M12 16v.1"/></svg>'};
function renderTasks(){
  const box=floater().querySelector('#tasks');const ids=new Set();const now=Date.now();
  for(const t of (S.tasks||[])){
    ids.add(t.id);let e=taskEls[t.id];
    if(!e){const root=el('div',{className:'tk run'}),ic=el('span',{className:'ic'}),tt=el('span',{className:'tt'}),ct=el('span',{className:'ct'}),dt=el('div',{className:'dt'}),bar=el('div',{className:'bar ind'},el('i'));
      root.append(el('div',{className:'h'},ic,tt,ct),dt,bar);e=taskEls[t.id]={root,ic,tt,ct,dt,bar,st:''};box.append(root)}
    const secs=Math.max(0,Math.round(((t.ended||now)-t.started)/1000));
    e.tt.textContent=t.state==='error'?t.label+' : échec':t.state==='done'?t.label+' : terminé':t.label;
    e.dt.textContent=t.state==='error'?(t.error||''):t.detail||'';e.dt.style.display=e.dt.textContent?'':'none';
    e.ct.textContent=(t.total&&t.state==='running'?t.done+' / '+t.total+' · ':'')+secs+' s';
    if(e.st!==t.state){e.st=t.state;e.root.className='tk '+(t.state==='running'?'run':t.state==='done'?'done':'err');e.ic.innerHTML=IC_TASK[t.state==='running'?'run':t.state==='done'?'done':'err']}
    const det=t.total>0||t.state!=='running';e.bar.classList.toggle('ind',!det);
    e.bar.firstChild.style.width=det?(t.state==='running'?Math.min(100,Math.round(t.done/Math.max(1,t.total)*100)):100)+'%':'';
  }
  for(const id in taskEls)if(!ids.has(id)){taskEls[id].root.remove();delete taskEls[id]}
}
const IC={
  search:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/></svg>',
  pin:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6l-1 6 3 3H7l3-3z"/><path d="M12 12v8"/></svg>',
  trash:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 7V4h4v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/></svg>',
  more:'<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5.5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="18.5" cy="12" r="1.8"/></svg>',
  chev:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>',
  smile:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M8.500 14c1 1.300 2.100 2 3.500 2s2.500-.7 3.500-2"/><circle cx="9" cy="10" r=".8" fill="currentColor"/><circle cx="15" cy="10" r=".8" fill="currentColor"/></svg>',
  clip:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11.500 12 19.500a5 5 0 0 1-7-7l8-8a3.300 3.300 0 0 1 4.700 4.700l-8 8a1.700 1.700 0 0 1-2.400-2.400l7.300-7.300"/></svg>',
  img:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3.500" y="4.500" width="17" height="15" rx="3"/><circle cx="9" cy="10" r="1.600"/><path d="m4 17 5-4.500 4 3.500 3-2.500 4 3.500"/></svg>',
  pencil:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4L19 9l-4-4L4 16z"/></svg>',
  eye:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  spark:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3c.6 5 3.900 8.400 9 9-5.100.6-8.400 4-9 9-.6-5-3.900-8.400-9-9 5.100-.6 8.400-4 9-9z"/></svg>',
  hist:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.500 12a8.500 8.500 0 1 0 2.600-6.100L3.500 8.500"/><path d="M3.500 4v4.500H8M12 7.500V12l3 2"/></svg>',
  refresh:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11a8 8 0 0 0-14.500-3.500L4 9M4 13a8 8 0 0 0 14.500 3.500L20 15"/><path d="M4 4v5h5M20 20v-5h-5"/></svg>',
  user:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="8" r="3.500"/><path d="M5 20c.7-3.700 3.500-5.500 7-5.500s6.300 1.800 7 5.500"/></svg>',
  theme:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.500"/><path d="M12 3.500v17a8.500 8.500 0 0 0 0-17z" fill="currentColor"/></svg>',
  gear:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"><circle cx="12" cy="12" r="3.200"/><path d="M19.400 13a7.900 7.900 0 0 0 0-2l2-1.500-2-3.400-2.400 1a7.700 7.700 0 0 0-1.700-1L15 3.500h-4l-.4 2.600a7.700 7.700 0 0 0-1.700 1l-2.400-1-2 3.400 2 1.500a7.900 7.900 0 0 0 0 2l-2 1.500 2 3.400 2.400-1c.5.400 1.100.7 1.700 1l.4 2.600h4l.4-2.600c.6-.3 1.200-.6 1.700-1l2.400 1 2-3.400z"/></svg>',
  file:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/></svg>',
  mappin:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 21s-6.500-6-6.500-11a6.500 6.500 0 0 1 13 0c0 5-6.500 11-6.500 11z"/><circle cx="12" cy="10" r="2.300"/></svg>',
  bolt:'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13.600 2 4.800 13.600h6.300L9.900 22l8.900-12.200h-6.400z"/></svg>',
  send:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 3 3 10.500l6.500 2.500L12 20z"/><path d="m21 3-11.500 10"/></svg>',
  check2:'<svg class="ck" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m2 12.500 4.500 4.500L14 8.500M10 15l1.500 1.500L20 7.500"/></svg>',
  pause:'<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1.200"/><rect x="14" y="5" width="4" height="14" rx="1.200"/></svg>',
  play:'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.500v15l12-7.500z"/></svg>',
};
const ih=(h)=>{const t=document.createElement('template');t.innerHTML=h.trim();return t.content.firstChild};
const hm=ts=>new Date(ts).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'});
const dayLabel=ts=>{const d=new Date(ts),n=new Date(),y=new Date(Date.now()-864e5);return d.toDateString()===n.toDateString()?"Aujourd'hui":d.toDateString()===y.toDateString()?'Hier':d.toLocaleDateString('fr-FR',{weekday:'long',day:'numeric',month:'long'})};
let tab='all';
function closeDrops(except){document.querySelectorAll('.drop.open').forEach(d=>{if(d!==except)d.classList.remove('open')})}
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeDrops();const em=document.getElementById('emojis');if(em)em.classList.remove('open')}});
document.addEventListener('click',e=>{
  if(!e.target.closest('#emojis')&&!e.target.closest('#bemoji')){const em=document.getElementById('emojis');if(em)em.classList.remove('open')}
  const t=e.target.closest('[data-drop]');
  if(t){const d=document.getElementById(t.dataset.drop);const open=!d.classList.contains('open');closeDrops();d.classList.toggle('open',open);return}
  if(!e.target.closest('.drop'))closeDrops();
});
const lbl=n=>{const a=(S&&S.accounts||[]).find(x=>x.name===n);return a?a.label:n};
