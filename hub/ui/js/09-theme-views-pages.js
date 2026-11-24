/* --- thème (clair / sombre / auto) et couleur d'accent --- */
const PAL=[['orange','Orange','#f26a1b','#c2410c'],['ambre','Ambre','#f5a524','#d97706'],['rose','Rose','#ec4899','#be185d'],['violet','Violet','#8b5cf6','#6d28d9'],['bleu','Bleu','#3b82f6','#1d4ed8'],['turquoise','Turquoise','#14b8a6','#0f766e'],['vert','Vert','#22c55e','#15803d'],['rouge','Rouge','#ef4444','#b91c1c']];
const effTheme=m=>m==='auto'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):m;
function syncBars(){
  try{
    const bg=getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()||'#08080a';
    const ms=document.querySelectorAll('meta[name=theme-color]');ms.forEach((m,i)=>{if(i)m.remove()});
    const m=document.querySelector('meta[name=theme-color]');if(m){m.removeAttribute('media');m.setAttribute('content',bg)}
    const ac=getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()||'#f26a1b';if(window.RelaisApp&&window.RelaisApp.setBars){try{window.RelaisApp.setBars(bg,document.documentElement.dataset.theme==='dark',ac)}catch(e){}}
  }catch(e){}
}
function setMode(m){LS('hub_theme',m);const t=effTheme(m);document.documentElement.dataset.theme=t;if(window.hubSetTheme)window.hubSetTheme(t);LS('hub_theme',m);syncBars();if(VIEW==='settings')renderSettingsPage()}
function setAccent(a){LS('hub_accent',a);document.documentElement.dataset.accent=a;syncBars();if(VIEW==='settings')renderSettingsPage()}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{if((LS('hub_theme')||'dark')==='auto')setMode('auto')});
syncBars();

/* --- vues --- */
const MOB=()=>matchMedia('(max-width:860px)').matches;
let VIEW=MOB()?'home':'hub',ST=null,stT=0;
function setView(v){
  VIEW=v;document.body.dataset.view=v;
  if(v!=='hub')document.body.classList.remove('open');
  document.querySelectorAll('#side .nv[data-view],#tabbar button[data-view]').forEach(b=>b.classList.toggle('on',b.dataset.view===v));
  closeDrops();
  if(v==='stats')renderStatsPage();else if(v==='security')renderSecurityPage();else if(v==='settings')renderSettingsPage();
  v3Render();
  const pg=$('#pages');if(pg)pg.scrollTop=0;window.scrollTo(0,0);
}
function openChat(k){sel=k;chatCache=null;dirty=false;if(VIEW!=='hub')setView('hub');document.body.classList.add('open');renderList();loadChat(true);renderChips()}
async function loadStats(force){if(!force&&ST&&Date.now()-stT<45000)return ST;const r=await api('/api/stats');if(r&&!r.error){ST=r;stT=Date.now()}return ST}
const nameOf=()=>S&&S.me?S.me.name:(S&&S.accounts[0]?S.accounts[0].label:'Relais');
const todayOf=()=>ST&&ST.series&&ST.series.length?ST.series[ST.series.length-1]:null;
const ago=t=>{if(!t)return 'jamais';const s=Math.round((Date.now()-t)/1000);return s<90?'il y a '+s+' s':s<5400?'il y a '+Math.round(s/60)+' min':'il y a '+Math.round(s/3600)+' h'};
function spark(series){
  if(!series||!series.length)return el('div');
  const v=series.map(d=>d.owner+d.llm),mx=Math.max(1,...v),w=240,h=56;
  const pts=v.map((y,i)=>[(i/(v.length-1||1))*w,h-4-(y/mx)*(h-12)]);
  const line=pts.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ');
  const wrap=el('div');wrap.innerHTML='<svg class="spark" viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none"><defs><linearGradient id="spg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--accent)" stop-opacity=".45"/><stop offset="1" stop-color="var(--accent)" stop-opacity="0"/></linearGradient></defs><path d="'+line+' L'+w+' '+h+' L0 '+h+' Z" fill="url(#spg)"/><path d="'+line+'" fill="none" stroke="var(--accent)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  return wrap.firstChild;
}
const ico=(n,c)=>{const d=el('span',{className:c||''});d.innerHTML=ICN[n]||'';return d.firstChild?d:d};

function v3Render(){
  if(!S)return;
  const online=S.accounts.some(x=>x.running&&x.classic),p=S.settings.paused==='1';
  const unread=S.chats.filter(c=>c.unread>0).length;
  for(const id of ['nvc_hub','nvc_tb']){const b=$('#'+id);if(b){b.textContent=unread;b.style.display=unread?'grid':'none'}}
  const need=S.accounts.filter(a=>a.expired);
  $('#top_dot').className='dot'+(online&&!p&&!need.length?' on':'');$('#top_state_t').textContent=need.length?'Action requise':!online?'Hors ligne':p?'En pause':'En ligne';
  if(need.length){$('#sb_state').textContent='Action requise';$('#sb_ast').textContent='Reconnecte « '+need[0].label+' »';$('#sb_okc').classList.add('off')}
  // cloche : brouillons à valider et demandes d'attention
  const todo=[];for(const a of need)todo.push([{key:null,name:a.label,acc:true},'à reconnecter : Meta demande une validation']);for(const c of S.chats){if(c.drafts)todo.push([c,c.drafts+' brouillon'+(c.drafts>1?'s':'')+' à valider']);if(c.attention)todo.push([c,'demande ton attention'])}
  const bn=$('#bell_n');bn.textContent=todo.length;bn.style.display=todo.length?'grid':'none';
  const bl=$('#bell_list'),bsig=JSON.stringify(todo.map(t=>[t[0].key,t[1]]));
  if(bl.dataset.sig!==bsig){bl.dataset.sig=bsig;bl.replaceChildren(...(todo.length?todo.map(([c,t])=>el('button',{className:'it',onclick:()=>{closeDrops();if(c.acc)$('#bacc').click();else openChat(c.key)}},el('span',{style:'display:flex;flex-direction:column;align-items:flex-start'},el('b',{},c.name),el('span',{style:'font-size:12px;color:var(--muted)'},t)))):[el('div',{className:'acc'},'Rien à traiter pour le moment.')]))}
  // carte utilisateur du rail
  const nm=nameOf();if($('#sb_name').textContent!==nm){$('#sb_name').textContent=nm;$('#sb_av').replaceChildren(placeholder({name:nm,key:nm},''))}
  $('#sb_role').textContent=S.me?(S.me.role==='admin'?'Administrateur':'Utilisateur'):'Usage local';
  $('#sb_out').style.display=S.auth?'flex':'none';
  document.body.dataset.view=VIEW;
  renderRight();if(VIEW==='home')renderHome();
  if(!ST||Date.now()-stT>60000)loadStats().then(()=>{renderRight();if(VIEW==='home')renderHome()});
}
const _renderTop=renderTop;renderTop=function(){_renderTop();v3Render()};

/* --- colonne de droite (bureau) --- */
function renderRight(){
  const box=$('#rside');if(!box||!S)return;
  const c=sel?S.chats.find(x=>x.key===sel):null,t=todayOf(),p=S.settings.paused==='1',online=S.accounts.some(x=>x.running&&x.classic);
  const sig=JSON.stringify([p,online,sel,c&&[c.enabled,c.mode,c.is_group],S.chats.length,t,ST&&ST.series&&ST.series.length,S.llm_last_hour,S.sync&&S.sync.last_run,S.accounts.map(a=>a.label+a.running+a.classic+(a.expired?'x':''))]);
  if(box.dataset.sig===sig)return;box.dataset.sig=sig;
  const tog=el('label',{className:'switch',title:p?'Reprendre l’assistant':'Mettre l’assistant en pause'},el('input',{type:'checkbox',checked:!p}),el('i'));
  tog.querySelector('input').onchange=()=>$('#bpause').click();
  const card1=el('div',{className:'rcard'},el('div',{className:'rs-top'},el('span',{className:'orb'},ico('bolt')),el('div',{className:'t'},el('b',{},'Assistant Relais'),el('span',{className:'sub'},p?'En pause':'Actif')),tog));
  const k=(n,l)=>el('div',{},el('b',{},String(n)),el('span',{},l));
  const card2=el('div',{className:'rcard'},el('h4',{},ico('stats'),'Aujourd’hui'),el('div',{className:'kp3'},k(S.chats.length,'Conversations'),k(t?t.llm:'–','Réponses du LLM'),k(t?t.contact:'–','Messages reçus')),spark(ST&&ST.series));
  const mk=(id,label,icon,on,fn)=>{const b=el('button',{className:on?'on':'',disabled:!c||c.is_group,onclick:fn});b.append(ico(icon),label);return b};
  const setc=async o=>{if(!c)return;const r=await api('/api/chat/settings',{key:c.key,...o});if(r.error)toast(r.error,'err');refresh()};
  const card3=el('div',{className:'rcard'},el('h4',{},ico('bolt'),'Contrôle rapide'),el('div',{className:'quick'},
    mk('q1','Brouillon','draft',c&&c.enabled&&c.mode==='draft',()=>setc({enabled:true,mode:'draft'})),
    mk('q2','Auto','bolt',c&&c.enabled&&c.mode!=='draft',()=>setc({enabled:true,mode:'auto'})),
    mk('q3','Pause','pause',c&&!c.enabled,()=>setc({enabled:false}))),
    el('div',{className:'sub',style:'margin-top:8px'},c?'Pour « '+c.name+' »':'Choisis une conversation.'));
  const a0=S.accounts[0];
  const row=(l,v,cls)=>el('div',{},el('span',{},l),el('span',{className:cls||''},v));
  const card4=el('div',{className:'rcard'},el('h4',{},ico('info'),'Informations'),el('div',{className:'info'},
    row('Compte Messenger',!S.accounts.length?'Aucun':S.accounts.some(a=>a.expired)?'À reconnecter':online?'Connecté':'Hors ligne',online&&!S.accounts.some(a=>a.expired)?'ok':''),
    row('Dernière synchro',S.sync&&S.sync.last_run?ago(S.sync.last_run):'—'),
    row('Réponses cette heure',String(S.llm_last_hour)),
    row('Brouillons à valider',String(S.chats.reduce((n,x)=>n+(x.drafts||0),0)))));
  card4.querySelectorAll('.ok').forEach(e=>e.style.color='var(--ok)');
  const card5=el('div',{className:'rcard help-card',onclick:()=>$('#bhelp').click()},el('span',{className:'orb'},ico('help')),el('div',{},el('b',{},'Besoin d’aide ?'),el('div',{className:'sub'},'Consulte le guide')),ico('chev'));
  box.replaceChildren(card1,card2,card3,card4,card5);
}

/* --- accueil (mobile) --- */
function renderHome(){
  const pg=$('#pg_home');if(!pg||!S)return;
  const t=todayOf(),online=S.accounts.some(x=>x.running&&x.classic),p=S.settings.paused==='1';
  const recent=[...S.chats].filter(c=>c.last_ts).sort((a,b)=>b.last_ts-a.last_ts).slice(0,4);
  const sig=JSON.stringify([nameOf(),online,p,t,S.chats.length,recent.map(c=>[c.key,c.last_text,c.unread])]);
  if(pg.dataset.sig===sig)return;pg.dataset.sig=sig;
  const kp=(ic,n,l)=>el('div',{className:'kpi'},ico(ic),el('b',{},String(n)),el('span',{},l));
  const hero=el('div',{className:'hero'},el('h2',{},'Bonjour, '+nameOf()+' 👋'),el('div',{style:'color:var(--muted);margin-bottom:14px'},'Ton assistant intelligent pour Messenger.'),
    el('div',{className:'rs-top'},el('span',{className:'orb'},ico('bolt')),el('div',{className:'t'},el('b',{},!S.accounts.length?'Aucun compte connecté':p?'Assistant en pause':online?'En ligne':'Hors ligne'),el('span',{className:'sub'},!S.accounts.length?'Ajoute ton compte Messenger':p?'Aucune réponse automatique':online?'Tout est prêt':'En attente de Messenger'))));
  const btn=el('button',{className:'primary',style:'width:100%;padding:14px;margin-top:6px;font-size:15px',onclick:()=>setView(S.accounts.length?'stats':'settings')},S.accounts.length?'Voir les statistiques →':'Connecter un compte →');
  const list=recent.length?recent.map(c=>{const r=el('div',{className:'homerow',onclick:()=>openChat(c.key)},avatar(c,'sm'),el('div',{className:'t'},el('b',{},c.name),el('div',{className:'s'},c.last_text||'')),el('div',{style:'text-align:right;font-size:12px;color:var(--muted)'},fmt(c.last_ts),c.unread?el('div',{className:'cnt',style:'margin:4px 0 0 auto;display:grid;place-items:center;min-width:22px;height:22px;border-radius:999px;background:var(--accent);color:#fff;font-weight:600;font-size:12px'},String(c.unread)):''));return r}):[el('div',{className:'sub',style:'padding:10px;color:var(--muted)'},'Aucune conversation pour le moment.')];
  pg.replaceChildren(hero,el('div',{className:'grid3'},kp('chat',S.chats.length,'Conversations'),kp('send',t?t.llm:'–','Réponses'),kp('shield',S.chats.filter(c=>c.unread>0).length,'Non lues')),btn,
    el('div',{className:'sech'},el('b',{},'Conversations récentes'),el('button',{onclick:()=>setView('hub')},'Tout voir →')),...list);
}

/* --- page Statistiques --- */
async function renderStatsPage(){
  const pg=$('#pg_stats');pg.replaceChildren(el('h2',{},'Statistiques'),el('p',{className:'lead'},'Chargement…'));
  const r=await loadStats(true);if(!r){pg.replaceChildren(el('h2',{},'Statistiques'),el('p',{className:'lead'},'Indisponible pour le moment.'));return}
  const kp=(n,l,e)=>el('div',{className:'kpi'},el('b',{},String(n),e?el('em',{},e):''),el('span',{},l));
  const ser=r.series||[],mx=Math.max(1,...ser.map(d=>d.contact+d.owner+d.llm));
  const bars=el('div',{className:'bars'},...ser.map(d=>{const col=el('div',{title:d.d+' : '+d.contact+' reçus, '+d.owner+' de toi, '+d.llm+' du LLM'});
    const seg=(c,v)=>el('i',{className:c,style:'height:'+(v/mx*100)+'%;min-height:'+(v?3:0)+'px'});
    col.append(el('small',{},d.d.slice(8)),seg('c',d.contact),seg('o',d.owner),seg('l',d.llm));return col}));
  const auto=(r.llm_total+0)&&(r.messages)?Math.round(100*r.llm_total/Math.max(1,r.llm_total+0)):0;
  const mb=b=>b>=1048576?(b/1048576).toFixed(1)+' Mo':Math.round(b/1024)+' Ko';
  const u=r.usage&&r.usage['7j']&&r.usage['7j'].total;
  const leg=el('div',{className:'legend'});leg.innerHTML='<span><i style="background:var(--line-2)"></i>Reçus</span><span><i style="background:var(--text-2);opacity:.6"></i>Toi</span><span><i style="background:var(--accent)"></i>LLM</span>';
  pg.replaceChildren(el('h2',{},'Statistiques'),el('p',{className:'lead'},'Ton activité sur les 14 derniers jours (comptages seulement, jamais le contenu).'),
    el('div',{className:'grid3'},kp(r.chats,'Conversations',r.chats_on?r.chats_on+' actives':''),kp(r.messages,'Messages'),kp(r.llm_total,'Réponses du LLM',r.llm_hour?r.llm_hour+' / h':'')),
    el('div',{className:'card',style:'margin-top:14px'},el('b',{},'Activité récente'),bars,leg),
    el('div',{className:'grid3'},kp(r.drafts,'Brouillons à valider'),kp(r.attachments,'Pièces jointes',mb(r.media_bytes||0)),kp(r.attacks_7d,'Messages suspects (7 j)')),
    u?el('div',{className:'card',style:'margin-top:14px'},el('b',{},'Consommation du LLM (7 jours)'),el('div',{className:'grid3',style:'margin-top:10px'},kp(u.calls,'Appels'),kp(Math.round((u.in||0)/1000)+'k / '+Math.round((u.out||0)/1000)+'k','Jetons entrée / sortie'),kp((u.cache_pct||0)+' %','Servis par le cache'))):'');
}

/* --- page Sécurité --- */
async function renderSecurityPage(){
  const pg=$('#pg_security');const r=await loadStats(false)||{};
  const lvl=S&&S.settings.security_level||'strict',on=(S&&S.settings.classifier==='1'),jg=(S&&S.settings.judge==='1');
  const e2=S&&S.accounts.filter(a=>a.e2ee).length||0;
  const item=(ic,t,s2)=>el('div',{className:'sec-item',style:'cursor:default'},el('span',{className:'ic'},ico(ic)),el('div',{},el('b',{},t),el('span',{},s2)));
  const hero=el('div',{className:'card shield'},el('div',{className:'big'},ico('shield')),el('h3',{},'Protection active'),el('div',{className:'sub',style:'color:var(--muted)'},'Niveau de sécurité : '+({strict:'strict',normal:'normal',off:'désactivé'}[lvl]||lvl)));
  pg.replaceChildren(el('h2',{},'Sécurité'),el('p',{className:'lead'},'Ce qui protège ton compte et tes conversations.'),hero,
    item('lock','Espace privé','Tes conversations sont dans ton espace, séparé des autres utilisateurs.'),
    item('key','Connexion sécurisée','HTTPS, identifiant et mot de passe. Ton mot de passe Messenger n’est jamais conservé : seule la session l’est.'),
    item('eye','Contrôle total','L’assistant ne répond que dans les conversations que tu actives, avec pause générale en un clic.'),
    item('shield','Messages suspects',(on?'Classifieur actif':'Classifieur désactivé')+(jg?', vérification avant envoi active':'')+'. '+(r.attacks_7d||0)+' message(s) suspect(s) détecté(s) sur 7 jours.'),
    item('lock','Chiffrement de bout en bout',e2?(e2+' compte(s) avec canal chiffré connecté. Le serveur déchiffre pour que l’assistant puisse répondre.'):'Aucun canal chiffré connecté pour le moment.'),
    el('button',{className:'set-row',onclick:()=>$('#bhelp').click()},el('span',{className:'ic'},ico('help')),el('div',{},el('b',{},'En savoir plus'),el('span',{className:'s'},'Guide et bonnes pratiques')),el('span',{className:'chev'},ico('chev'))));
}

/* --- page Paramètres (+ apparence) --- */
function renderSettingsPage(){
  const pg=$('#pg_settings');if(!S)return;
  const nm=nameOf(),adm=S.me&&S.me.role==='admin';
  const row=(ic,t,s2,fn)=>el('button',{className:'set-row',onclick:fn},el('span',{className:'ic'},ico(ic)),el('div',{},el('b',{},t),el('span',{className:'s'},s2||'')),el('span',{className:'chev'},ico('chev')));
  const online=S.accounts.some(x=>x.running&&x.classic);
  const mode=LS('hub_theme')||'dark',acc=LS('hub_accent')||'orange';
  const seg=el('div',{className:'seg3'},...[['auto','Auto'],['light','Clair'],['dark','Sombre']].map(([m,l])=>el('button',{className:mode===m?'on':'',onclick:()=>setMode(m)},l)));
  const sw=el('div',{className:'swatches'},...PAL.map(([k,n,c1,c2])=>{const b=el('button',{className:'sw'+(acc===k?' on':''),title:n,'aria-label':n,'aria-pressed':String(acc===k),onclick:()=>setAccent(k)});b.style.setProperty('--c1',c1);b.style.setProperty('--c2',c2);return b}));
  const openSet=sec=>{$('#bset').click();if(sec){const b=document.querySelector('#dset section[data-sec]:has('+sec+')');if(b){const k=b.dataset.sec;const t=document.querySelector('#dset .seg button[data-sec="'+k+'"]');if(t)t.click()}}};
  const prof=el('div',{className:'card profile'},el('span',{id:'set_av'}),el('div',{},el('b',{style:'font-size:18px'},nm),el('div',{className:'sub',style:'color:var(--muted)'},S.me?(adm?'Administrateur':'Utilisateur'):'Usage local')));
  prof.firstChild.replaceChildren(placeholder({name:nm,key:nm},'lg'));
  const app=el('div',{className:'card',id:'set_appearance'},el('b',{},'Apparence'),el('div',{className:'sub',style:'color:var(--muted);margin:2px 0 10px'},'Mode d’affichage et couleur du thème (enregistrés sur cet appareil).'),seg,el('div',{style:'margin-top:14px;font-size:13px;color:var(--text-2)'},'Couleur'),sw);
  const rows=[row('chat','Compte Messenger',S.accounts.length?(S.accounts.length+' compte'+(S.accounts.length>1?'s':'')+' · '+(online?'connecté':'hors ligne')):'Aucun compte connecté',()=>$('#bacc').click()),
    row('bolt','Mode de réponse','Automatique, brouillon, limites, silence',()=>openSet('')),
    row('user','Personnalisation','Ton, style, règles de l’assistant',()=>openSet('#s_style')),
    row('shield','Sécurité','Niveau de protection et leurres',()=>openSet('#s_sec'))];
  if(adm)rows.push(row('user','Utilisateurs','Inviter, créer, réinitialiser',()=>$('#busers').click()));
  if(S.auth)rows.push(row('key','Mot de passe','Changer mon mot de passe',()=>$('#bpw').click()));
  rows.push(row('help','Aide','Guide et questions fréquentes',()=>$('#bhelp').click()));
  const out=S.auth?el('button',{className:'set-row',style:'justify-content:center;color:var(--bad)',onclick:()=>$('#blogout').click()},ico('out'),el('b',{style:'color:var(--bad)'},'Se déconnecter')):'';
  pg.replaceChildren(el('h2',{},'Paramètres'),prof,app,...rows,out,el('div',{className:'ver'},'Relais · '+(window.RelaisApp?'application Android':'web')));
}

