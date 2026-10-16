const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
function harness(){
  const nodes=new Map();
  const element=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',disabled:false,dataset:{},style:{},listeners:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},addEventListener(name,fn){this.listeners[name]=fn;},setAttribute(){},getAttribute(){return null},removeAttribute(){},querySelectorAll(){return [];},scrollIntoView(){}});return nodes.get(id);};
  const context=vm.createContext({console,setTimeout,clearTimeout,setInterval,clearInterval,
    document:{getElementById:element,querySelectorAll:()=>[],querySelector:()=>element('dummy'),body:{style:{}}},
    window:{addEventListener(){}},confirm:()=>true,fetch:async()=>({ok:true,json:async()=>[]}),
    marked:{use(){}},DOMPurify:{sanitize:x=>x},katex:{renderToString:x=>x}});
  return {context,element};
}
(async()=>{
  const {context:c,element:e}=harness();
  vm.runInContext(fs.readFileSync('studio/static/app.js','utf8'),c);
  await new Promise(resolve=>setImmediate(resolve));
  vm.runInContext('globalThis.originalShowJob=showJob;',c);
  vm.runInContext(`sourceReady=true;current=null;$('course').value='测试';$('source').value='C:/fixture';api=async()=>({id:'123456789abc'});showJob=async id=>{globalThis.followed=id;};refreshHistory=async()=>{};`,c);
  await e('start').listeners.click();
  assert.equal(c.followed,'123456789abc','newly created job must be followed');
  const responses=new Map();
  c.api=url=>new Promise(resolve=>responses.set(url,resolve));
  vm.runInContext('showJob=originalShowJob;renderStatus=s=>{current=s.id;};current=null;',c);
  const old=c.originalShowJob('aaaaaaaaaaaa');
  const latest=c.originalShowJob('bbbbbbbbbbbb');
  responses.get('/api/jobs/bbbbbbbbbbbb')({id:'bbbbbbbbbbbb',status:'draft_ready'});
  await latest;
  responses.get('/api/jobs/aaaaaaaaaaaa')({id:'aaaaaaaaaaaa',status:'draft_ready'});
  await old;
  assert.equal(vm.runInContext('current',c),'bbbbbbbbbbbb','late navigation response must be ignored');

  const {context:r,element:n}=harness();
  r.$=n;r.current='123456789abc';r.esc=x=>x;r.notify=()=>{};r.renderStatus=()=>{};
  let resolveReview, saved;
  r.api=(url,method,payload)=>{
    if(url.endsWith('/review'))return new Promise(resolve=>{resolveReview=resolve;});
    if(url.endsWith('/save')){saved=payload;return Promise.resolve({...payload,review:'pending'});}
    return Promise.resolve([]);
  };
  vm.runInContext(fs.readFileSync('studio/static/editor.js','utf8'),r);
  vm.runInContext(`loadDocuments=async()=>{};loadVersions=async()=>{};documentJob=current;documentState={path:'chapters/A.md',revision:'revA',content:'A',review:'pending'};$('review').value='approved';`,r);
  const pending=n('review').onchange();
  vm.runInContext(`selectionRequest++;documentState={path:'chapters/B.md',revision:'revB',content:'B',review:'pending'};$('markdown-editor').value='B edited';dirty=true;`,r);
  resolveReview({path:'chapters/A.md',revision:'revA',content:'A',review:'approved'});
  await pending;
  await vm.runInContext('saveDocument()',r);
  assert.equal(saved.path,'chapters/B.md','late review response must never switch the save target');
  assert.equal(saved.content,'B edited');
  let resolveRestore, reloaded=false;
  r.api=url=>url.endsWith('/restore')?new Promise(resolve=>{resolveRestore=resolve;}):Promise.resolve({});
  r.recordReload=()=>{reloaded=true;};
  vm.runInContext(`selectDocument=async()=>recordReload();documentState={path:'chapters/A.md',revision:'revA',content:'A'};dirty=false;loadingDocument=false;$('versions').value='v1';`,r);
  const restore=n('restore-doc').onclick();
  assert.equal(n('markdown-editor').disabled,true,'restore must lock editing until response');
  vm.runInContext(`selectionRequest++;documentState={path:'chapters/B.md',revision:'revB',content:'B'};$('markdown-editor').value='B unsaved';dirty=true;loadingDocument=false;`,r);
  resolveRestore({});
  await restore;
  assert.equal(reloaded,false,'late restore must not reload a different chapter');
  assert.equal(n('markdown-editor').value,'B unsaved');

  const {context:f,element:fe}=harness();
  f.$=fe;f.current='aaaaaaaaaaaa';f.notify=()=>{};f.esc=x=>x;
  const drawing={clearRect(){},drawImage(){},fillRect(){},strokeRect(){},setLineDash(){},measureText:()=>({width:1}),fillText(){}};
  for(const id of ['pdf-render-canvas','pdf-selection-canvas'])fe(id).getContext=()=>drawing;
  f.document.createElement=()=>({style:{},getContext:()=>drawing});
  const pendingPdfs=new Map(), rendered=[];
  f.pdfjsLib={GlobalWorkerOptions:{},getDocument:({url})=>({promise:new Promise(resolve=>pendingPdfs.set(new URL(url,'http://local').searchParams.get('path'),resolve))})};
  vm.runInContext(fs.readFileSync('studio/static/figures.js','utf8'),f);
  const pdf=name=>({name,numPages:1,destroy(){},getPage:async()=>({
    getViewport:()=>({width:100,height:100}),render:()=>({promise:Promise.resolve().then(()=>rendered.push(name)),cancel(){}})})});
  const pa=vm.runInContext("openPdfCropper('A.pdf')",f);
  const pb=vm.runInContext("openPdfCropper('B.pdf')",f);
  pendingPdfs.get('B.pdf')(pdf('B.pdf'));await pb;
  pendingPdfs.get('A.pdf')(pdf('A.pdf'));await pa;
  assert.equal(vm.runInContext('cropperPdfDoc.name',f),'B.pdf','late PDF load cannot replace selected source');
  assert.deepEqual(rendered,['B.pdf'],'late PDF load must not render over current page');
  let cropPayload;
  f.api=async(url,method,payload)=>{cropPayload=payload;return {caption:'crop',width:50,height:50};};
  vm.runInContext('currentSelection={x:10,y:10,w:50,h:50};loadFigures=async()=>{};',f);
  await vm.runInContext('confirmCropAction()',f);
  assert.equal(cropPayload.source_path,'B.pdf');
  cropPayload=null;
  vm.runInContext("current='bbbbbbbbbbbb';currentSelection={x:10,y:10,w:50,h:50};",f);
  await vm.runInContext('confirmCropAction()',f);
  assert.equal(cropPayload,null,'old rendered page cannot be cropped under a new job');
  console.log('frontend async regressions passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
