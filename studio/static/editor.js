/* All Markdown, including generated HTML and math, is sanitized before display. */
let documentState = null, documentJob = null, dirty = false, editorBusy = false;
let lastJobState = null, documentList = [], previewTimer;
let selectionRequest = 0;
let savingDocument = false;
let loadingDocument = false;
const reviewNames = {pending:'待审核', approved:'已审核', changes:'需要修改'};
function mathHTML(text, displayMode) {
  try { return katex.renderToString(text, {displayMode, throwOnError:false, trust:false, strict:'warn', maxExpand:500}); }
  catch (e) { return `<code>${esc(text)}</code>`; }
}
marked.use({
  extensions:[
    {name:'displayMath', level:'block', start:src=>src.indexOf('$$'), tokenizer(src){const m=/^\$\$\s*\n?([\s\S]+?)\$\$(?:\n|$)/.exec(src);if(m)return {type:'displayMath',raw:m[0],text:m[1]};},renderer:token=>mathHTML(token.text,true)},
    {name:'inlineMath', level:'inline', start:src=>src.indexOf('$'), tokenizer(src){const m=/^\$(?!\$)((?:\\.|[^$\n])+?)\$(?!\$)/.exec(src);if(m)return {type:'inlineMath',raw:m[0],text:m[1]};},renderer:token=>mathHTML(token.text,false)}
  ],
  renderer: {
    image(href, title, text) {
      let src = href;
      if (src.startsWith('figures/') && current) {
        const assetId = src.replace(/^figures\//, '').replace(/\.[^.]+$/, '');
        src = `/api/jobs/${current}/figures/asset/${assetId}`;
      }
      const parts = (text || '').split('|');
      const caption = parts[0] || '';
      let style = 'max-width: 80%; display: block; margin: 16px auto; border-radius: 6px; box-shadow: 0 2px 10px rgba(0,0,0,0.08);';
      for (const opt of parts.slice(1)) {
        if (opt.startsWith('width=')) {
          let val = opt.slice(6);
          if (val.includes('\\linewidth') || val.includes('\\textwidth')) {
            let num = parseFloat(val) || 0.8;
            style = `max-width: ${Math.round(num * 100)}%; display: block; margin: 16px auto; border-radius: 6px; box-shadow: 0 2px 10px rgba(0,0,0,0.08);`;
          } else if (val.endsWith('%')) {
            style = `max-width: ${val}; display: block; margin: 16px auto; border-radius: 6px; box-shadow: 0 2px 10px rgba(0,0,0,0.08);`;
          }
        }
      }
      const capHtml = caption ? `<figcaption style="text-align: center; font-size: 12px; color: #667085; margin-top: 6px; font-weight: 500;">${esc(caption)}</figcaption>` : '';
      return `<figure style="margin: 18px 0; text-align: center;"><img src="${src}" alt="${esc(caption)}" style="${style}">${capHtml}</figure>`;
    }
  }
});
function renderPreview() {
  const text = $('markdown-editor').value;
  const body = text.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '');
  $('markdown-preview').innerHTML = DOMPurify.sanitize(marked.parse(body), {
    FORBID_TAGS:['style','iframe','object','embed','form','input','button'],
    ADD_TAGS: ['figure', 'figcaption', 'img'],
    ADD_ATTR: ['src', 'alt', 'style', 'class', 'width', 'height'],
    ALLOW_DATA_ATTR:false
  });
  // Highlight after escaping; source never becomes executable HTML.
  $('highlight').innerHTML = text.split('\n').map(line=>{
    const safe = esc(line);
    if (/^#{1,6} /.test(line)) return `<span class="syntax-heading">${safe}</span>`;
    if (/^\s*>/.test(line)) return `<span class="syntax-quote">${safe}</span>`;
    if (/^---$|^```|^\|/.test(line)) return `<span class="syntax-marker">${safe}</span>`;
    return safe.replace(/(\$[^$]+\$|\*\*[^*]+\*\*|`[^`]+`)/g,'<span class="syntax-math">$1</span>');
  }).join('\n')+'\n';
}
function saveMessage(message, error=false) {
  $('save-state').textContent=message;
  $('save-state').classList.toggle('error',error);
}
function canLeave() { if(savingDocument){notify('正在保存，请稍候');return false;}return !dirty || confirm('当前章节有未保存修改。确认放弃这些修改？'); }
window.addEventListener('beforeunload', e=>{if(dirty){e.preventDefault();e.returnValue='';}});
$('markdown-editor').addEventListener('input',()=>{
  dirty = !!documentState && $('markdown-editor').value !== documentState.content;
  saveMessage(dirty?'有未保存修改 · Ctrl+S 保存':'已保存');
  clearTimeout(previewTimer);previewTimer=setTimeout(renderPreview,120);
});
$('markdown-editor').addEventListener('scroll',()=>{
  $('highlight').scrollTop=$('markdown-editor').scrollTop;
  $('highlight').scrollLeft=$('markdown-editor').scrollLeft;
});
window.addEventListener('keydown', e=>{
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'&&!$('editor').classList.contains('hidden')) {e.preventDefault();saveDocument();}
});
async function loadDocuments() {
  if(!current)return;
  const task=current;
  try {
    const docs=await api(`/api/jobs/${task}/documents`);
    if(task!==current)return;
    documentList=docs;
    $('open-editor').disabled=!docs.length;
    $('documents').innerHTML=docs.map(d=>`<button class="document-item ${documentState?.path===d.path?'active':''}" data-path="${esc(d.path)}"><strong>${esc(d.title)}</strong><small>${esc(reviewNames[d.review])} · ${esc(d.path.startsWith('chapters/')?'章节':'文档')}</small></button>`).join('');
    for(const button of $('documents').querySelectorAll('button'))button.onclick=()=>selectDocument(button.dataset.path);
  } catch(e) {notify(e.message);}
}
async function selectDocument(path, force=false) {
  if(!force&&!canLeave())return;
  const task=current;
  const request=++selectionRequest;
  loadingDocument=true;
  $('markdown-editor').disabled=true;
  $('save-doc').disabled=true;
  $('review').disabled=true;
  $('restore-doc').disabled=true;
  try {
    const doc=await api(`/api/jobs/${task}/document?path=${encodeURIComponent(path)}`);
    if(task!==current||request!==selectionRequest)return;
    loadingDocument=false;
    documentState=doc; documentJob=task; dirty=false;
    $('markdown-editor').value=doc.content;
    $('markdown-editor').disabled=editorBusy;
    $('save-doc').disabled=editorBusy;
    $('review').disabled=editorBusy;
    $('restore-doc').disabled=editorBusy;
    $('document-name').textContent=doc.path;
    $('review').value=doc.review;
    saveMessage(editorBusy?'任务进行中 · 只读':'已保存 · 使用 Ctrl+Z 撤销当前编辑');
    renderPreview();await loadDocuments();await loadVersions();
  } catch(e) {if(request===selectionRequest)loadingDocument=false;saveMessage(e.message,true);notify(e.message);}
}
async function loadVersions() {
  if(!documentState)return;
  const path=documentState.path;
  const versions=await api(`/api/jobs/${current}/versions?path=${encodeURIComponent(path)}`);
  if(documentState?.path!==path)return;
  $('versions').innerHTML='<option value="">选择已保存的历史版本</option>'+versions.map(v=>`<option value="${v.id}">${esc(v.time)} · ${v.id.slice(0,6)}</option>`).join('');
}
async function saveDocument() {
  if(!documentState||editorBusy||savingDocument||loadingDocument)return false;
  if(!dirty)return true;
  savingDocument=true;
  const content=$('markdown-editor').value;
  try {
    documentState=await api(`/api/jobs/${documentJob}/save`,'POST',{path:documentState.path,revision:documentState.revision,content});
    dirty=$('markdown-editor').value!==content;saveMessage(dirty?'已保存上一版本 · 当前仍有新修改':'保存成功 · 审核已重置，请重新编译');
    $('review').value=documentState.review;
    await loadDocuments();await loadVersions();renderStatus(await api('/api/jobs/'+current));
    return !dirty;
  } catch(e) {saveMessage('保存失败：'+e.message,true);notify(e.message);return false;}
  finally {savingDocument=false;}
}
$('save-doc').onclick=saveDocument;
$('reload-doc').onclick=()=>documentState&&selectDocument(documentState.path);
$('restore-doc').onclick=async()=>{
  if(!documentState||!$('versions').value||editorBusy)return;
  if(!confirm('将用选中版本替换当前章节。当前已保存内容会再备份，未保存修改将丢弃。'))return;
  const task=current, path=documentState.path, revision=documentState.revision, request=selectionRequest;
  const version=$('versions').value;
  loadingDocument=true;
  $('markdown-editor').disabled=true;
  $('save-doc').disabled=true;
  $('review').disabled=true;
  $('restore-doc').disabled=true;
  try {
    await api(`/api/jobs/${task}/restore`,'POST',{path,version,revision});
    if(task!==current||request!==selectionRequest)return;
    await selectDocument(path,true);
    const state=await api('/api/jobs/'+task);
    if(task===current){renderStatus(state);notify('历史版本已恢复，请重新编译');}
  }catch(e){if(task===current&&request===selectionRequest){loadingDocument=false;saveMessage(e.message,true);if(lastJobState)editorStatus(lastJobState);}}
};
$('review').onchange=async()=>{
  if(!documentState)return;
  if(dirty){$('review').value=documentState.review;notify('请先保存当前修改，再审核');return;}
  const task=current, path=documentState.path, revision=documentState.revision, request=selectionRequest;
  const value=$('review').value;
  $('review').disabled=true;
  try {
    const result=await api(`/api/jobs/${task}/review`,'POST',{path,revision,review:value});
    if(task!==current||request!==selectionRequest||documentState?.path!==path||documentState?.revision!==revision)return;
    documentState=result;
    await loadDocuments();
    const state=await api('/api/jobs/'+task);
    if(task===current)renderStatus(state);
  }catch(e){if(task===current&&request===selectionRequest){$('review').value=documentState.review;notify(e.message);}}
  finally {if(task===current&&request===selectionRequest)$('review').disabled=editorBusy||loadingDocument;}
};
$('open-editor').onclick=async()=>{
  $('editor').classList.remove('hidden');document.body.style.overflow='hidden';
  if(documentJob!==current){documentState=null;dirty=false;await loadDocuments();if(documentList.length)await selectDocument(documentList[0].path,true);}
  else if(!documentState&&documentList.length)await selectDocument(documentList[0].path,true);
};
$('close-editor').onclick=()=>{if(!canLeave())return;if(dirty&&documentState){$('markdown-editor').value=documentState.content;dirty=false;renderPreview();}$('editor').classList.add('hidden');document.body.style.overflow='';};
function previewTab(pdf) {
  $('markdown-preview').classList.toggle('hidden',pdf);$('pdf-preview').classList.toggle('hidden',!pdf);
  $('markdown-tab').classList.toggle('selected',!pdf);$('pdf-tab').classList.toggle('selected',pdf);
}
$('markdown-tab').onclick=()=>previewTab(false);$('pdf-tab').onclick=()=>previewTab(true);
$('rebuild').onclick=async()=>{
  if(dirty&&!await saveDocument())return;
  try {renderStatus(await api(`/api/jobs/${current}/build`,'POST',{}));previewTab(true);await showJob(current);}
  catch(e){saveMessage(e.message,true);}
};
$('deliver').onclick=async()=>{
  if(dirty){notify('请先保存修改并重新编译');return;}
  if(!confirm('确认已核查全部章节的公式、例题答案、事实来源与版权，并将当前 PDF 标记为可交付？'))return;
  try {renderStatus(await api(`/api/jobs/${current}/deliver`,'POST',{}));notify('人工审核通过，讲义可交付');}
  catch(e){notify(e.message);}
};
$('resume').onclick=async()=>{
  if(!canLeave())return;
  try {renderStatus(await api(`/api/jobs/${current}/resume`,'POST',{}));await showJob(current);}
  catch(e){notify(e.message);}
};
function editorStatus(s) {
  const wasBusy=editorBusy; const changed=lastJobState?.id!==s.id;
  editorBusy=['queued','running','building'].includes(s.status);
  $('editor-course').textContent=s.course+' / 讲义编辑';
  $('editor-state').textContent=s.stage;
  for(const id of ['rebuild','deliver','restore-doc','review','reload-doc'])$(id).disabled=editorBusy||loadingDocument;
  $('markdown-editor').disabled=editorBusy||loadingDocument||!documentState||documentJob!==s.id;
  $('save-doc').disabled=$('markdown-editor').disabled;
  const valid=!!s.pdf_current && !!s.artifacts?.pdf;
  $('pdf-message').textContent=editorBusy?'任务进行中，请等待编译结果。':valid?'最新 PDF 已编译；最终排版以此为准。':'当前内容尚无有效 PDF。请保存并重新编译；错误见下方日志。';
  $('pdf-frame').classList.toggle('hidden',!valid);
  $('editor-pdf-download').classList.toggle('hidden',!valid);
  const pdfURL=`/api/preview/${s.id}/pdf?v=${s.built_revision||''}`;
  if(valid&&$('pdf-frame').getAttribute('src')!==pdfURL)$('pdf-frame').src=pdfURL;
  if(!valid)$('pdf-frame').removeAttribute('src');
  $('editor-pdf-download').href=`/api/download/${s.id}/pdf`;
  $('compile-log').textContent=s.compile_log||s.detail||'暂无构建日志';
  if(!editorBusy&&(wasBusy||changed))loadDocuments();
  lastJobState=s;
}
