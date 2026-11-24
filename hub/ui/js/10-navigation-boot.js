/* --- navigation --- */
document.querySelectorAll('#side .nv[data-view],#tabbar button[data-view]').forEach(b=>b.onclick=()=>{buzz();setView(b.dataset.view)});
$('#nv_hist').onclick=()=>$('#bhist').click();$('#nv_help').onclick=()=>$('#bhelp').click();
$('#a_more').onclick=()=>{$('#dacc').close();setView('security')};$('#a_help').onclick=()=>{$('#dacc').close();$('#bhelp').click()};
$('#sb_user').onclick=()=>setView('settings');$('#sb_out').onclick=()=>$('#blogout').click();
$('#bapp').onclick=()=>{closeDrops();setView('settings');setTimeout(()=>{const a=$('#set_appearance');if(a)a.scrollIntoView({behavior:'smooth'})},60)};
$('#search').addEventListener('input',()=>{if(VIEW!=='hub')setView('hub')});
document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();if(VIEW!=='hub')setView('hub');$('#search').focus()}});
matchMedia('(max-width:860px)').addEventListener('change',e=>{if(!e.matches&&VIEW==='home')setView('hub')});
hydrate();
setView(VIEW);

const PUBLIC=document.body.dataset.public==='1';
function publicMode(){
  document.body.classList.add('noacc');document.body.classList.remove('later');
  const go=()=>{location.href='/login'};
  for(const id of ['l_go','l_start2','l_open'])$('#'+id).onclick=go;
  $('#l_later').style.display='none';$('#l_cancel').style.display='none';$('#l_status').style.display='none';
  const lbl=$('#l_go .lbl');if(lbl)lbl.textContent='Se connecter';
  for(const id of ['l_start2','l_open']){const b=$('#'+id);if(b&&b.firstChild)b.firstChild.textContent='Se connecter'}
  const L=$('#landing');const h2=[...L.querySelectorAll('h2')].find(h=>/Connecter ton compte/.test(h.textContent));
  if(h2){h2.textContent='Accède à ton espace';const sub=h2.parentElement.querySelector('.sub');if(sub)sub.textContent='L\'accès se fait sur invitation. Connecte-toi avec ton identifiant.';const st=h2.parentElement.querySelector('.steps');if(st)st.style.display='none'}
  document.title='Relais';
}
applyView();
async function tick(){await refresh();setTimeout(tick,(S&&S.tasks&&S.tasks.some(t=>t.state==='running'))?900:2500)}
if(PUBLIC)publicMode();else tick();
