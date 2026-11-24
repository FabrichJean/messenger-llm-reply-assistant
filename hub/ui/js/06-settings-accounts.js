$('#search').oninput=()=>S&&renderList();$('#search').onkeydown=e=>{if(e.key==='Escape'&&e.target.value){e.target.value='';renderList()}};$('#onlyon').onchange=()=>S&&renderList();$('#hideempty').onchange=()=>S&&renderList();
$('#blog').onclick=$('#tab_log').onclick=()=>{LS('hub_log',LS('hub_log')==='1'?'0':'1');applyView()};
$('#nv_hub').onclick=()=>{LS('hub_log','0');applyView();closeDrops()};
document.querySelectorAll('.tab[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;document.querySelectorAll('.tab[data-tab]').forEach(x=>x.classList.toggle('on',x===b));renderList()});
$('#bsync').onclick=async()=>{closeDrops();const r=await api('/api/sync/all',{});if(!r.ok)toast('Une tâche est déjà en cours : attends sa fin (progression en bas à droite).','err');refresh()};
$('#bthreads').onclick=async()=>{closeDrops();await api('/api/threads/load',{});const r=await api('/api/names/resolve',{});if(!r.ok)toast('Une tâche est déjà en cours : attends sa fin (progression en bas à droite).','err');refresh()};
$('#bnew').onclick=async()=>{
  const v=await askForm('Nouvelle conversation',[
    {id:'id',required:true,label:'Identifiant Facebook de la personne',placeholder:'ex. 100095216710689',hint:'Un nombre : on le trouve dans l\'adresse de son profil.'},
    {id:'name',label:'Nom à afficher (facultatif)'},
    {id:'e2ee',type:'checkbox',label:'Conversation chiffrée de bout en bout (cadenas)'}],'Ajouter');
  if(!v||!v.id.trim())return;
  const r=await api('/api/chat/add',{id:v.id.trim(),name:v.name.trim(),e2ee:v.e2ee});if(r.error){toast(r.error,'err');return}
  await refresh();sel=r.key;chatCache=null;dirty=false;renderList();loadChat(true)};
$('#bhist').onclick=()=>{const hs=$('#h_acc');hs.replaceChildren(...S.accounts.map(a=>new Option('Compte « '+a.label+' »',a.name)));hs.style.display=S.accounts.length>1?'block':'none';hs.onchange=renderHist;renderHist();$('#h_pin').value='';$('#h_ok').checked=false;$('#dhist').showModal()};
$('#h_cancel').onclick=()=>$('#dhist').close();
$('#h_go').onclick=async()=>{
  const pin=$('#h_pin').value.trim();
  if(!/^\d{6}$/.test(pin)){toast('Le PIN doit faire exactement 6 chiffres.','err');return}
  if(!$('#h_ok').checked){toast('Coche la case pour confirmer.','err');return}
  const r=await api('/api/history/enroll',{pin,confirm:true,account:$('#h_acc').value||undefined});$('#h_pin').value='';
  if(r.error){toast(r.error,'err');return}
  setTimeout(refresh,1500);setTimeout(refresh,5000);setTimeout(refresh,12000)};
$('#bpause').onclick=async()=>{await api('/api/settings',{paused:S.settings.paused==='1'?'0':'1'});refresh()};
$('#s_cancel').onclick=()=>$('#dset').close();
const SET_FIELDS={owner:['v','s_owner'],model:['v','s_model'],persona:['v','s_persona'],style_profile:['v','s_style'],style_cross:['c','s_cross'],style_auto:['c','s_auto'],
  takeover_min:['v','s_takeover'],max_per_hour_global:['v','s_maxg'],late_reply_min:['v','s_late'],sync_s:['v','s_sync'],judge:['c','s_judge'],
  security_level:['v','s_sec'],classifier:['c','s_class'],attack_mode:['v','s_atk'],link_preview:['c','s_link'],link_preview_fb:['c','s_linkfb'],typing:['c','s_typing'],read_delay:['v','s_read'],token_mode:['v','s_tokmode']};
let settingsSnap={};
const scope=()=>$('#s_scope').value||'';
const eff=k=>{const sc=scope();const o=sc&&S.account_settings&&S.account_settings[sc]?S.account_settings[sc][k]:undefined;return o!==undefined?o:S.settings[k]};
function readField(k){const [t,id]=SET_FIELDS[k];const e=$('#'+id);return t==='c'?(e.checked?'1':'0'):String(e.value)}
function fillSettings(){
  for(const k in SET_FIELDS){const [t,id]=SET_FIELDS[k];const v=eff(k);if(t==='c')$('#'+id).checked=v==='1';else $('#'+id).value=v}
  settingsSnap={};for(const k in SET_FIELDS)settingsSnap[k]=readField(k);
  const sc=scope();const n=sc?(S.owner_msgs_by_account||{})[sc]:S.owner_msgs;
  $('#s_stat').textContent=(n??0)+' de tes messages sont connus'+(sc?' pour le compte « '+sc+' »':'')+'. Plus il y en a, plus l\'imitation est fidèle.';
  settingsSnap.paused=sc?eff('paused'):'0';$('#s_pausebox').style.display=sc?'flex':'none';$('#s_pause').checked=sc&&eff('paused')==='1';
  $('#s_reset').style.display=sc?'inline-block':'none';
  $('#s_scopehint').textContent=sc?'Ces réglages ne s\'appliquent qu\'au compte « '+lbl(sc)+' » ; le reste utilise les valeurs générales.':'Valeurs générales : elles s\'appliquent à tous les comptes qui n\'ont pas leurs propres réglages.';
}
$('#bset').onclick=()=>{
  const adm=!S.auth||(S.me&&S.me.role==='admin');
  if(!adm&&!S.accounts.length){toast('Ajoute d\'abord un compte Messenger (menu > Gérer les comptes).','err');return}
  const sel=$('#s_scope');sel.replaceChildren();if(adm)sel.append(new Option('Général (tous les comptes)',''));
  for(const a of S.accounts)sel.append(new Option('Compte « '+a.label+' »',a.name));
  const f=$('#accfilter').value;sel.value=f||(S.accounts.length===1||!adm?S.accounts[0].name:'');
  fillSettings();$('#dset').showModal();
};
$('#s_scope').onchange=fillSettings;
const styleAccount=()=>scope()||$('#accfilter').value||undefined;
$('#s_learn').onclick=async()=>{const r=await api('/api/style/learn',{account:styleAccount()});(r.ok?toast('Import lancé en arrière-plan (quelques minutes). Le profil sera mis à jour à la fin.','ok'):toast(r.error||'Un import est déjà en cours.','err'));refresh()};
$('#s_analyze').onclick=async()=>{await api('/api/style/analyze',{account:styleAccount()});toast('Analyse lancée. Rouvre les réglages dans quelques secondes pour voir le profil.','ok');refresh()};
$('#s_reset').onclick=async()=>{const sc=scope();if(!sc||!await ask('Les réglages propres au compte « '+lbl(sc)+' » seront supprimés ; le style appris est conservé.',{title:'Revenir aux valeurs générales ?',ok:'Revenir'}))return;await api('/api/settings/reset',{account:sc});await refresh();fillSettings()};
$('#s_save').onclick=async()=>{
  const body={};const sc=scope();if(sc)body.account=sc;
  for(const k in SET_FIELDS){const v=readField(k);if(v!==settingsSnap[k])body[k]=v}
  if(sc){const p=$('#s_pause').checked?'1':'0';if(p!==(settingsSnap.paused||'0'))body.paused=p}
  await api('/api/settings',body);$('#dset').close();refresh()};
function renderAccFilter(){
  const f=$('#accfilter');const multi=S.accounts.length>1;f.style.display=multi?'block':'none';
  if(!multi){f.value='';return}
  const cur=f.value;const sig=S.accounts.map(a=>a.name+a.label).join('|');if(f.dataset.sig!==sig){f.dataset.sig=sig;f.replaceChildren(new Option('Tous les comptes',''));for(const a of S.accounts)f.append(new Option(a.label,a.name));f.value=cur}
}
$('#accfilter').onchange=()=>S&&renderList();

let loginTimer=null,loginName='';
function renderAccounts(){
  const box=$('#a_list');box.replaceChildren();
  if(!S.accounts.length)box.append(el('div',{className:'hint',style:'margin:0 0 12px'},'Aucun compte connecté pour le moment.'));
  for(const a of S.accounts){
    const ok=a.running&&a.classic&&!a.expired;
    const av=el('div',{className:'avw'},placeholder({name:a.label,key:a.name},'lg'),el('i',{className:'ondot'+(ok?' on':'')}));
    const badge=a.expired?el('span',{className:'bdg warn'},'Action requise'):ok?el('span',{className:'bdg ok'},'✓ Actif'):el('span',{className:'bdg'},'Hors ligne');
    const info=el('div',{className:'ai'},el('b',{},a.label),el('div',{className:'s'},a.expired?'À reconnecter':ok?'Connecté sur Messenger':'Connexion en cours…'),el('div',{className:'bds'},badge,el('span',{className:'bdg'+(a.e2ee?' ok':'')},a.e2ee?'Chiffré':'Non chiffré')),a.expired&&a.note?el('div',{className:'hint',style:'margin-top:8px'},a.note):'');
    const del=el('button',{className:'rm',title:'Retirer ce compte du hub',onclick:async()=>{
      if(!await ask('Ses fichiers restent sur le disque : tu peux le rajouter plus tard.',{title:'Retirer « '+a.label+' » de l\'application ?',ok:'Retirer',danger:true}))return;
      const r=await api('/api/accounts/remove',{name:a.name,confirm:true});if(r.error)toast(r.error,'err');refresh()}});
    del.append(ih(IC.trash),'Retirer');
    const acts=el('div',{className:'acts'},del);
    if(a.running&&!a.has_device)acts.prepend(el('button',{textContent:'Enregistrer l\'appareil chiffré',title:'Ajoute un appareil chiffré sur ce compte Messenger',onclick:async()=>{
      if(!await ask('Cela AJOUTE un appareil de chiffrement sur le compte « '+a.label+' » (visible dans les réglages de Messenger, retirable). À faire une seule fois par compte.',{title:'Enregistrer l\'appareil chiffré ?',ok:'Enregistrer'}))return;
      const r=await api('/api/accounts/register_e2ee',{name:a.name,confirm:true});if(r.error)toast(r.error,'err');else toast('Enregistrement lancé. Le canal chiffré se connecte dans quelques secondes.','ok');refresh()}}));
    box.append(el('div',{className:'acard'+(a.expired?' warn':'')},av,info,acts));
  }
}
function setLoginUi(state,err,reused){
  const busy=state==='starting'||state==='waiting_login';
  const msg={starting:'Ouverture de Chrome…',waiting_login:'⏳ Connecte-toi dans la fenêtre Chrome qui vient de s\'ouvrir. Elle se fermera toute seule quand ce sera fini.',
    captured:'Session récupérée, ajout du compte…',done:'✓ Compte '+(err?'« '+err+' » ':'')+(reused?'reconnecté.':'ajouté. Étape suivante : « Enregistrer l\'appareil chiffré » (👤 Comptes) pour recevoir les conversations chiffrées.'),
    error:'Échec : '+(err||''),cancelled:'Connexion annulée.',none:''}[state]||'';
  // fenêtre « Comptes »
  if(RL.on){const m=$('#rl_msg');
    if(state==='done'){m.style.color='var(--ok)';m.textContent='✓ Compte '+(err?'« '+err+' » ':'')+(reused?'reconnecté.':'ajouté.');setTimeout(()=>{rlClose();toast('Compte Messenger connecté ✓','ok');refresh();renderAccounts()},1100)}
    else if(state==='captured'){m.style.color='var(--muted)';m.textContent='Session récupérée, ajout du compte…';$('#rl_load').style.display='grid';$('#rl_load').textContent='Ajout du compte…'}
    else if(state==='error'||state==='cancelled'){RL.on=false;m.style.color='var(--bad)';m.textContent=state==='error'?'Échec : '+(err||'connexion interrompue')+'. Tu peux fermer et réessayer.':'Connexion annulée.';$('#rl_cancel').textContent='Fermer'}
  }
  $('#a_go').disabled=busy;$('#a_cancel').style.display=busy?'inline-block':'none';
  $('#a_status').style.color=state==='error'?'var(--bad)':'var(--muted)';$('#a_status').textContent=msg;
  // page d'accueil : tout se passe dans la carte, sans changer sa taille
  const L=$('#landing');
  const phase={starting:'starting',waiting_login:'waiting',captured:'captured',done:'done',error:'error'}[state]||'idle';
  L.dataset.phase=phase;
  $('#l_go').disabled=phase!=='idle'&&phase!=='error';
  $('#l_go .lbl').textContent={starting:'Ouverture de Chrome…',waiting:'En attente de ta connexion…',captured:'Finalisation…',done:'Compte connecté'}[phase]||'Connecter mon compte';
  $('#l_status').textContent=phase==='error'?(err||'La connexion a échoué.'):'';
}
async function pollLogin(){
  if(!loginName)return;
  const r=await api('/api/accounts/login/status?name='+encodeURIComponent(loginName));
  setLoginUi(r.state,r.state==='done'?r.name:r.error,r.reused);
  if(r.state==='starting'||r.state==='waiting_login'||r.state==='captured'){loginTimer=setTimeout(pollLogin,RL.on?800:1500)}else{loginTimer=null;refresh()}
}
$('#bacc').onclick=()=>{renderAccounts();$('#dacc').showModal()};
$('#a_close').onclick=()=>$('#dacc').close();
async function extConnect(){
  const r=await api('/api/accounts/ext_code',{});if(!r.code){toast(r.error||'Échec.','err');return}
  window.postMessage({relais:'connect',code:r.code},location.origin);toast('Connexion en cours avec ton navigateur…','ok');
}
window.addEventListener('message',e=>{
  if(e.source!==window||e.origin!==location.origin)return;const d=e.data||{};
  if(d.relais==='progress'&&d.step)toast(d.step,'ok');
  if(d.relais==='result'){if(d.ok){toast('Compte « '+(d.name||'')+' » '+(d.reused?'reconnecté':'ajouté')+' ✓','ok');refresh();renderAccounts()}else toast(d.error||'Échec de la connexion.','err')}
});
const RL={on:false,n:'0',q:Promise.resolve(),w:0,h:0};
const rlSend=o=>{RL.q=RL.q.then(()=>api('/api/accounts/login/input',o)).catch(()=>{})};
const rlPt=e=>{const r=$('#rl_img').getBoundingClientRect();return{x:Math.round((e.clientX-r.left)*(RL.w/r.width)),y:Math.round((e.clientY-r.top)*(RL.h/r.height))}};
async function rlFrames(){
  const img=$('#rl_img');
  while(RL.on){
    try{
      const r=await fetch('/api/accounts/login/frame?n='+RL.n);
      if(r.status===401){location.href='/login';return}
      if(r.status===200){RL.n=r.headers.get('X-N')||RL.n;const u=URL.createObjectURL(await r.blob());const old=img.src;img.src=u;if(old&&old.startsWith('blob:'))URL.revokeObjectURL(old);$('#rl_load').style.display='none'}
      else if(r.status!==204)await new Promise(z=>setTimeout(z,900));
    }catch(e){await new Promise(z=>setTimeout(z,900))}
  }
}
function rlClose(){RL.on=false;const d=$('#dlogin');if(d.open)d.close();const i=$('#rl_img');if(i.src.startsWith('blob:'))URL.revokeObjectURL(i.src);i.removeAttribute('src')}
async function openRemote(){
  const W=Math.max(290,Math.min(440,innerWidth-64)),H=Math.max(340,Math.min(540,innerHeight-400));
  const r=await api('/api/accounts/login/start',{w:W,h:H});
  if(r.error){toast(r.error,'err');return}
  RL.w=r.size[0]||W;RL.h=r.size[1]||H;RL.n='0';RL.on=true;
  const wrap=$('#rl_wrap');wrap.style.width=RL.w+'px';wrap.style.maxWidth='100%';$('#rl_load').style.display='grid';$('#rl_load').textContent='Ouverture de Messenger…';$('#rl_msg').textContent='';$('#rl_msg').style.color='var(--muted)';$('#rl_cancel').textContent='Annuler';
  const d=$('#dlogin');if(!d.open)d.showModal();
  loginName='login';clearTimeout(loginTimer);pollLogin();rlFrames();
}
{const d=$('#dlogin'),img=$('#rl_img'),kb=$('#rl_kb');
 d.addEventListener('cancel',e=>e.preventDefault());   // Échap ne ferme pas la fenêtre : seul « Annuler » (ou la fin de la connexion) la ferme
 const focusKb=()=>{kb.value='';kb.focus({preventScroll:true})};
 img.addEventListener('click',e=>{rlSend({t:'click',...rlPt(e)});focusKb()});
 img.addEventListener('wheel',e=>{e.preventDefault();rlSend({t:'scroll',dy:e.deltaY})},{passive:false});
 let ty=null,acc=0;
 img.addEventListener('touchstart',e=>{ty=e.touches[0].clientY;acc=0},{passive:true});
 img.addEventListener('touchmove',e=>{if(ty===null)return;const y=e.touches[0].clientY,r=img.getBoundingClientRect();acc+=(ty-y)*(RL.h/r.height);ty=y;if(Math.abs(acc)>24){rlSend({t:'scroll',dy:Math.round(acc)});acc=0}},{passive:true});
 img.addEventListener('touchend',()=>{ty=null});
 kb.addEventListener('input',()=>{const v=kb.value;kb.value='';if(v)rlSend({t:'text',s:v})});
 kb.addEventListener('keydown',e=>{const k=e.key;if(['Enter','Backspace','Tab','Escape','Delete','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Home','End'].includes(k)){e.preventDefault();rlSend({t:'key',k})}});
 $('#rl_kbd').onclick=focusKb;$('#rl_enter').onclick=()=>rlSend({t:'key',k:'Enter'});$('#rl_back').onclick=()=>rlSend({t:'key',k:'Backspace'});$('#rl_tab').onclick=()=>rlSend({t:'key',k:'Tab'});
 $('#rl_cancel').onclick=async()=>{await api('/api/accounts/login/cancel',{});rlClose();refresh()};
}
async function startLogin(){
  if(window.RelaisApp){try{window.RelaisApp.connectMessenger()}catch(e){toast('Connexion indisponible dans cette version de l\'application.','err')}return}   // appli Android : Messenger s'ouvre dans l'appli
  if(document.documentElement.dataset.relaisExt==='1')return extConnect();   // extension du navigateur installée : on utilise le navigateur du client
  if(S&&S.login_remote)return openRemote();   // mode « navigateur distant » (désactivé par défaut)
  if(S&&S.can_login===false){$('#dext').showModal();return}
  if(false){$('#dacc').showModal();toast('Pour connecter un compte, utilise l\'application Android Relais.','ok');return}
  if(S&&S.login_remote)return openRemote();
  const r=await api('/api/accounts/login/start',{});
  if(r.error){setLoginUi('error',r.error);return}
  loginName='login';setLoginUi('starting');clearTimeout(loginTimer);pollLogin();
}
$('#a_go').onclick=startLogin;
$('#dext_go').onclick=()=>location.reload();
$('#l_go').onclick=startLogin;
$('#a_cancel').onclick=$('#l_cancel').onclick=async()=>{await api('/api/accounts/login/cancel',{name:loginName})};
async function importCurl(curlBox){
  const r=await api('/api/accounts/import_curl',{curl:curlBox.value});
  curlBox.value='';if(r.error){setLoginUi('error',r.error);return}
  setLoginUi('done',r.name,r.reused);refresh();renderAccounts();
}
$('#a_imp').onclick=()=>importCurl($('#a_curl'));

