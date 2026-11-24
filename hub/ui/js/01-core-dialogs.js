
const $=s=>document.querySelector(s);
const el=(t,props={},...kids)=>{const e=document.createElement(t);for(const k in props){if(k.startsWith('data-'))e.setAttribute(k,props[k]);else e[k]=props[k]}for(const k of kids)e.append(k);return e};

// ---- notifications et boîtes de dialogue (remplacent alert / confirm / prompt)
function floater(){let f=document.getElementById('fl');if(!f){f=el('div',{id:'fl'},el('div',{id:'tasks'}),el('div',{id:'toasts'}));f.querySelector('#toasts').setAttribute('role','status');f.querySelector('#toasts').setAttribute('aria-live','polite');document.body.append(f)}return f}
const buzz=(ms=8)=>{try{if(navigator.vibrate)navigator.vibrate(ms)}catch(e){}};
document.addEventListener('change',e=>{if(e.target.closest&&e.target.closest('.switch'))buzz(10)},true);
function toast(msg,kind){
  const box=floater().querySelector('#toasts');
  const t=el('div',{className:'toast'+(kind?' '+kind:'')},el('span',{},String(msg)),el('button',{textContent:'×','aria-label':'Fermer',onclick:()=>t.remove()}));
  box.append(t);setTimeout(()=>t.remove(),kind==='err'?9000:5000);
}
function ask(msg,o={}){
  return new Promise(res=>{
    const d=el('dialog',{className:'ask'},el('div',{className:'dh'},el('h3',{},o.title||'Confirmer')),el('div',{className:'db'},msg),
      el('div',{className:'df'},el('button',{textContent:o.cancel||'Annuler',onclick:()=>d.close('no')}),el('button',{className:o.danger?'danger':'primary',textContent:o.ok||'Confirmer',onclick:()=>d.close('yes')})));
    d.addEventListener('close',()=>{res(d.returnValue==='yes');d.remove()});
    document.body.append(d);d.showModal();
  });
}
function askForm(title,fields,okLabel){
  return new Promise(res=>{
    const inputs={};const body=el('div',{className:'db'});
    for(const f of fields){
      if(f.type==='checkbox'){const i=el('input',{type:'checkbox',checked:!!f.value});inputs[f.id]=i;body.append(el('label',{className:'chk'},i,el('span',{},f.label)))}
      else{const i=el('input',{type:f.type==='password'?'password':'text',autocomplete:f.type==='password'?'new-password':'off',value:f.value||'',placeholder:f.placeholder||'',required:!!f.required});inputs[f.id]=i;body.append(el('label',{},f.label),i);if(f.hint)body.append(el('div',{className:'hint'},f.hint))}
    }
    const d=el('dialog',{className:'ask'});
    const cancel=el('button',{type:'button',textContent:'Annuler',onclick:()=>d.close('no')});
    const wrap=el('form',{},el('div',{className:'dh'},el('h3',{},title)),body,el('div',{className:'df'},cancel,el('button',{className:'primary',type:'submit',textContent:okLabel||'Valider'})));
    wrap.onsubmit=e=>{e.preventDefault();d.close('yes')};
    d.append(wrap);
    wrap.style.cssText='display:flex;flex-direction:column;min-height:0;flex:1';
    d.addEventListener('close',()=>{if(d.returnValue==='yes'){const o={};for(const k in inputs)o[k]=inputs[k].type==='checkbox'?inputs[k].checked:inputs[k].value;res(o)}else res(null);d.remove()});
    document.body.append(d);d.showModal();const first=Object.values(inputs)[0];if(first&&(first.type==='text'||first.type==='password'))first.focus();
  });
}
