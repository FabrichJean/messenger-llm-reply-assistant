// ---- page d'accueil : thème, navigation, « continuer plus tard »
(()=>{
  const L=$('#landing'),T=$('#l_theme');
  const sun='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></svg>';
  const moon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/></svg>';
  const setTheme=t=>{L.dataset.theme=t;document.documentElement.dataset.theme=t;T.innerHTML=t==='dark'?moon:sun;LS('hub_landing_theme',t);LS('hub_theme',t)};
  window.hubSetTheme=setTheme;
  {const m0=LS('hub_theme')||LS('hub_landing_theme')||'dark';setTheme(m0==='auto'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):m0);LS('hub_theme',m0)}
  T.onclick=()=>setTheme(L.dataset.theme==='dark'?'light':'dark');
  const SEC=[['top',()=>0],['fonctionnalites',()=>$('#s-fonctionnalites').offsetTop],['securite',()=>$('#s-securite').offsetTop],['faq',()=>$('#s-faq').offsetTop]];
  const links=[...L.querySelectorAll('.menu [data-go]')];
  const mark=k=>links.forEach(a=>a.classList.toggle('on',a.dataset.go===k));
  const here=()=>{let cur='top';for(const [k,f] of SEC)if(L.scrollTop+L.clientHeight*.5>=f())cur=k;return cur};
  L.addEventListener('click',e=>{
    const a=e.target.closest('[data-go]');if(!a)return;
    e.preventDefault();const S=SEC.find(x=>x[0]===a.dataset.go);
    if(S){L.scrollTo({top:S[1](),behavior:'smooth'});mark(S[0])}
  });
  L.addEventListener('scroll',()=>mark(here()),{passive:true});
  // FAQ : une seule réponse ouverte à la fois
  L.addEventListener('click',e=>{
    const q=e.target.closest('.fq-q');if(!q)return;
    const it=q.parentElement,open=!it.classList.contains('open');
    L.querySelectorAll('.fq-item').forEach(x=>{x.classList.remove('open');x.querySelector('.fq-q').setAttribute('aria-expanded','false')});
    if(open){it.classList.add('open');q.setAttribute('aria-expanded','true')}
  });
  $('#l_start2').onclick=()=>{L.scrollTo({top:0,behavior:'smooth'});setTimeout(()=>{const g=$('#l_go');if(!g.disabled)g.click()},600)};
  $('#l_open').onclick=()=>document.body.classList.add('later');
  // détails de la section Sécurité : texte complet et honnête, dans une fenêtre
  const DETAILS={
    locales:['Espace privé','Tes conversations, ton profil de style et tes sessions sont enregistrés sur le serveur du hub, dans un espace séparé par utilisateur : les autres utilisateurs, administrateur compris, n\'y ont pas accès dans l\'interface. Seul l\'opérateur du serveur y a techniquement accès : n\'utilise Relais que si tu lui fais confiance. Pour rédiger une réponse, le texte de la conversation concernée est transmis au modèle d\'IA (Claude), uniquement pour les conversations où tu as activé l\'assistant.'],
    connexion:['Connexion sécurisée','Tu te connectes toi-même sur la page officielle de Messenger, dans ton propre navigateur (extension Relais Connect) ou dans l\'application Android : Relais ne voit jamais ton mot de passe Messenger, il ne garde que la session. L\'accès à ton espace est protégé par identifiant et mot de passe, en HTTPS. Les conversations chiffrées de bout en bout sont déchiffrées par le serveur du hub pour que l\'assistant puisse répondre.'],
    controle:['Contrôle total','Rien n\'est actif par défaut. Pour chaque conversation tu choisis : désactivé, brouillon à valider, ou réponse automatique. Pause générale en un clic, limite de réponses par heure, silence dès que tu écris toi-même, aperçu avant tout envoi.'],
    collecte:['Aucune revente','Relais ne revend rien et n\'utilise pas tes messages pour autre chose que tes réponses. Les seules données qui quittent le serveur vont à Messenger (pour lire et envoyer) et à Claude (pour rédiger les réponses des conversations que tu as activées).'],
    transparence:['Fiable et transparent','Les messages reçus sont traités comme des données, jamais comme des consignes : filtres, classifieur, vérification avant envoi, leurre sarcastique en cas d\'attaque. À savoir : automatiser un compte personnel peut aller à l\'encontre des conditions de Meta.']};
  const dlg=$('#l_info');
  L.addEventListener('click',e=>{const b=e.target.closest('[data-info]');if(!b)return;const d=DETAILS[b.dataset.info];if(!d)return;$('#l_info_t').textContent=d[0];$('#l_info_p').textContent=d[1];dlg.showModal()});
  $('#l_info_ok').onclick=()=>dlg.close();
  dlg.addEventListener('click',e=>{if(e.target===dlg)dlg.close()});
  $('#l_later').onclick=()=>document.body.classList.add('later');
})();

// ---- statistiques, aide, thème
$('#bstats').onclick=async()=>{
  const r=await api('/api/stats');if(r.error){toast(r.error,'err');return}
  const k=(n,l)=>el('div',{},el('b',{},String(n)),el('span',{},l));
  const mb=b=>b>=1048576?(b/1048576).toFixed(1)+' Mo':Math.round(b/1024)+' Ko';
  $('#st_kpis').replaceChildren(k(r.chats,'conversations'),k(r.chats_on,'avec LLM actif'),k(r.messages,'messages enregistrés'),k(r.llm_total,'réponses du LLM'),k(r.llm_hour,'réponses cette heure'),k(r.drafts,'brouillons en attente'),k(r.attachments,'pièces jointes'),k(mb(r.media_bytes),'en cache'),k(r.attacks_7d,'alertes sécurité (7 j)'));
  const nf=n=>n>=1e6?(n/1e6).toFixed(1)+' M':n>=1e3?(n/1e3).toFixed(1)+' k':String(n);
  const KL={gen:'Réponses',classifier:'Détecteur d\'attaques',judge:'Second contrôle',decoy:'Leurres',style:'Style',prepare:'Préparation'};
  const ub=$('#st_usage');ub.replaceChildren();
  for(const [lab,u] of Object.entries(r.usage||{})){
    const t=u.total;
    ub.append(el('div',{style:'margin:8px 0 2px;font-weight:600'},'Sur '+lab+' : '+t.calls+' appel(s), '+nf(t.in)+' tokens en entrée dont '+t.cache_pct+' % servis par le cache, '+nf(t.out)+' en sortie, ≈ '+t.cost.toFixed(2)+' $'));
    const rows=Object.entries(u.kinds).sort((a,b)=>b[1].cost-a[1].cost);
    if(rows.length)ub.append(el('div',{className:'hint',style:'margin:0'},rows.map(([k,v])=>(KL[k]||k)+' : '+v.calls+' × · '+nf(v.in)+' entrée · '+nf(v.out)+' sortie · '+v.cost.toFixed(3)+' $').join('  |  ')));
  }
  if(!Object.values(r.usage||{}).some(u=>u.total.calls))ub.append(el('div',{className:'hint'},'Aucun appel mesuré pour l\'instant : la mesure démarre avec cette version.'));
  const mx=Math.max(1,...r.series.map(d=>d.contact+d.owner+d.llm));
  $('#st_bars').replaceChildren(...r.series.map(d=>{const t=d.contact+d.owner+d.llm;const col=el('div',{title:d.d+' : '+t+' message(s) — reçus '+d.contact+', toi '+d.owner+', LLM '+d.llm,style:'height:'+Math.max(3,Math.round(t/mx*100))+'%'});
    for(const [c,v] of [['l',d.llm],['o',d.owner],['c',d.contact]])if(v)col.append(el('i',{className:c,style:'height:'+Math.round(v/Math.max(1,t)*100)+'%'}));return col}));
  $('#dstats').showModal();
};
$('#st_close').onclick=()=>$('#dstats').close();
$('#bhelp').onclick=()=>$('#dhelp').showModal();
$('#hp_close').onclick=()=>$('#dhelp').close();
$('#bpw').onclick=async()=>{
  const r=await askForm('Changer mon mot de passe',[{id:'old',type:'password',label:'Mot de passe actuel',required:true},{id:'n1',type:'password',label:'Nouveau mot de passe',hint:'12 caractères minimum.',required:true},{id:'n2',type:'password',label:'Confirmer le nouveau',required:true}],'Changer');
  if(!r)return;if(r.n1!==r.n2){toast('Les deux nouveaux mots de passe diffèrent.','err');return}
  const d=await api('/api/me/password',{old:r.old,new:r.n1});
  if(d.ok){toast('Mot de passe changé : reconnecte-toi.','ok');setTimeout(()=>{location.href='/login'},1200)}else toast(d.error||'Échec.','err')};
async function renderUsers(){
  const d=await api('/api/users/list',{});const box=$('#u_list');box.replaceChildren();
  for(const u of d.users||[]){
    const mine=S.me&&u.name===S.me.name;
    const acts=el('div',{style:'display:flex;gap:6px;flex-wrap:wrap'},
      el('button',{textContent:'Nouveau mot de passe',onclick:async()=>{
        const r=await askForm('Nouveau mot de passe pour « '+u.name+' »',[{id:'p',type:'password',label:'Mot de passe',hint:'12 caractères minimum. Ses sessions seront fermées.',required:true}],'Réinitialiser');
        if(!r)return;const x=await api('/api/users/reset',{name:u.name,password:r.p});x.ok?toast('Mot de passe réinitialisé.','ok'):toast(x.error||'Échec.','err')}}));
    if(!mine)acts.append(el('button',{textContent:'Supprimer',onclick:async()=>{
      const own=u.accounts.length;
      if(!await ask('« '+u.name+' » sera supprimé'+(own?' et ses '+own+' compte(s) Messenger seront retirés du hub (les fichiers restent sur le disque)':'')+'.',{title:'Supprimer cet utilisateur ?',ok:'Supprimer'}))return;
      const x=await api('/api/users/delete',{name:u.name,confirm:true,remove_accounts:own>0});x.ok?(toast('Utilisateur supprimé.','ok'),renderUsers(),refresh()):toast(x.error||'Échec.','err')}}));
    box.append(el('div',{className:'arow'},el('div',{className:'ai'},el('b',{},u.name+(u.role==='admin'?' · administrateur':'')+(mine?' (toi)':'')),
      el('div',{className:'sts'},u.accounts.length?'Comptes : '+u.accounts.join(', '):'Aucun compte Messenger')),acts));
  }
  const ib=$('#u_invites');ib.replaceChildren();
  if((d.invites||[]).length){ib.append(el('h4',{},'Invitations en attente'));
    for(const v of d.invites){const left=Math.max(1,Math.round((v.exp*1000-Date.now())/3600000));
      ib.append(el('div',{className:'arow'},el('div',{className:'ai'},el('b',{},'Lien à usage unique'),el('div',{className:'sts'},'créé par '+v.by+' · expire dans ~'+left+' h')),
        el('button',{textContent:'Révoquer',onclick:async()=>{const x=await api('/api/users/invite_revoke',{id:v.id});x.ok?(toast('Invitation révoquée.','ok'),renderUsers()):toast(x.error||'Échec.','err')}})))}}
  $('#u_unowned').textContent=(d.unowned||[]).length?'Comptes sans propriétaire : '+d.unowned.join(', '):'';
}
$('#busers').onclick=async()=>{await renderUsers();$('#dusers').showModal()};
$('#u_close').onclick=()=>$('#dusers').close();
$('#u_inv').onclick=async()=>{
  const d=await api('/api/users/invite',{});if(!d.ok){toast(d.error||'Échec.','err');return}
  const link=location.origin+d.path;renderUsers();
  const dlg=el('dialog',{className:'ask'});const inp=el('input',{type:'text',readOnly:true,value:link,style:'width:100%'});
  const copy=el('button',{type:'button',className:'primary',textContent:'Copier le lien',onclick:async()=>{try{await navigator.clipboard.writeText(link);copy.textContent='Copié ✓'}catch(e){inp.select();toast('Copie impossible : sélectionne le lien et copie-le à la main.','err')}}});
  dlg.append(el('div',{className:'dh'},el('h3',{},"Lien d'invitation")),el('div',{className:'db'},el('div',{className:'hint',style:'margin-top:0'},"Envoie ce lien à la personne. Il ne marche qu'une fois et expire dans 48 h. Elle choisit elle-même son identifiant et son mot de passe. Ce lien ne sera plus affiché."),inp),
    el('div',{className:'df'},el('button',{type:'button',textContent:'Fermer',onclick:()=>dlg.close()}),copy));
  dlg.addEventListener('close',()=>dlg.remove());document.body.append(dlg);dlg.showModal();inp.select()};
$('#u_add').onclick=async()=>{
  const r=await askForm('Ajouter un utilisateur',[{id:'name',label:'Identifiant',placeholder:'ex. marie',hint:'2 à 32 caractères : minuscules, chiffres, . _ -',required:true},{id:'pw',type:'password',label:'Mot de passe',hint:'12 caractères minimum. Transmets-le à la personne : elle pourra le changer.',required:true},{id:'adm',type:'checkbox',label:'Administrateur (gère les utilisateurs)'}],'Créer');
  if(!r)return;const x=await api('/api/users/create',{name:r.name,password:r.pw,role:r.adm?'admin':'user'});
  x.ok?(toast('Utilisateur créé.','ok'),renderUsers()):toast(x.error||'Échec.','err')};
$('#blogout').onclick=async()=>{await fetch('/api/logout',{method:'POST',headers:{'X-Hub':'1','Content-Type':'application/json'},body:'{}'});location.reload()};

