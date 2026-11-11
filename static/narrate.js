const state={voices:[],voice:null,clips:[],clip:null,mode:'sync-yellow',job:null,models:[],modelAttempts:0,scriptGenerated:false,customLibrary:false,extraClipsAvailable:false,extraClipsEnabled:false,extraClipsCount:0};
const $=s=>document.querySelector(s);
const escapeHtml=v=>String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#039;'}[c]));
function updateScript(){const text=$('#scriptInput').value;const words=text.trim()?text.trim().split(/\s+/).length:0;$('#wordCount').textContent=`${words} words`;$('#charCount').textContent=`${text.length} chars`;$('#durationEstimate').textContent=`Estimated narration · ${formatTime(words/3.2)}`;}
function formatTime(s){s=Math.max(0,Math.round(s));return `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;}
function targetDuration(){return Math.max(30,Number($('#targetDuration')?.value||30));}
if($('#targetDuration'))$('#targetDuration').oninput=()=>{$('#targetDurationValue').textContent=`${targetDuration()} seconds`;};
function captionSize(){return Math.max(64,Math.min(120,Number($('#captionSize')?.value||96)));}
if($('#captionSize'))$('#captionSize').oninput=()=>{$('#captionSizeValue').textContent=`${captionSize()} px`;};
function showScriptSource(message=''){const status=$('#scriptSourceStatus');if(!status)return;status.textContent=message;status.hidden=!message;}
function setScriptText(value,generatedByAi=false,sourceMessage=''){ $('#scriptInput').value=value;state.scriptGenerated=generatedByAi;updateScript();showScriptSource(sourceMessage); }
$('#scriptInput').addEventListener('input',()=>{state.scriptGenerated=false;showScriptSource('');updateScript();});$('#clearScript').onclick=()=>{$('#scriptInput').value='';$('#scriptPrompt').value='';state.scriptGenerated=false;showScriptSource('');updateScript();};
function renderVoices(){const query=$('#voiceSearch').value.toLowerCase();const active=document.querySelector('.voice-filter.active')?.dataset.filter||'All';const list=state.voices.filter(v=>(active==='All'||v.category===active||v.gender===active)&&(!query||`${v.name} ${v.category} ${v.language} ${v.engine}`.toLowerCase().includes(query)));$('#voiceGrid').innerHTML=list.length?list.map(v=>`<button class="voice-card ${state.voice?.id===v.id?'selected':''}" data-voice="${escapeHtml(v.id)}"><strong>${escapeHtml(v.name)}</strong><small>${escapeHtml(v.language)} · ${escapeHtml(v.gender)} · ${escapeHtml(v.engine)}</small><span class="voice-card-actions"><em>Select</em><i class="voice-preview">▶ Preview</i></span></button>`).join(''):'<div class="loading">No installed voices match this filter.</div>';document.querySelectorAll('.voice-card').forEach(card=>{card.onclick=async event=>{state.voice=state.voices.find(v=>v.id===card.dataset.voice);$('#selectedVoice').textContent=state.voice.name;if(event.target.closest('.voice-preview')){event.stopPropagation();try{const r=await fetch('/api/narrate/preview-voice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({voice:state.voice.id})});const d=await r.json();if(!r.ok)throw Error(d.error);new Audio(d.url).play();}catch(error){alert(error.message)}}renderVoices();updateReady();};});}
function renderFilters(){const categories=['All',...new Set(state.voices.map(v=>v.category))];$('#voiceFilters').innerHTML=categories.map((v,i)=>`<button class="voice-filter ${i?'':'active'}" data-filter="${escapeHtml(v)}">${escapeHtml(v)}</button>`).join('');document.querySelectorAll('.voice-filter').forEach(b=>b.onclick=()=>{document.querySelectorAll('.voice-filter').forEach(x=>x.classList.remove('active'));b.classList.add('active');renderVoices();});}
$('#voiceSearch').oninput=renderVoices;
function renderClips(){const q=$('#clipSearch').value.toLowerCase();const list=state.clips.filter(v=>!q||v.name.toLowerCase().includes(q));$('#clipGrid').innerHTML=list.length?list.map(v=>`<button class="clip-card ${state.clip?.id===v.id?'selected':''}" data-clip="${escapeHtml(v.id)}"><video muted playsinline preload="metadata" src="/api/narrate/media/${encodeURIComponent(v.id)}"></video><span class="clip-copy"><strong>${escapeHtml(v.name)}</strong><small>${v.duration_label} · ${v.width}×${v.height} · ${v.generated?'Clipify export':'Library'}</small></span></button>`).join(''):'<div class="loading">No Narrate clips found.</div>';document.querySelectorAll('.clip-card').forEach(card=>card.onclick=()=>{state.clip=state.clips.find(v=>v.id===card.dataset.clip);renderClips();updateReady();});}
$('#clipSearch').oninput=renderClips;
$('#customVideo').onchange=async e=>{const file=e.target.files[0];if(!file)return;const form=new FormData();form.append('video',file);try{const r=await fetch('/api/narrate/upload',{method:'POST',body:form});const d=await r.json();if(!r.ok)throw Error(d.error);const clips=await fetch('/api/narrate/videos');state.clips=(await clips.json()).videos||[];state.clip=state.clips.find(v=>v.id===d.video_id)||state.clips.find(v=>v.filename===d.video)||state.clips[0];renderClips();updateReady();}catch(err){alert(err.message)}};
function updateReady(){$('#generateNarrate').disabled=!($('#scriptInput').value.trim()&&state.voice&&state.clip);}
let downloadPollInterval = null;
function updateExtraClipsUI(){
  const btn=$('#btnDownloadExtra');
  const count=state.extraClipsCount||62;
  if(!btn)return;
  if(state.extraClipsEnabled || (state.clips && state.clips.length > 20)){
    btn.textContent=`✓ Additional Videos Added (${state.clips.length} total)`;
    btn.classList.add('installed');
  }else{
    btn.textContent=`⬇ Download Additional Videos (${count})`;
    btn.classList.remove('installed');
  }
}
async function pollDownloadProgress(){
  try{
    const r=await fetch('/api/narrate/download-extra-status');
    const isJson=r.headers.get('content-type')?.includes('application/json');
    if(!r.ok||!isJson)return;
    const d=await r.json();
    const s=d.state||{};
    const panel=$('#extraDownloadPanel');
    const bar=$('#extraDownloadBar');
    const title=$('#extraDownloadTitle');
    const stats=$('#extraDownloadStats');
    if(s.status==='downloading'){
      if(panel)panel.hidden=false;
      if(bar)bar.style.width=`${s.progress||0}%`;
      if(title)title.textContent=`Adding: ${s.current_file||'Preparing...'}`;
      if(stats)stats.textContent=`${s.downloaded_count||0} / ${s.total_count||62} (${s.progress||0}%)`;
    }else if(s.status==='completed'){
      clearInterval(downloadPollInterval);
      downloadPollInterval=null;
      if(bar)bar.style.width='100%';
      if(title)title.textContent='✓ All additional videos downloaded and ready!';
      if(stats)stats.textContent=`${s.total_count||62} / ${s.total_count||62} (100%)`;
      state.extraClipsEnabled=true;
      try{
        const vr=await fetch('/api/narrate/videos');
        const vd=await vr.json();
        state.clips=vd.videos||[];
        renderClips();
        updateReady();
        updateExtraClipsUI();
      }catch(e){}
      setTimeout(()=>{if(panel)panel.hidden=true;},4000);
    }else if(s.status==='error'){
      clearInterval(downloadPollInterval);
      downloadPollInterval=null;
      if(title)title.textContent=`Error: ${s.error||'Failed'}`;
    }
  }catch(err){
    clearInterval(downloadPollInterval);
    downloadPollInterval=null;
  }
}
async function startExtraDownload(){
  const btn=$('#btnDownloadExtra');
  const panel=$('#extraDownloadPanel');
  const bar=$('#extraDownloadBar');
  const title=$('#extraDownloadTitle');
  const stats=$('#extraDownloadStats');
  if(panel)panel.hidden=false;
  if(bar)bar.style.width='5%';
  if(title)title.textContent='Connecting to clips store...';
  if(stats)stats.textContent='0 / 62';
  try{
    const r=await fetch('/api/narrate/download-extra',{method:'POST'});
    const isJson=r.headers.get('content-type')?.includes('application/json');
    const d=isJson?await r.json():null;
    if(!r.ok||!d?.ok)throw new Error(d?.error||'Failed to start video download.');
    if(!downloadPollInterval){
      downloadPollInterval=setInterval(pollDownloadProgress,250);
    }
  }catch(err){
    if(title)title.textContent=`Download error: ${err.message}`;
  }
}
if($('#btnDownloadExtra')){$('#btnDownloadExtra').onclick=startExtraDownload;}

async function load(){
  try{
    const [v,c]=await Promise.all([fetch('/api/narrate/voices'),fetch('/api/narrate/videos')]);
    const cd=await c.json();
    state.voices=(await v.json()).voices||[];
    state.clips=cd.videos||[];
    state.customLibrary=!!cd.is_custom;
    state.extraClipsAvailable=!!cd.extra_clips_available;
    state.extraClipsEnabled=!!cd.extra_clips_enabled;
    state.extraClipsCount=cd.extra_clips_count||0;
    showClipFolder(cd.folder);
    showLibraryPaths(cd.folders);
    updateExtraClipsUI();
    if(state.voices[0]){
      state.voice=state.voices[0];
      $('#selectedVoice').textContent=state.voice.name;
    }
    if(state.clips[0])state.clip=state.clips[0];
    renderFilters();
    renderVoices();
    renderClips();
    updateReady();
  }catch(e){
    console.error('Failed to load narrate services:', e);
    $('#voiceGrid').innerHTML='<div class="loading">Narrate services unavailable.</div>';
  }
}

function showClipFolder(folder){const el=$('#clipFolder');if(el)el.textContent=folder||'No folder set yet';const reset=$('#useDefaultClipFolder');if(reset)reset.hidden=!state.customLibrary;}
function showLibraryPaths(folders){const el=$('#libraryPaths');if(!el)return;const list=(folders||[]).filter(Boolean);el.textContent=list.length?list.join('  +  '):'No clip folders found yet.';}
async function setClipFolder(folder){const r=await fetch('/api/narrate/library',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({folder})});const d=await r.json();if(!r.ok){alert(d.error||'Could not use that folder.');return false;}state.clips=d.videos||[];state.clip=state.clips[0]||null;state.customLibrary=!!d.is_custom;showClipFolder(d.folder);renderClips();updateReady();if(d.note)alert(d.note);return true;}
$('#useDefaultClipFolder').onclick=async()=>{if(confirm('Go back to the default Narrate clips folder?')){await setClipFolder('');}};
$('#chooseClipFolder').onclick=()=>{const input=$('#clipFolderInput');input.hidden=false;input.value='';input.focus();};
$('#clipFolderInput').onkeydown=async e=>{if(e.key!=='Enter')return;e.preventDefault();const value=e.target.value.trim();if(!value)return;await setClipFolder(value);e.target.hidden=true;};
$('#clipFolderInput').onblur=()=>{$('#clipFolderInput').hidden=true;};
async function loadModels(){const select=$('#scriptModel');if(!select)return;try{const r=await fetch('/api/models',{cache:'no-store'});const d=await r.json();state.models=d.models||[];if(state.models.length){state.modelAttempts=0;select.innerHTML='<option value="">Auto-select installed model</option>'+state.models.map(model=>`<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`).join('');return;}select.innerHTML='<option value="">No Ollama models found (retrying...)</option>';if(state.modelAttempts<5){state.modelAttempts+=1;setTimeout(loadModels,2000);}}catch(error){select.innerHTML='<option value="">Model service unavailable (retrying...)</option>';if(state.modelAttempts<5){state.modelAttempts+=1;setTimeout(loadModels,2000);}}}
$('#generateScript').onclick=async()=>{const prompt=$('#scriptPrompt').value.trim();if(!prompt){alert('Give the AI a prompt like “funny 15-second gaming joke” or “dramatic reveal with a hook”.');return;}const button=$('#generateScript');button.disabled=true;button.textContent='Working…';try{const r=await fetch('/api/narrate/script',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt,duration:targetDuration(),model:$('#scriptModel')?.value||''})});const d=await r.json();if(!r.ok)throw Error(d.error||'Could not generate the script.');const usedAi=Boolean(d.used_ai);setScriptText(d.script,true,usedAi?'Generated with the selected local model.':'Local starter text used; no complete AI draft was returned.');$('#scriptPrompt').value='';}catch(e){alert(e.message)}finally{button.disabled=false;button.textContent='Generate with AI';}};
$('#randomScript').onclick=async()=>{$('#randomScript').disabled=true;try{const r=await fetch('/api/narrate/random-script',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_duration:targetDuration()})});const d=await r.json();if(!r.ok)throw Error(d.error);const usedAi=Boolean(d.used_ai);setScriptText(d.script,true,usedAi?'Random script generated with the local model.':'Random local starter script used; no complete AI draft was returned.');$('#scriptPrompt').value='';}catch(e){alert(e.message)}finally{$('#randomScript').disabled=false;}};
$('#presetGrid').onclick=e=>{const b=e.target.closest('.preset');if(!b)return;document.querySelectorAll('.preset').forEach(x=>x.classList.remove('active'));b.classList.add('active');state.mode=b.dataset.preset;};
$('#improveScript').onclick=async()=>{const text=$('#scriptInput').value.trim()||$('#scriptPrompt').value.trim();if(!text){alert('Enter a script or AI prompt first.');return;}const button=$('#improveScript');button.disabled=true;button.textContent='Working…';try{const r=await fetch('/api/narrate/improve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({script:text})});const d=await r.json();if(!r.ok)throw Error(d.error||'Could not improve the script.');$('#improvedScript').textContent=d.improved||text;$('#improveBox').hidden=false;}catch(e){alert(e.message)}finally{button.disabled=false;button.textContent='Improve with AI';}};
$('#useOriginal').onclick=()=>$('#improveBox').hidden=true;$('#useImproved').onclick=()=>{setScriptText($('#improvedScript').textContent,true);$('#improveBox').hidden=true;};
async function generate(){const progress=$('#narrateProgress');progress.hidden=false;$('#generateNarrate').disabled=true;try{const r=await fetch('/api/narrate/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({script:$('#scriptInput').value,voice:state.voice.id,video:state.clip.id,speed:+$('#voiceSpeed').value,target_duration:state.scriptGenerated?targetDuration():null,caption_mode:state.mode,caption_size:captionSize()})});const d=await r.json();if(!r.ok)throw Error(d.error);state.job=d.job_id;await watch(d.job_id);}catch(e){alert(e.message);$('#generateNarrate').disabled=false;}}
$('#generateNarrate').onclick=generate;
async function watch(id){while(true){const r=await fetch(`/api/narrate/status/${id}`,{cache:'no-store'});const d=await r.json();$('#narrateBar').style.width=`${d.progress||0}%`;$('#narratePercent').textContent=`${d.progress||0}%`;$('#narrateStage').textContent=d.stage||'Working...';$('#narrateDetail').textContent=d.detail||'';if(d.status==='done'){const url=`/api/narrate/result-media/${encodeURIComponent(id)}/${encodeURIComponent(d.output)}`;$('#narratePreview').src=url;$('#narratePreview').load();$('#narratePreview').play().catch(()=>{});$('#narrateAudio').src=url;$('#narrateAudio').load();$('#resultInfo').hidden=false;$('#resultTitle').textContent=d.metadata?.title||'Your Narrated Short';$('#resultMeta').textContent=`${formatTime(d.duration)} · ${state.voice.name} · ${state.clip.name} · 1080×1920`;$('#narrateDownload').href=url;$('#generateNarrate').disabled=false;return;}if(d.status==='error'){throw Error(d.error||'Narration failed.');}await new Promise(x=>setTimeout(x,600));}}
async function loadHistory(){const container=$('#narrateHistory');if(!container)return;try{const r=await fetch('/api/narrate/history',{cache:'no-store'});const data=await r.json();const items=data.history||[];container.innerHTML=items.length?items.map(item=>`<article class="history-card"><div class="history-thumb"><video muted playsinline preload="metadata" src="${item.url}"></video></div><div class="history-copy"><strong>${escapeHtml(item.title)}</strong><small>${formatTime(item.duration)} · ${escapeHtml(item.voice)}</small></div><div class="history-actions"><a class="download" href="${item.url}" download>Download</a><button class="quiet history-delete" type="button" data-id="${escapeHtml(item.id)}">Delete</button></div></article>`).join(''):'<div class="history-empty">No narrated shorts yet.</div>';container.querySelectorAll('.history-delete').forEach(button=>button.onclick=async()=>{if(!confirm('Delete this narrated short?'))return;const r=await fetch(`/api/narrate/history/${encodeURIComponent(button.dataset.id)}`,{method:'DELETE'});if(r.ok)loadHistory();});}catch(error){container.innerHTML='<div class="history-empty">History is unavailable right now.</div>';}}
$('#refreshHistory')?.addEventListener('click',loadHistory);
load();loadModels();updateScript();loadHistory();
const resultVideo=$('#narratePreview');if(resultVideo){resultVideo.muted=false;resultVideo.volume=1;}
