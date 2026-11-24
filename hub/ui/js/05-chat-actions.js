function relaisAv(){const d=el('span',{className:'av sm',title:'Réponse du LLM'});d.style.background='#241510';d.style.border='2px solid #ff8a3d66';d.innerHTML='<svg viewBox="0 0 44 44" style="width:70%;height:70%"><use href="#i-logo"/></svg>';return d}
function fillChat(r){
  const c=r.chat;
  $('#cname').textContent=c.name;
  const lm=$('#climit');const full=c.enabled&&c.llm_hour>=c.max_per_hour;lm.style.display=full?'inline':'none';lm.textContent='Limite horaire atteinte ('+c.llm_hour+'/'+c.max_per_hour+') — cliquer pour +10';
  const mu=$('#cmute');mu.style.display=c.muted_min?'inline':'none';mu.textContent='LLM muet encore ~'+c.muted_min+' min — cliquer pour ignorer';
  const av=$('#cav');if(av.dataset.k!==c.key+c.pic){av.dataset.k=c.key+c.pic;av.replaceChildren(avatar(c,'xl'))}
  $('#cstat').textContent=c.is_group?'Groupe':(c.route==='e2ee'?'Chiffré de bout en bout':'Messagerie classique');
  const b=$('#cbadge');b.textContent=c.is_group?'groupe':(c.enabled?(c.mode==='draft'?'brouillon':'automatique'):'LLM inactif');
  const sw=$('#csw input');sw.checked=!!c.enabled;sw.disabled=!!c.is_group;
  const bp=$('#bpin');bp.dataset.p=c.pinned?'1':'0';bp.classList.toggle('on',!!c.pinned);bp.title=c.pinned?'Désépingler':'Épingler en haut de la liste';
  const ib=$('#cimp');if(ib){const hOk=S.accounts.some(a=>a.history==='enrolled');ib.disabled=c.route==='e2ee'&&!hOk;ib.title=c.route==='e2ee'&&!hOk?'Conversation chiffrée : restaure d\'abord l\'historique chiffré (onglet Historique) avec ton code PIN':'Charge des messages plus anciens pour que le LLM connaisse la conversation et ton style'}
  renderChips();
  const box=$('#msgs');const atEnd=box.scrollTop+box.clientHeight>=box.scrollHeight-60;
  const msig=c.key+JSON.stringify(r.messages.map(m=>[m.id,m.text,m.edited,m.deleted,m.local_edit,(m.atts||[]).map(a=>a.id+a.kind+a.has_main+(a.img||'')+(a.title||'')+(a.pending?'p':''))]));
  if(!window.__editing&&box.dataset.sig!==msig){box.dataset.sig=msig;
    const nodes=[];let lastDay='';
    for(const m of r.messages){
      const dk=new Date(m.ts).toDateString();
      if(dk!==lastDay){lastDay=dk;nodes.push(el('div',{className:'dsep'},dayLabel(m.ts)))}
      const mine=m.src!=='contact';
      const who=(m.src==='llm'?'LLM · ':m.src==='owner'?'Toi · ':'');
      const small=el('small',{},who+hm(m.ts)+(m.edited&&!m.deleted?' · modifié':'')+(m.local_edit&&!m.deleted?' · modifié ici':''));
      if(mine&&!m.deleted)small.append(ih(IC.check2));
      const d=el('div',{className:'m '+(m.src==='contact'?'':m.src)},...msgBody(m),small);
      if(m.deleted){d.style.opacity='.55';d.style.fontStyle='italic'}else{d.append(el('button',{className:'eb',title:"Modifier dans l'historique local (rien n'est envoyé à Messenger)",onclick:()=>editMsg(m,d)},ih(IC.pencil)))}
      const av=mine?(m.src==='llm'?relaisAv():placeholder({name:S.settings.owner||'Moi',key:'me'},'sm')):avatar(c,'sm');
      nodes.push(el('div',{className:'mrow'+(mine?' me':'')},...(mine?[d,av]:[av,d])));
    }
    if(!nodes.length)nodes.push(el('div',{style:'margin:auto;color:var(--muted);text-align:center'},'Aucun message pour l\'instant.'));
    box.replaceChildren(...nodes);
    const sv=$('#csearch input');if(sv&&sv.value)filterMsgs(sv.value);
  }
  if(atEnd||!box.dataset.init){box.scrollTop=box.scrollHeight;box.dataset.init=1}
  const dr=$('#drafts');const pv=$('#pvbox');dr.replaceChildren();if(pv)dr.append(pv);
  for(const d of r.drafts){
    const t=el('textarea',{value:d.text});
    dr.append(el('div',{className:'d'},el('b',{},'Brouillon du LLM'),t,el('div',{className:'btns'},
      el('button',{className:'ok',textContent:'Envoyer',onclick:async()=>{const x=await api('/api/draft',{id:d.id,action:'send',text:t.value});if(x.error)toast(x.error,'err');loadChat()}}),
      el('button',{textContent:'Ignorer',onclick:async()=>{await api('/api/draft',{id:d.id,action:'discard'});loadChat()}}))));
  }
  if(!dirty){$('#c_trusted').checked=!!c.trusted;$('#c_noquiet').checked=!!c.takeover_off;$('#c_mode').value=c.mode;$('#c_delay').value=c.delay_s;$('#c_max').value=c.max_per_hour;$('#c_inst').value=c.instructions||'';$('#c_mem').value=c.memory||''}
  const pb=$('#c_prepbox'),pr=r.prepared,sig=(pr?(pr.busy?'b':'')+(pr.text||'').length+(pr.err||''):'-')+c.key;
  if(pb.dataset.sig!==sig){
    pb.dataset.sig=sig;pb.replaceChildren();
    pb.append(el('button',{textContent:(pr&&pr.busy)?'Analyse de la conversation…':'Préparer cette conversation',disabled:!!(pr&&pr.busy),title:"Le LLM lit l'historique et te propose des instructions à relire",onclick:async()=>{const x=await api('/api/chat/prepare',{key:sel});if(x.error)toast(x.error,'err');loadChat()}}));
    if(pr&&pr.err)pb.append(el('div',{style:'color:var(--bad);margin-top:6px'},pr.err));
    if(pr&&pr.text){
      const ta=el('textarea',{value:pr.text});ta.style.minHeight='160px';ta.style.marginTop='8px';
      pb.append(el('div',{style:'margin-top:8px;padding:10px;border:1px dashed var(--accent);border-radius:10px'},
        el('b',{},'Proposition du LLM : relis et corrige avant de l\'utiliser'),ta,
        el('div',{style:'display:flex;gap:8px;margin-top:6px;align-items:center'},
          el('button',{className:'ok',textContent:'Mettre dans les instructions',onclick:async()=>{$('#c_inst').value=ta.value;dirty=true;await api('/api/chat/prepare/discard',{key:sel});loadChat();$('#csaved').textContent='Pense à cliquer sur « Enregistrer ces réglages »'}}),
          el('button',{textContent:'Ignorer',onclick:async()=>{await api('/api/chat/prepare/discard',{key:sel});loadChat()}}))));
    }
  }
  if(c.attention&&!dr.children.length){dr.append(el('div',{className:'d',style:'border-color:var(--warn)'},'Le LLM a passé la main'+(c.attention_note?' — raison : '+c.attention_note:'')+'. Réponds toi-même, ou utilise « Répondre maintenant » avec une consigne ponctuelle. ',el('button',{textContent:'OK',onclick:async()=>{await api('/api/clear_attention',{key:sel});refresh()}})))}
}

async function saveChatSettings(){
  const x=await api('/api/chat/settings',{key:sel,mode:$('#c_mode').value,delay_s:+$('#c_delay').value,max_per_hour:+$('#c_max').value,instructions:$('#c_inst').value,memory:$('#c_mem').value,takeover_off:$('#c_noquiet').checked,trusted:$('#c_trusted').checked});
  dirty=false;$('#csaved').textContent=x.error||'Enregistré ✓';setTimeout(()=>$('#csaved')&&($('#csaved').textContent=''),2000);refresh();
}
function editMsg(m,d){
  window.__editing=true;
  const ta=el('textarea',{value:m.text});ta.style.minHeight='70px';ta.style.width='100%';
  const finish=()=>{window.__editing=false;loadChat()};
  const note=el('small',{},"Modifie seulement l'historique de cette application : rien n'est envoyé dans Messenger. Le LLM lira la version corrigée.");
  const btns=[el('button',{className:'ok',textContent:'Enregistrer',onclick:async()=>{const r=await api('/api/message/edit',{key:sel,id:m.id,text:ta.value});if(r.error){toast(r.error,'err');return}finish()}}),
              el('button',{textContent:'Annuler',onclick:finish})];
  if(m.local_edit)btns.push(el('button',{textContent:"Rétablir l'original",onclick:async()=>{await api('/api/message/edit',{key:sel,id:m.id,revert:true});finish()}}));
  d.replaceChildren(ta,note,el('div',{style:'display:flex;gap:8px;margin-top:6px;flex-wrap:wrap'},...btns));
  d.style.maxWidth='92%';ta.focus();
}
async function forceReply(send){
  const b1=$('#f_send'),b2=$('#f_draft'),hint=$('#f_hint');
  b1.disabled=b2.disabled=true;const t1=b1.textContent;b1.textContent='Génération…';
  try{
    const r=await api('/api/chat/force',{key:sel,send,hint:hint.value});
    if(r.error)toast(r.error,'err');
    else if(r.skipped)toast('Le LLM a passé la main'+(r.reason?' — raison : '+r.reason:'')+'.\nAjoute une consigne ponctuelle pour le guider, ou assouplis les instructions de la conversation.');
    else hint.value='';
  }finally{b1.disabled=b2.disabled=false;b1.textContent=t1;loadChat();refresh()}
}
async function previewReply(){
  const b=$('#f_prev');b.disabled=true;const t0=b.textContent;b.textContent='Aperçu…';
  let r;try{r=await api('/api/chat/preview',{key:sel})}finally{b.disabled=false;b.textContent=t0}
  const box=$('#drafts');
  const old=$('#pvbox');if(old)old.remove();
  const wrap=el('div',{id:'pvbox',className:'d'});
  if(r.error){wrap.append(el('b',{},'Aperçu impossible : '),r.error)}
  else{
    const lab={reply:'Réponse que le LLM enverrait',decoy:'Réponse sarcastique (leurre) : message jugé suspect',skip:'Le LLM ne répondrait pas',blocked:'Réponse BLOQUÉE par le filtre de sécurité'}[r.kind]||r.kind;
    wrap.append(el('b',{},'Aperçu : '+lab));
    if(r.why)wrap.append(el('div',{style:'color:var(--muted);font-size:12px'},r.why));
    for(const i of r.info||[])wrap.append(el('div',{style:'color:var(--muted);font-size:12px'},'• '+i));
    if(r.text){
      const ta=el('textarea',{value:r.text});ta.style.minHeight='70px';ta.style.margin='6px 0';wrap.append(ta);
      const row=el('div',{style:'display:flex;gap:8px;flex-wrap:wrap'});
      if(r.kind!=='blocked')row.append(el('button',{className:'ok',textContent:'Envoyer ceci',onclick:async()=>{const x=await api('/api/chat/send_preview',{key:sel,text:ta.value});if(x.error)toast(x.error,'err');wrap.remove();loadChat();refresh()}}));
      row.append(el('button',{textContent:'Fermer',onclick:()=>wrap.remove()}));
      wrap.append(row);
    }else wrap.append(el('div',{style:'margin-top:6px'},el('button',{textContent:'Fermer',onclick:()=>wrap.remove()})));
  }
  box.prepend(wrap);
}
async function sendManual(){
  const i=$('#sendtxt');const t=i.value.trim();if(!t)return;i.value='';
  const x=await api('/api/send',{key:sel,text:t});if(x.error||!x.ok)toast(x.error||'Envoi impossible','err');loadChat();
}

let failN=0;
async function refresh(){
  try{S=await api('/api/state');failN=0;$('#offline').style.display='none'}catch(e){if(++failN>=2)$('#offline').style.display='block';return}
  renderTop();renderList();if(sel)loadChat(false);
}
