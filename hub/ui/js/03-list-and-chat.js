function renderTop(){
  document.body.classList.toggle('noacc',!S.accounts.length);
  if(S.accounts.length)document.body.classList.remove('later');
  if(!S.accounts.length&&S.me&&S.me.role==='admin')document.body.classList.add('later');   // l'administrateur sans compte gère les utilisateurs : pas de page d'accueil
  renderAccFilter();
  if($('#dacc').open)renderAccounts();
  const a=$('#accs');a.replaceChildren();
  for(const x of S.accounts){
    const ago=t=>t?(Math.round((Date.now()-t)/1000)<90?Math.round((Date.now()-t)/1000)+' s':Math.round((Date.now()-t)/60000)+' min'):'jamais';
    a.append(el('div',{className:'acc',title:(x.note||'')+' · dernier événement reçu il y a '+ago(x.last_event)+' · dernier message il y a '+ago(x.last_message)},
      el('b',{},x.label),el('span',{className:'dot'+(x.running&&x.classic?' on':'')}),'classique',el('span',{className:'dot'+(x.e2ee?' on':'')}),'chiffré',
      x.expired?el('b',{style:'color:var(--bad)'},'· à reconnecter'):''));
  }
  const first=S.accounts[0];
  const mv=$('#meav');if(first&&mv.dataset.k!==first.label){mv.dataset.k=first.label;mv.replaceChildren(placeholder({name:first.label,key:first.name},''))}
  $('#count').textContent='LLM / h : '+S.llm_last_hour;
  renderHist();
  renderTasks();
  const run=k=>(S.tasks||[]).some(t=>t.key===k&&t.state==='running');
  const bs=$('#bsync'),bt=$('#bthreads');bs.disabled=run('sync');bs.textContent=run('sync')?'Synchronisation en cours…':'Tout synchroniser';bt.disabled=run('names');bt.textContent=run('names')?'Recherche en cours…':'Charger plus de conversations';
  const bz=[];if(S.busy.import)bz.push('import de l\'historique…');if(S.busy.style)bz.push('analyse du style…');if(S.busy.import==='names')bz.push('recherche des noms…');if(S.busy.import==='sync')bz.push('synchronisation…');
  $('#busy').style.display='none';
  const p=S.settings.paused==='1';
  const online=S.accounts.some(x=>x.running&&x.classic);
  $('#bpause').replaceChildren(ih(p?IC.play:IC.pause),p?'Reprendre le LLM':'Pause générale');
  $('#bpause').className=p?'ok':'';
  $('#banner').style.display=p?'block':'none';
  $('#blogout').style.display=S.auth?'':'none';
  const adm=!!(S.me&&S.me.role==='admin');$('#busers').style.display=adm?'':'none';$('#bpw').style.display=S.auth?'':'none';
  const mn=$('#me_name');mn.style.display=S.me?'':'none';if(S.me)mn.textContent='Connecté : '+S.me.name+(adm?' (administrateur)':'');
  $('#a_reco').style.display='none';$('#a_apkrow').style.display=window.RelaisApp?'none':'block';
  if(window.RelaisApp){$('#a_go').style.display='';$('#a_go').textContent='Connecter mon compte Messenger';$('#a_intro').style.display='';$('#a_notool').style.display='none';$('#a_intro').innerHTML='Messenger s\'ouvre <b>dans l\'application</b> : connecte-toi (identifiant, mot de passe, code de vérification). <b>C\'est toi qui saisis</b> tes identifiants : ni l\'application ni le serveur ne les conservent. Ta session est envoyée au hub, puis effacée du téléphone.'}
  else if(!S.login_remote){const ext=document.documentElement.dataset.relaisExt==='1';$('#a_go').style.display='';$('#a_go').textContent=ext?'⚠ Connecter via l\'extension (déconseillé)':'⚠ Installer l\'extension (déconseillé)';$('#a_go').classList.remove('primary');$('#a_go').classList.add('discouraged');$('#a_intro').style.display='';$('#a_notool').style.display='none';
    $('#a_intro').innerHTML=ext?'<b>Déconseillé :</b> via l\'extension du navigateur.':'<b>Autre méthode, déconseillée</b> (plus lente, plus risquée) :'}
  else if(S.login_remote){$('#a_go').textContent='Connecter mon compte Messenger';$('#a_intro').innerHTML='Une fenêtre s\'ouvre ici avec la <b>vraie page officielle</b> de Messenger. Connecte-toi <b>dans cette fenêtre</b> (identifiant, mot de passe, code de vérification) : <b>c\'est toi qui saisis</b> tes identifiants, ils ne sont jamais conservés, seule la session l\'est.'}
  const noTool=false;$('#a_go').style.display=noTool?'none':'';$('#a_intro').style.display=noTool?'none':'';$('#a_notool').style.display=noTool?'':'none';if(noTool)$('#dacc details').open=true;
  const sv=$('#sb_ver');sv.replaceChildren(S.accounts.length+' compte'+(S.accounts.length>1?'s':''),el('span',{className:'dot'+(online?' on':'')}));
  $('#sb_state').textContent=online?'En ligne':'Hors ligne';
  $('#sb_ast').textContent=p?'Assistant en pause':'Assistant actif';
  $('#sb_okc').classList.toggle('off',!online||p);
  const n=S.chats.filter(c=>c.unread>0).length;const ct=$('#ct_unread');ct.textContent=n;ct.style.display=n?'grid':'none';document.title=(n?'('+n+') ':'')+'Messenger Lite Hub';
  renderChips();
  const lb=$('#logbox');const atEnd=lb.scrollTop+lb.clientHeight>=lb.scrollHeight-8;
  lb.replaceChildren(...S.log.filter(l=>l.level!=='debug').map(l=>el('div',{className:l.level},new Date(l.ts).toLocaleTimeString('fr-FR')+' '+(l.chat?'['+(S.chats.find(c=>c.key===l.chat)?.name||l.chat)+'] ':'')+l.text)));
  if(atEnd)lb.scrollTop=lb.scrollHeight;
}
function renderChips(){
  const p=S.settings.paused==='1',online=S.accounts.some(x=>x.running&&x.classic);
  const c=sel?S.chats.find(x=>x.key===sel):null;
  let t='Relais est actif et écoute...',off=false;
  if(!online){t='Hors ligne : en attente de Messenger';off=true}
  else if(p){t='Relais est en pause';off=true}
  else if(c&&!c.enabled){t='Relais est inactif dans cette conversation';off=true}
  else if(c&&c.is_group){t='Pas de LLM dans les groupes';off=true}
  $('#chip_state_t').textContent=t;$('#chip_state .od').classList.toggle('off',off);
  const cm=$('#chip_mode');if(c){cm.style.display='inline-flex';$('#chip_mode_t').textContent='Mode : '+(c.mode==='draft'?'Brouillon':'Automatique')}else cm.style.display='none';
  $('#chip_sec_t').textContent=c&&c.route==='e2ee'?'Chiffrée de bout en bout':'Session sécurisée';
}

function renderList(){
  if(!S.accounts.length){
    const rows=$('#rows');rows.dataset.sig='';rows.replaceChildren(el('div',{style:'padding:24px 18px;color:var(--muted);line-height:1.6'},
      el('b',{style:'color:var(--text);font-size:15px'},'Aucun compte Messenger'),el('br'),
      'Ajoute ton premier compte : une fenêtre de connexion officielle s\'ouvre, tu te connectes toi-même.',el('br'),
      el('button',{className:'primary',style:'margin-top:12px',textContent:'Ajouter un compte',onclick:()=>$('#bacc').click()})));
    return;
  }
  const q=$('#search').value.toLowerCase(),only=$('#onlyon').checked,rows=$('#rows');
  const list=[...S.chats].sort((x,y)=>((y.pinned|0)-(x.pinned|0))||(y.last_ts-x.last_ts));
  const lsig=JSON.stringify([tab,sel,q,only,$('#hideempty').checked,$('#accfilter').value,S.accounts.map(a=>a.name+a.label).join(),list.map(c=>[c.key,c.name,c.last_ts,c.last_text,c.enabled,c.unread,c.pinned,c.drafts,c.attention,c.pic,c.is_group,c.n_msgs])]);
  if(rows.dataset.sig===lsig)return;
  rows.dataset.sig=lsig;
  const keep=rows.scrollTop;rows.replaceChildren();
  for(const c of list){
    if(tab==='unread'&&!(c.unread>0))continue;
    if(tab==='groups'&&!c.is_group)continue;
    if(only&&!c.enabled)continue;
    if($('#accfilter').value&&c.account!==$('#accfilter').value)continue;
    if($('#hideempty').checked&&!c.n_msgs&&/^\d+$/.test(c.name)&&!c.enabled)continue;
    if(q&&!(c.name.toLowerCase().includes(q)))continue;
    const sw=el('label',{className:'switch',title:c.is_group?'Pas de LLM dans les groupes':'Activer / désactiver le LLM'},el('input',{type:'checkbox',checked:!!c.enabled,disabled:!!c.is_group}),el('i'));
    sw.onclick=e=>e.stopPropagation();
    sw.querySelector('input').onchange=async e=>{const r=await api('/api/chat/settings',{key:c.key,enabled:e.target.checked});if(r.error)toast(r.error,'err');refresh()};
    const line2=el('div',{className:'ln'});
    if(c.unread>0)line2.append(el('span',{className:'cnt',title:'Messages reçus sans réponse'},String(c.unread)));
    if(c.is_group)line2.append(el('span',{className:'gr'},'Groupe'));
    if(c.drafts)line2.append(el('span',{className:'badge dr'},c.drafts+' brouillon'));
    if(c.attention)line2.append(el('span',{className:'badge att'},'à toi'));
    const right=el('div',{className:'r'},el('div',{className:'ln'},el('span',{className:'tm'},fmt(c.last_ts)),c.is_group?'':sw),line2);
    const nm=el('div',{className:'n'});
    if(c.pinned){const pn=ih(IC.pin);pn.setAttribute('class','pn');nm.append(pn)}
    nm.append(el('span',{className:'nm'},c.name));
    if(S.accounts.length>1)nm.append(el('span',{className:'badge acc'},lbl(c.account)));
    const row=el('div',{className:'row'+(c.key===sel?' sel':''),tabIndex:0,role:'button'},avatar(c),el('div',{className:'t'},nm,el('div',{className:'s'},c.last_text||'')),right);
    row.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();row.click()}};
    row.onclick=()=>{sel=c.key;chatCache=null;dirty=false;document.body.classList.add('open');renderList();loadChat(true);renderChips()};
    rows.append(row);
  }
  if(!rows.children.length)rows.append(el('div',{style:'padding:30px 18px;color:var(--muted);text-align:center'},tab==='unread'?'Aucun message en attente de réponse.':tab==='groups'?'Aucun groupe.':'Aucune conversation.'));
  rows.scrollTop=keep;
}

async function loadChat(force){
  if(!sel)return;
  const r=await api('/api/chat?key='+encodeURIComponent(sel));
  if(r.error)return;
  const pane=$('#chatpane');
  if(force||!$('#msgs')){buildPane(r)}
  fillChat(r);
}

function emptyPane(){
  const e=el('div',{id:'empty'},el('div',{className:'ei'}),el('b',{className:'t'},'Choisis une conversation'),'Le LLM ne répond ',el('b',{},'jamais'),' tant que tu ne l\'actives pas pour elle.');
  e.querySelector('.ei').innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"><path d="M4 5.500h16v11H10l-4.500 3.500v-3.500H4z"/><path d="M8 10h8M8 13h5"/></svg>';
  return e;
}
const EMOJIS=['😀','😂','😊','😍','😘','😉','😎','🥰','🤔','😅','😢','😭','😡','🙏','👍','👎','👏','🙌','💪','🔥','❤️','💔','🎉','✨','😴','🤝','👀','🙈','😋','🥳','😬','🤗'];
function menuItem(label,fn,icon){const b=el('button',{className:'it',onclick:()=>{closeDrops();fn()}});if(icon)b.append(ih(IC[icon]));b.append(el('span',{},label));return b}
function buildPane(r){
  const pane=$('#chatpane');pane.replaceChildren();
  const back=el('button',{className:'ib mobback',textContent:'←',onclick:()=>{document.body.classList.remove('open');sel=null;pane.replaceChildren(emptyPane());renderChips()}});
  const sw=el('label',{className:'switch',id:'csw',title:'Activer / désactiver le LLM pour cette conversation'},el('input',{type:'checkbox'}),el('i'));
  sw.querySelector('input').onchange=async e=>{const x=await api('/api/chat/settings',{key:sel,enabled:e.target.checked});if(x.error){toast(x.error,'err')}refresh()};
  const bsearch=el('button',{className:'ib',id:'bcsearch',title:'Rechercher dans la conversation',onclick:()=>{const b=$('#csearch');b.classList.toggle('open');$('#bcsearch').classList.toggle('on',b.classList.contains('open'));if(b.classList.contains('open'))$('#csearch input').focus();else{$('#csearch input').value='';filterMsgs('')}}});bsearch.append(ih(IC.search));
  const bpin=el('button',{className:'ib',id:'bpin',title:'Épingler en haut de la liste',onclick:async()=>{await api('/api/chat/pin',{key:sel,pinned:$('#bpin').dataset.p!=='1'});refresh()}});bpin.append(ih(IC.pin));
  const bdel=el('button',{className:'ib',id:'bdel',title:'Supprimer cette conversation de ce hub (Messenger n\'est pas touché)',onclick:async()=>{
    if(!await ask('Cela efface ici l\'historique local, les brouillons et les pièces jointes en cache.\nRien n\'est supprimé dans Messenger, et la conversation réapparaîtra si un message arrive.',{title:'Supprimer cette conversation de ce hub ?',ok:'Supprimer',danger:true}))return;
    const x=await api('/api/chat/delete',{key:sel,confirm:true});if(x.error){toast(x.error,'err');return}
    document.body.classList.remove('open');sel=null;pane.replaceChildren(emptyPane());refresh()}});bdel.append(ih(IC.trash));
  const syn=el('button',{className:'it',id:'csync',title:'Rattrape les messages manqués',onclick:async()=>{closeDrops();const b=$('#csync'),sp=b.querySelector('span');b.disabled=true;sp.textContent='Synchronisation…';const r=await api('/api/chat/sync',{key:sel});b.disabled=false;sp.textContent='Synchroniser cette conversation';loadChat();refresh();if(r.error)toast(r.error,'err')}},ih(IC.refresh),el('span',{},'Synchroniser cette conversation'));
  const imp=el('button',{className:'it',id:'cimp',title:'Charge des messages plus anciens pour que le LLM connaisse la conversation et ton style',onclick:async()=>{closeDrops();const r=await api('/api/chat/import',{key:sel,pages:12});if(r.error)toast(r.error,'err');else if(!r.ok)toast('Une tâche est déjà en cours : attends sa fin (progression en bas à droite).','err');refresh()}},ih(IC.hist),el('span',{},'Importer l\'historique'));
  const mdrop=el('div',{className:'drop',id:'mdrop'},
    menuItem('Renommer',async()=>{const v=await askForm('Renommer la conversation',[{id:'name',label:'Nom à afficher',value:$('#cname').textContent}],'Renommer');if(!v)return;await api('/api/chat/rename',{key:sel,name:v.name});refresh()},'pencil'),
    syn,menuItem('Réglages de la conversation',toggleCset,'gear'));
  const adrop=el('div',{className:'drop',id:'adrop'},
    menuItem('Répondre maintenant',()=>forceReply(true),'bolt'),menuItem('Générer un brouillon',()=>forceReply(false),'pencil'),menuItem('Aperçu de la réponse',previewReply,'eye'),
    el('div',{className:'hr'}),menuItem('Préparer cette conversation',async()=>{LS('hub_cset','1');applyView();const x=await api('/api/chat/prepare',{key:sel});if(x.error)toast(x.error,'err');loadChat()},'spark'),imp);
  const bmore=el('button',{className:'ib',id:'bmore',title:'Plus d\'options','data-drop':'mdrop'});bmore.append(ih(IC.more));
  const bact=el('button',{id:'bact',className:'ib',title:'Actions : répondre maintenant, brouillon, aperçu…','data-drop':'adrop'});bact.append(ih(IC.bolt));
  const head=el('div',{id:'chead'},back,el('span',{id:'cav'}),
    el('div',{className:'who'},el('h2',{id:'cname'}),el('div',{className:'st'},el('span',{className:'dot'}),el('span',{id:'cstat'}),el('span',{id:'cbadge',className:'badge'}),
      el('button',{id:'climit',className:'badge att',style:'display:none;cursor:pointer',title:'Cliquer pour autoriser 10 réponses de plus par heure',onclick:async()=>{await api('/api/chat/raise_limit',{key:sel});loadChat();refresh()}}),
      el('button',{id:'cmute',className:'badge att',style:'display:none;cursor:pointer',title:'Cliquer pour ignorer ce silence et laisser le LLM répondre',onclick:async()=>{await api('/api/chat/unmute',{key:sel});loadChat();refresh()}}))),
    el('div',{className:'llm'},el('span',{},'LLM'),sw),
    el('div',{className:'ics'},bsearch,bpin,bdel,bmore,bact),mdrop,adrop);
  const csearch=el('div',{id:'csearch'},el('input',{type:'text',placeholder:'Rechercher dans la conversation…',oninput:e=>filterMsgs(e.target.value)}));
  const msgs=el('div',{id:'msgs'});
  const drafts=el('div',{id:'drafts'});
  const hint=el('input',{type:'text',id:'f_hint',placeholder:'Consigne ponctuelle (facultatif) : ex. « dis que j\'arrive dans 10 min »'});
  const fbtn=el('button',{className:'ok',id:'f_send',textContent:'Répondre maintenant',title:'Le LLM lit le dernier contexte et envoie une réponse tout de suite',onclick:()=>forceReply(true)});
  const dbtn=el('button',{id:'f_draft',textContent:'Brouillon',title:'Génère une réponse que tu valides avant envoi',onclick:()=>forceReply(false)});
  const pbtn=el('button',{id:'f_prev',textContent:'Aperçu',title:'Voir ce que le LLM répondrait, sans rien envoyer',onclick:previewReply});
  const forcebar=el('div',{id:'forcebar'},hint,pbtn,fbtn,dbtn);
  const ta=el('input',{type:'text',id:'sendtxt',placeholder:'Écrire un message…',title:'Écrire toi-même dans cette conversation (rien ne part sans que tu l\'envoies)'});
  ta.onkeydown=e=>{if(e.key==='Enter')sendManual()};
  const emo=el('div',{id:'emojis'},...EMOJIS.map(e=>el('button',{textContent:e,onclick:()=>{ta.value+=e;ta.focus();emo.classList.remove('open')}})));
  const bemoji=el('button',{className:'ib',id:'bemoji',title:'Emoji',onclick:ev=>{ev.stopPropagation();emo.classList.toggle('open')}});bemoji.append(ih(IC.smile));
  const bclip=el('button',{className:'ib',disabled:true,title:'Envoi de pièces jointes : pas encore disponible'});bclip.append(ih(IC.clip));
  const bimg=el('button',{className:'ib',disabled:true,title:'Envoi d\'images : pas encore disponible'});bimg.append(ih(IC.img));
  const bbolt=el('button',{id:'bbolt',title:'Répondre maintenant avec le LLM (consigne, aperçu, brouillon)',onclick:()=>{const f=$('#forcebar');f.classList.toggle('open');$('#bbolt').classList.toggle('on',f.classList.contains('open'));if(f.classList.contains('open'))$('#f_hint').focus()}});bbolt.append(ih(IC.bolt));
  const sendBtn=el('button',{className:'primary',id:'bsend',onclick:sendManual},ih(IC.send),'Envoyer');
  const compose=el('div',{id:'compose'},emo,bemoji,bclip,bimg,ta,bbolt,sendBtn);
  const cset=el('div',{id:'cset'},
    el('label',{},'Mode',el('select',{id:'c_mode'},new Option('Automatique (envoie seul)','auto'),new Option('Brouillon (tu valides)','draft'))),
    el('label',{},'Délai avant réponse (s)',el('input',{type:'number',id:'c_delay',min:0,max:300})),
    el('label',{},'Max réponses / heure',el('input',{type:'number',id:'c_max',min:1,max:100})),
    el('label',{className:'full',style:'flex-direction:row;align-items:center;gap:8px;color:var(--text)'},el('input',{type:'checkbox',id:'c_trusted',style:'width:auto'}),'Contact de confiance : ne pas bloquer sur les messages « suspects » ni demander de second contrôle (le filtre des liens, numéros et secrets reste actif)'),
    el('label',{className:'full',style:'flex-direction:row;align-items:center;gap:8px;color:var(--text)'},el('input',{type:'checkbox',id:'c_noquiet',style:'width:auto'}),'Ne jamais se taire quand j\'écris dans cette conversation (ignorer la reprise en main)'),
    el('label',{className:'full'},'Instructions pour cette conversation (qui est cette personne, ce que le LLM doit dire ou éviter)',el('textarea',{id:'c_inst'})),
    el('label',{className:'full'},'Mémoire de cette conversation — une ligne par information « - [catégorie|confiance] contenu » (confirmé, observé, probable). Tu peux corriger ou vider : tes lignes « confirmé » priment',el('textarea',{id:'c_mem',placeholder:'- [relation|confirmé] ami proche\n- [événement|confirmé] examen (échéance 2026-12-05)\n- [engagement|confirmé] doit envoyer le fichier (en attente)'}),el('button',{type:'button',style:'margin-top:6px;align-self:flex-start',textContent:'Mettre à jour maintenant',onclick:async()=>{const r=await api('/api/chat/memory/refresh',{key:sel});r.error?toast(r.error,'err'):toast('Mise à jour lancée : rouvre les réglages dans quelques secondes.','ok')}})),
    el('div',{className:'full',id:'c_prepbox'}),
    el('div',{className:'full',style:'display:flex;gap:8px;align-items:center'},el('button',{className:'primary',textContent:'Enregistrer ces réglages',onclick:saveChatSettings}),el('span',{id:'csaved'})));
  for(const id of ['c_mode','c_delay','c_max','c_inst','c_mem'])cset.querySelector('#'+id).oninput=()=>dirty=true;
  cset.querySelector('#c_noquiet').onchange=()=>dirty=true;
  cset.querySelector('#c_trusted').onchange=()=>dirty=true;
  const tob=el('button',{id:'tobottom',title:'Aller aux derniers messages','aria-label':'Aller aux derniers messages',onclick:()=>{msgs.scrollTo({top:msgs.scrollHeight,behavior:'smooth'})}});tob.append(ih(IC.chev));
  msgs.addEventListener('scroll',()=>tob.classList.toggle('show',msgs.scrollHeight-msgs.scrollTop-msgs.clientHeight>240),{passive:true});
  pane.append(head,csearch,msgs,drafts,forcebar,compose,cset,tob);
  applyView();
}
function filterMsgs(t){
  t=t.trim().toLowerCase();let first=null;
  document.querySelectorAll('#msgs .mrow').forEach(r=>{const hit=!t||r.textContent.toLowerCase().includes(t);r.style.display=hit?'':'none';r.querySelector('.m')?.classList.toggle('hit',!!t&&hit);if(t&&hit&&!first)first=r});
  document.querySelectorAll('#msgs .dsep').forEach(d=>d.style.display=t?'none':'');
  if(first)first.scrollIntoView({block:'center'});
}

