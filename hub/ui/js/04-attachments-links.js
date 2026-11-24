// ---- pièces jointes et liens
const URL_RE=/(https?:\/\/[^\s<>"']+)/g;
function linkify(t){
  const out=[];let last=0;t.replace(URL_RE,(m,u,i)=>{
    let url=u,tail='';const mt=url.match(/[.,;:!?)\]]+$/);if(mt){tail=mt[0];url=url.slice(0,-tail.length)}
    if(i>last)out.push(t.slice(last,i));
    out.push(el('a',{href:url,target:'_blank',rel:'noopener noreferrer',textContent:url.length>70?url.slice(0,67)+'…':url,title:url}));
    if(tail)out.push(tail);last=i+m.length;return m});
  if(last<t.length)out.push(t.slice(last));return out;
}
const fmtSize=n=>!n?'':n<1024?n+' o':n<1048576?Math.round(n/1024)+' Ko':(n/1048576).toFixed(1)+' Mo';
const fmtDur=ms=>{if(!ms)return '';const s=Math.round(ms/1000);return Math.floor(s/60)+':'+String(s%60).padStart(2,'0')};
const hostOf=u=>{try{return new URL(u).hostname.replace(/^www\./,'')}catch(e){return ''}};
const ATT_ONLY=/^\[(image|GIF|sticker|vidéo|message vocal|fichier|lien partagé|position|média éphémère|pièce jointe \/ sticker)\]$/;
function attPh(msg){return el('div',{className:'ph'},msg)}
const fbLabel=u=>{let p='';try{p=new URL(u).pathname}catch(e){}return /\/share\/r\//.test(p)||/\/reel\//.test(p)?'Reel Facebook':/\/share\/v\//.test(p)||/\/watch|\/videos?\//.test(p)?'Vidéo Facebook':/\/share\/p\//.test(p)||/\/posts\//.test(p)?'Publication Facebook':'Lien Facebook'};
function attNode(a){
  const src='/media/'+a.id,box=el('div',{className:'att-i'});
  const lazyImg=(cls,url)=>{const im=el('img',{className:cls||'',loading:'lazy',alt:a.name||a.kind,src:url});if(a.w&&a.h){im.width=Math.min(a.w,300);im.height=Math.round(Math.min(a.w,300)*a.h/a.w)}im.onerror=()=>im.replaceWith(attPh((a.kind==='sticker'?'Sticker':'Image')+' indisponible (expirée ou trop ancienne)'));return im};
  const vid=(extra)=>{const v=el('video',Object.assign({src:src,preload:'none',playsInline:true},extra||{}));v.onerror=()=>v.replaceWith(attPh('Vidéo indisponible'));return v};
  if(a.kind==='image'||(a.kind==='gif'&&!/^video/.test(a.mime))){return el('a',{href:src,target:'_blank',rel:'noopener'},lazyImg('',src))}
  if(a.kind==='gif'){const v=vid({autoplay:true,loop:true,muted:true,controls:false});v.preload='auto';v.muted=true;return v}
  if(a.kind==='sticker'){return lazyImg('st',src)}
  if(a.kind==='video'){const v=vid({controls:true});if(a.has_preview)v.poster=src+'?p=1';return v}
  if(a.kind==='audio'){const au=el('audio',{src:src,controls:true,preload:'none'});au.onerror=()=>au.replaceWith(attPh('Message vocal indisponible'));return el('div',{},au,a.dur?el('small',{style:'display:block'},fmtDur(a.dur)):'')}
  if(a.kind==='file'){return el('a',{className:'card',href:src+'?dl=1',download:a.name||'',target:'_blank',rel:'noopener'},(()=>{const i=el('span',{className:'ic'});i.append(ih(IC.file));return i})(),el('span',{className:'tx'},el('div',{className:'tt'},a.name||'Fichier'),el('div',{className:'ds'},[fmtSize(a.size),a.mime].filter(Boolean).join(' · ')||'Télécharger')))}
  if(a.kind==='link'){
    const body=[];
    const pimg=a.img||(a.has_preview?src+'?p=1':'');
    if(pimg)body.push(lazyImg('',pimg));
    const host=a.site||hostOf(a.action);
    const pth=(()=>{try{const u=new URL(a.action||'');return (u.pathname+u.search).replace(/^\/$/,'')}catch(e){return ''}})();
    const fb=(!a.title&&/(^|\.)(facebook\.com|fb\.watch|fb\.com)$/.test(hostOf(a.action)))?fbLabel(a.action):'';
    body.push(el('div',{className:'tx'},el('div',{className:'tt'},a.title||fb||host||'Lien'),(a.descr||a.subtitle)?el('div',{className:'ds'},a.descr||a.subtitle):(a.pending?el('div',{className:'ds'},'Chargement de l\'aperçu…'):(!a.title&&pth?el('div',{className:'ds'},pth):'')),(a.title&&host)?el('div',{className:'ds'},host):''));
    return a.action?el('a',{className:'lk',href:a.action,target:'_blank',rel:'noopener noreferrer'},...body):el('div',{className:'lk'},...body)}
  if(a.kind==='location'){return el('a',{className:'card',href:a.action||'#',target:'_blank',rel:'noopener noreferrer'},(()=>{const i=el('span',{className:'ic'});i.append(ih(IC.mappin));return i})(),el('span',{className:'tx'},el('div',{className:'tt'},a.title||'Position partagée'),el('div',{className:'ds'},'Ouvrir la carte')))}
  if(a.kind==='ephemeral'){return attPh('Média éphémère (non affichable)')}
  return attPh('Pièce jointe')
}
function msgBody(m){
  const nodes=[];
  if(m.deleted){nodes.push('Message supprimé');return nodes}
  const atts=m.atts||[];
  if(!(atts.length&&ATT_ONLY.test(m.text)))nodes.push(...linkify(m.text));
  if(atts.length)nodes.push(el('div',{className:'att'},...atts.map(attNode)));
  return nodes;
}
