const $ = (id) => document.getElementById(id);
const MODES = { sprint:["考前冲刺","优先生成核心考点、典型题型、速记提要与高价值易错提醒。"], comprehensive:["完整精讲","重点展示概念原理、公式推导、详细例题和严谨的知识体系。"], practice:["题型突破","侧重识别信号、解题方法、典型变式、错误分析与练习。"] };
const STYLES = { academic:["学术经典","#1F4E79"], modern:["现代蓝调","#4F46E5"], warm:["暖色书卷","#8B5E3C"], minimal:["黑白极简","#222222"] };
let mode="sprint", style="academic", current=null, sourceReady=false, pollTimer=null, currentRequest=null, ignoreAccent=false;
const esc = s => String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#39;");
async function api(url, method="GET", payload){const resp=await fetch(url,{method,headers:payload?{"Content-Type":"application/json"}:undefined,body:payload?JSON.stringify(payload):undefined});const data=await resp.json();if(!resp.ok)throw new Error(data.error||`请求失败：${resp.status}`);return data;}
let toastTimer;function notify(message){const e=$("toast");e.textContent=message;e.classList.remove("hidden");clearTimeout(toastTimer);toastTimer=setTimeout(()=>e.classList.add("hidden"),4200);}
function syncSummary(){const c=$("course").value.trim()||"未命名课程";$("cover-course").textContent=c;$("s-mode").textContent=MODES[mode][0];$("s-style").textContent=STYLES[style][0];$("mode-note").textContent=MODES[mode][1];$("accent-label").textContent=$("accent").value.toUpperCase();}
for(const x of document.querySelectorAll(".mode-card"))x.addEventListener("click",()=>{mode=x.dataset.mode;for(const y of document.querySelectorAll(".mode-card")){let active=y===x;y.classList.toggle("selected",active);y.setAttribute("aria-pressed",active);} syncSummary();});
for(const x of document.querySelectorAll(".style-card"))x.addEventListener("click",()=>{style=x.dataset.style;for(const y of document.querySelectorAll(".style-card")){let active=y===x;y.classList.toggle("selected",active);y.setAttribute("aria-pressed",active);} if(!ignoreAccent)$("accent").value=STYLES[style][1];syncSummary();});
$("accent").addEventListener("input",()=>{ignoreAccent=true;syncSummary()});$("course").addEventListener("input",syncSummary);
$("source").addEventListener("input",()=>{sourceReady=false;$("s-files").textContent="尚未扫描";$("file-list").classList.add("hidden");$("source-summary").textContent="路径已更改，请重新扫描";});
$("browse").addEventListener("click",async()=>{try{const a=await api("/api/browse","POST",{});if(a.path){$("source").value=a.path;sourceReady=false;await scan();}}catch(e){notify(e.message);}});
const formatSize=n=>n>=1048576?(n/1048576).toFixed(1)+" MB":n>=1024?(n/1024).toFixed(1)+" KB":n+" B";
async function scan(){const path=$("source").value.trim();if(!path){notify("请先选择一个课程资料文件夹");return;}$("source-summary").textContent="扫描中…";try{const data=await api("/api/scan?path="+encodeURIComponent(path));sourceReady=true;$("s-files").textContent=data.count+" 份";$("source-summary").textContent=`发现 ${data.count} 份资料 · ${formatSize(data.total_bytes)}`;$("file-count").textContent=data.count+" 份";$("file-rows").innerHTML=data.files.slice(0,25).map(f=>`<div class="file-row"><span title="${esc(f.relative)}">▤ ${esc(f.relative)} <small>${esc(f.relative.split(".").pop().toUpperCase())}</small></span><span>${formatSize(f.size)}</span></div>`).join("")+(data.count>25?`<div class="file-row">另外还有 ${data.count-25} 个文件</div>`:"");$("file-list").classList.remove("hidden");notify("资料扫描完成，已准备好生成");}catch(e){sourceReady=false;$("source-summary").textContent="扫描失败";notify(e.message);}}
$("scan").addEventListener("click",scan);
$("start").addEventListener("click",async()=>{if(!sourceReady){notify("开始制作前请先扫描资料");return;}if(!$("course").value.trim()){notify("请填写课程名称");return;}const payload={course:$("course").value,source_path:$("source").value,mode,style,title:$("title").value,subtitle:$("subtitle").value,accent:$("accent").value};try{$("start").disabled=true;const state=await api("/api/jobs","POST",payload);notify("新任务已创建，正在启动生成引擎");await showJob(state.id);document.querySelector("#progress").scrollIntoView({behavior:"smooth"});await refreshHistory();}catch(e){notify(e.message);$("start").disabled=false;}});
function renderStatus(s){current=s.id; if(typeof editorStatus==="function")editorStatus(s);
  const finished=!(["queued","running","building"].includes(s.status));
  if(typeof loadFigures==="function"&&(!window._lastFigJob||window._lastFigJob!==s.id||finished)){window._lastFigJob=s.id;loadFigures(s.id);}
  const figBtn=$("open-figures-btn");if(figBtn)figBtn.disabled=false;
  const audBtn=$("audit-figures-btn");if(audBtn)audBtn.disabled=false;
  $("resume").classList.toggle("hidden",["queued","running","building"].includes(s.status)||(s.generation_complete??["review_ready","draft_ready","deliverable"].includes(s.status))); $("chapter-count").textContent=`章节 ${s.chapters_done||0} / ${s.chapters_total||"待大纲"}`; $("worker-log").textContent=(s.failed_stage?"失败阶段："+s.failed_stage+"\n":"")+(s.worker_log||"")+"\n"+(s.compile_log||"");$("job-status").textContent=({queued:"排队中",running:"生成中",review_ready:"待人工审核",draft_ready:"初稿已生成",failed:"生成失败",cancelled:"已取消",building:"编译中",deliverable:"可交付"})[s.status]||s.status;$("progress-title").textContent=s.stage||"等待开始";$("progress-detail").textContent=s.detail||`${s.course} · ${MODES[s.mode]?.[0]||""}`;$("percent").textContent=s.percent+"%";$("track-fill").style.width=s.percent+"%";
  $("events").innerHTML=s.events?.length?s.events.slice().reverse().map(v=>`<div class="event"><time>${esc(v.time)}</time><b>${esc(v.stage)}</b><span>${esc(v.message)}</span></div>`).join(""):'<div class="empty-state">任务运行中，等待首条事件…</div>';
  $("cancel").classList.toggle("hidden",finished);$("start").disabled=!finished;
  $("downloads").classList.toggle("hidden",!s.artifacts||!Object.keys(s.artifacts).length);
  for(const [kind,id] of [["pdf","pdf-link"],["markdown","md-link"],["tex","tex-link"]]){const el=$(id);el.classList.toggle("hidden",!s.artifacts?.[kind]);el.href=`/api/download/${s.id}/${kind}`;el.setAttribute("download","");}
  if(finished&&pollTimer){clearInterval(pollTimer);pollTimer=null;refreshHistory();}
}
let jobNavigation=0;
async function showJob(id){
  if(id!==current&&typeof canLeave==="function"&&!canLeave())return;
  const navigation=++jobNavigation;
  if(id!==current&&typeof documentState!=="undefined"){documentState=null;dirty=false;selectionRequest++;}
  if(pollTimer){clearInterval(pollTimer);pollTimer=null;}
  try{
    const s=await api("/api/jobs/"+id);
    if(navigation!==jobNavigation)return;
    renderStatus(s);
    if(!["queued","running","building"].includes(s.status))return;
  }catch(e){if(navigation===jobNavigation)notify(e.message);return;}
  pollTimer=setInterval(async()=>{
    try{
      const state=await api("/api/jobs/"+id);
      if(navigation===jobNavigation&&current===id)renderStatus(state);
    }catch(e){if(navigation===jobNavigation)notify(e.message);}
  },1500);
}
$("cancel").addEventListener("click",async()=>{if(!current||!confirm("确定停止当前生成任务吗？已写入的草稿将保留。"))return;try{renderStatus(await api(`/api/jobs/${current}/cancel`,"POST",{}));notify("任务已停止");}catch(e){notify(e.message);}});
async function refreshHistory(){try{const jobs=await api("/api/jobs");$("history-rows").innerHTML=jobs.length?jobs.slice(0,8).map(s=>`<div class="history-item" data-job="${esc(s.id)}" tabindex="0" role="button" aria-label="查看${esc(s.course)}"><div><b>${esc(s.course)}</b><small>${esc(s.created_at?.replace("T"," "))} · ${esc(MODES[s.mode]?.[0]||"")}</small></div><span class="hstatus">${({queued:"排队",running:"进行中",review_ready:"待审阅",draft_ready:"草稿完成",failed:"失败",cancelled:"取消",building:"编译中",deliverable:"可交付"})[s.status]||esc(s.status)}</span></div>`).join(""):'<div class="empty-state">暂无历史任务</div>';for(const row of document.querySelectorAll(".history-item")){row.addEventListener("click",()=>showJob(row.dataset.job));row.addEventListener("keydown",e=>{if(e.key==="Enter")showJob(row.dataset.job);});}}catch(e){notify("加载历史任务失败："+e.message);}}
(async()=>{try{await api("/api/health");await refreshHistory();}catch(e){notify("无法连接本地 CourseLM 服务："+e.message);}})();syncSummary();
