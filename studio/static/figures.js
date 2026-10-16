/**
 * CourseLM Studio — Original Source Figures System (Frontend)
 *
 * Implements:
 * 1. Source Figure Asset Library & Gallery View
 * 2. PDF.js Document Viewer with Zoom, Navigation, and Mouse Box Selection
 * 3. High-resolution Region Cropping and Asset Provenance Management
 * 4. Markdown Editor Figure Insertion with Width, Alignment, and Caption
 * 5. Missing Figure Audit & Candidate Matching Interface
 */

// Configure PDF.js worker
if (typeof pdfjsLib !== 'undefined') {
  pdfjsLib.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/pdf.worker.js';
}

let figuresState = [];
let figuresSources = [];
let cropperPdfDoc = null;
let cropperCurrentPage = 1;
let cropperTotalPages = 1;
let cropperZoom = 1.25;
let cropperSourcePath = '';
let isSelecting = false;
let selectionStart = { x: 0, y: 0 };
let currentSelection = null; // { x, y, w, h } in CSS px on canvas
let selectedPickerAsset = null;
let cropperLoadRequest = 0, cropperRenderRequest = 0;
let cropperReady = null, cropperRenderTask = null;

// ==========================================
// 1. Figures Library & Gallery
// ==========================================

async function loadFigures(jobId = current) {
  if (!jobId) return;
  try {
    const list = await api(`/api/jobs/${jobId}/figures`);
    if (jobId !== current) return;
    figuresState = list;
    updateFigureCountBadge(list.length);
    renderFiguresGrid();
    await loadFigureSources(jobId);
  } catch (err) {
    console.error('Failed loading figures:', err);
  }
}

async function loadFigureSources(jobId = current) {
  if (!jobId) return;
  try {
    const sources = await api(`/api/jobs/${jobId}/figures/sources`);
    if (jobId !== current) return;
    figuresSources = sources;
    const select = $('fig-source-select');
    if (select) {
      const cur = select.value;
      select.innerHTML = '<option value="">全部源文件</option>' +
        sources.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
      if (cur) select.value = cur;
    }
    const cropperSelect = $('cropper-file-select');
    if (cropperSelect) {
      const cur = cropperSelect.value;
      cropperSelect.innerHTML = sources.filter(s => s.toLowerCase().endsWith('.pdf'))
        .map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
      if (cur) cropperSelect.value = cur;
    }
  } catch (err) {
    console.error('Failed loading figure sources:', err);
  }
}

function updateFigureCountBadge(count) {
  const b1 = $('figure-count-badge');
  if (b1) b1.textContent = count;
  const b2 = $('figure-badge-count');
  if (b2) b2.textContent = count;
  const btn = $('open-figures-btn');
  if (btn) btn.disabled = false;
  const audBtnMain = $('audit-figures-btn');
  if (audBtnMain) audBtnMain.disabled = false;
  const insBtn = $('editor-insert-fig-btn');
  if (insBtn) insBtn.disabled = false;
  const audBtn = $('editor-audit-fig-btn');
  if (audBtn) audBtn.disabled = false;
}

function renderFiguresGrid() {
  const container = $('figures-grid');
  if (!container) return;

  const statusFilter = $('fig-status-select')?.value || '';
  const sourceFilter = $('fig-source-select')?.value || '';
  const searchKeyword = ($('fig-search-input')?.value || '').toLowerCase().trim();

  let filtered = figuresState.filter(f => {
    if (statusFilter && f.status !== statusFilter) return false;
    if (sourceFilter && f.source_file !== sourceFilter) return false;
    if (searchKeyword) {
      const target = (f.caption + ' ' + f.source_file + ' ' + f.adjacent_text).toLowerCase();
      if (!target.includes(searchKeyword)) return false;
    }
    return true;
  });

  if (!filtered.length) {
    container.innerHTML = `<div class="empty-state" style="grid-column: 1/-1; padding: 48px; text-align: center;">
      <div style="font-size: 32px; margin-bottom: 12px;">🖼</div>
      <b>暂无匹配的原图素材</b>
      <p style="color: #8898af; font-size: 12px; margin-top: 6px;">点击上方“扫描提取资料原图”自动解析，或点击“从 PDF 手动框选”精确截取。</p>
    </div>`;
    return;
  }

  container.innerHTML = filtered.map(fig => {
    const statusMap = {
      pending: { label: '待审核', class: 'status-pending' },
      confirmed: { label: '已确认', class: 'status-confirmed' },
      rejected: { label: '已驳回', class: 'status-rejected' }
    };
    const st = statusMap[fig.status] || { label: fig.status, class: '' };
    const typeLabel = fig.extraction_type === 'embedded' ? '嵌入原图' :
                     fig.extraction_type === 'cropped' ? '页面裁剪' : '独立图像';

    return `
      <div class="figure-card" data-id="${esc(fig.asset_id)}">
        <div class="figure-img-wrap" onclick="viewLargeFigure('${esc(fig.asset_id)}', '${esc(fig.caption)}')">
          <img src="/api/jobs/${current}/figures/asset/${esc(fig.asset_id)}" alt="${esc(fig.caption)}" loading="lazy">
          <span class="figure-tag type-tag">${esc(typeLabel)}</span>
          <span class="figure-tag ${st.class}">${esc(st.label)}</span>
        </div>
        <div class="figure-body">
          <div class="figure-caption" title="${esc(fig.caption)}">${esc(fig.caption || '未命名图示')}</div>
          <div class="figure-meta">
            <span>📄 ${esc(fig.source_file)} · 第 ${fig.page_index} 页</span>
            <span>📐 ${fig.width} × ${fig.height} · ${fig.dpi} DPI</span>
          </div>
          ${fig.adjacent_text ? `<div class="figure-text-hint" title="${esc(fig.adjacent_text)}">"${esc(fig.adjacent_text.slice(0, 75))}..."</div>` : ''}
          <div class="figure-actions">
            ${fig.source_file.toLowerCase().endsWith('.pdf') ? `
              <button class="outline-btn small-btn" onclick="openPdfCropper('${esc(fig.source_file)}', ${fig.page_index}, ${fig.bbox ? JSON.stringify(fig.bbox) : 'null'})">
                ⌕ 原页查看
              </button>` : ''}
            <button class="link-btn small-btn" onclick="copyFigureMarkdown('${esc(fig.asset_id)}', '${esc(fig.caption)}')">
              复制 Markdown
            </button>
            <div style="margin-left: auto; display: flex; gap: 4px;">
              <button class="icon-btn ${fig.status === 'confirmed' ? 'active-ok' : ''}" title="确认使用" onclick="setFigureStatus('${esc(fig.asset_id)}', 'confirmed')">✓</button>
              <button class="icon-btn ${fig.status === 'rejected' ? 'active-reject' : ''}" title="驳回" onclick="setFigureStatus('${esc(fig.asset_id)}', 'rejected')">✕</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

async function scanFiguresAction() {
  if (!current) return;
  notify('正在扫描源资料并提取原始题图，请稍候…');
  try {
    const res = await api(`/api/jobs/${current}/figures/scan`, 'POST', {});
    figuresState = res;
    updateFigureCountBadge(res.length);
    renderFiguresGrid();
    notify(`扫描完成，共发现 ${res.length} 个候选；候选不会自动插入正文`);
  } catch (err) {
    notify('扫描提取失败: ' + err.message);
  }
}

async function setFigureStatus(assetId, status) {
  if (!current) return;
  try {
    const updated = await api(`/api/jobs/${current}/figures/update`, 'POST', { asset_id: assetId, status: status });
    const idx = figuresState.findIndex(f => f.asset_id === assetId);
    if (idx !== -1) figuresState[idx] = updated;
    renderFiguresGrid();
    notify(`题图已设为「${status === 'confirmed' ? '已确认' : '已驳回'}」`);
  } catch (err) {
    notify('更新状态失败: ' + err.message);
  }
}

function copyFigureMarkdown(assetId, caption) {
  const code = `![${caption || '题图'}|width=0.8\\linewidth](figures/${assetId}.png)`;
  navigator.clipboard.writeText(code).then(() => {
    notify('已复制 Markdown 语法到剪贴板');
  }).catch(() => {
    prompt('复制以下 Markdown 语法：', code);
  });
}

function viewLargeFigure(assetId, caption) {
  const url = `/api/jobs/${current}/figures/asset/${assetId}`;
  window.open(url, '_blank');
}

// ==========================================
// 2. Interactive PDF Viewer & Region Cropper
// ==========================================

async function openPdfCropper(sourceRelPath, pageNum = 1, initialBbox = null) {
  if (!sourceRelPath) {
    const pdfs = figuresSources.filter(s => s.toLowerCase().endsWith('.pdf'));
    if (!pdfs.length) {
      notify('未找到 PDF 源文件');
      return;
    }
    sourceRelPath = pdfs[0];
  }

  cropperSourcePath = sourceRelPath;
  cropperCurrentPage = pageNum || 1;
  currentSelection = null;

  const modal = $('pdf-cropper-modal');
  if (modal) modal.classList.remove('hidden');

  const cropperSelect = $('cropper-file-select');
  if (cropperSelect) cropperSelect.value = sourceRelPath;

  if (await loadPdfDocument(sourceRelPath)) {
    await renderPdfPage(cropperCurrentPage, initialBbox);
  }
}

function closePdfCropper() {
  cropperLoadRequest++;
  cropperRenderRequest++;
  cropperReady = null;
  currentSelection = null;
  cropperRenderTask?.cancel();
  const modal = $('pdf-cropper-modal');
  if (modal) modal.classList.add('hidden');
}

async function loadPdfDocument(sourceRelPath) {
  const request = ++cropperLoadRequest, task = current;
  cropperSourcePath = sourceRelPath;
  cropperPdfDoc = null;
  cropperReady = null;
  currentSelection = null;
  cropperRenderRequest++;
  cropperRenderTask?.cancel();
  $('cropper-confirm-btn').disabled = true;
  const pdfUrl = `/api/jobs/${task}/figures/source-pdf?path=${encodeURIComponent(sourceRelPath)}`;
  try {
    $('cropper-status-msg').textContent = '正在加载 PDF…';
    const doc = await pdfjsLib.getDocument({ url: pdfUrl }).promise;
    if (request !== cropperLoadRequest || task !== current || sourceRelPath !== cropperSourcePath) {
      doc.destroy?.();
      return false;
    }
    cropperPdfDoc = doc;
    cropperTotalPages = doc.numPages;
    $('cropper-total-pages').textContent = cropperTotalPages;
    $('cropper-page-num').max = cropperTotalPages;
    return true;
  } catch (err) {
    if (request === cropperLoadRequest && task === current) {
      notify('加载 PDF 失败: ' + err.message);
      $('cropper-status-msg').textContent = '加载失败: ' + err.message;
    }
    return false;
  }
}

async function renderPdfPage(pageNum, highlightBbox = null) {
  const doc = cropperPdfDoc;
  if (!doc) return;
  const request = ++cropperRenderRequest, load = cropperLoadRequest;
  const task = current, source = cropperSourcePath, zoom = cropperZoom;
  pageNum = Math.max(1, Math.min(cropperTotalPages, pageNum));
  cropperCurrentPage = pageNum;
  cropperReady = null;
  currentSelection = null;
  cropperRenderTask?.cancel();
  $('cropper-confirm-btn').disabled = true;
  $('cropper-page-num').value = pageNum;
  const isCurrent = () => request === cropperRenderRequest && load === cropperLoadRequest &&
    task === current && source === cropperSourcePath && doc === cropperPdfDoc;
  try {
    const page = await doc.getPage(pageNum);
    if (!isCurrent()) return;
    const viewport = page.getViewport({ scale: zoom });
    const outputScale = window.devicePixelRatio || 1;
    // An old render must never paint on the visible canvas while a new one loads.
    const buffer = document.createElement('canvas');
    buffer.width = Math.floor(viewport.width * outputScale);
    buffer.height = Math.floor(viewport.height * outputScale);
    const rendering = page.render({canvasContext: buffer.getContext('2d'),
      transform: outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null,
      viewport});
    cropperRenderTask = rendering;
    await rendering.promise;
    if (!isCurrent()) return;
    const renderCanvas = $('pdf-render-canvas'), selectCanvas = $('pdf-selection-canvas');
    renderCanvas.width = buffer.width;
    renderCanvas.height = buffer.height;
    renderCanvas.style.width = viewport.width + 'px';
    renderCanvas.style.height = viewport.height + 'px';
    renderCanvas.getContext('2d').drawImage(buffer, 0, 0);
    selectCanvas.width = buffer.width;
    selectCanvas.height = buffer.height;
    selectCanvas.style.width = renderCanvas.style.width;
    selectCanvas.style.height = renderCanvas.style.height;
    cropperReady = {task, source, page: pageNum, load, request,
      cssWidth: viewport.width, cssHeight: viewport.height};
    initSelectionOverlay(selectCanvas, viewport.width, viewport.height);
    $('cropper-confirm-btn').disabled = false;
    $('cropper-status-msg').textContent = '原页已就绪 · 拖拽选择完整图形及参数';
    if (highlightBbox) {
      currentSelection = {x: highlightBbox.x0 * viewport.width, y: highlightBbox.y0 * viewport.height,
        w: (highlightBbox.x1 - highlightBbox.x0) * viewport.width,
        h: (highlightBbox.y1 - highlightBbox.y0) * viewport.height};
      drawSelectionBox();
      updateCropPreview();
    }
  } catch (err) {
    if (isCurrent() && err.name !== 'RenderingCancelledException') notify('渲染页面失败: ' + err.message);
  }
}

function initSelectionOverlay(canvas, cssWidth, cssHeight) {
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Mouse drag handlers
  canvas.onmousedown = (e) => {
    if (!cropperReady || cropperReady.task !== current) return;
    const rect = canvas.getBoundingClientRect();
    const scaleX = cssWidth / rect.width;
    const scaleY = cssHeight / rect.height;
    selectionStart.x = (e.clientX - rect.left) * scaleX;
    selectionStart.y = (e.clientY - rect.top) * scaleY;
    isSelecting = true;
    currentSelection = null;
  };

  window.onmousemove = (e) => {
    if (!isSelecting) return;
    const rect = canvas.getBoundingClientRect();
    const scaleX = cssWidth / rect.width;
    const scaleY = cssHeight / rect.height;
    const curX = Math.max(0, Math.min(cssWidth, (e.clientX - rect.left) * scaleX));
    const curY = Math.max(0, Math.min(cssHeight, (e.clientY - rect.top) * scaleY));

    const x = Math.min(selectionStart.x, curX);
    const y = Math.min(selectionStart.y, curY);
    const w = Math.abs(curX - selectionStart.x);
    const h = Math.abs(curY - selectionStart.y);

    currentSelection = { x, y, w, h };
    drawSelectionBox();
  };

  window.onmouseup = () => {
    if (!isSelecting) return;
    isSelecting = false;
    if (currentSelection && currentSelection.w > 10 && currentSelection.h > 10) {
      drawSelectionBox();
      updateCropPreview();
    }
  };
}

function drawSelectionBox() {
  const canvas = $('pdf-selection-canvas');
  if (!canvas || !currentSelection) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;

  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const { x, y, w, h } = currentSelection;
  const sx = x * dpr;
  const sy = y * dpr;
  const sw = w * dpr;
  const sh = h * dpr;

  // Semi-transparent overlay outside box
  ctx.fillStyle = 'rgba(18, 27, 48, 0.4)';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.clearRect(sx, sy, sw, sh);

  // Box border
  ctx.strokeStyle = '#6753d5';
  ctx.lineWidth = 2 * dpr;
  ctx.setLineDash([6 * dpr, 4 * dpr]);
  ctx.strokeRect(sx, sy, sw, sh);
  ctx.setLineDash([]);

  // Corner handles
  const handleSize = 8 * dpr;
  ctx.fillStyle = '#ffffff';
  ctx.strokeStyle = '#6753d5';
  ctx.lineWidth = 2 * dpr;
  const corners = [
    [sx, sy],
    [sx + sw, sy],
    [sx, sy + sh],
    [sx + sw, sy + sh]
  ];
  for (const [cx, cy] of corners) {
    ctx.fillRect(cx - handleSize / 2, cy - handleSize / 2, handleSize, handleSize);
    ctx.strokeRect(cx - handleSize / 2, cy - handleSize / 2, handleSize, handleSize);
  }

  // Dimension tag
  ctx.fillStyle = '#6753d5';
  ctx.font = `${11 * dpr}px sans-serif`;
  const label = `${Math.round(w)} × ${Math.round(h)} pt`;
  ctx.fillRect(sx, Math.max(0, sy - 20 * dpr), ctx.measureText(label).width + 10 * dpr, 18 * dpr);
  ctx.fillStyle = '#ffffff';
  ctx.fillText(label, sx + 5 * dpr, Math.max(14 * dpr, sy - 6 * dpr));

  // Update HUD
  const hud = $('cropper-hud');
  if (hud) {
    const normX0 = (x / (canvas.width / dpr)).toFixed(3);
    const normY0 = (y / (canvas.height / dpr)).toFixed(3);
    const normX1 = ((x + w) / (canvas.width / dpr)).toFixed(3);
    const normY1 = ((y + h) / (canvas.height / dpr)).toFixed(3);
    hud.textContent = `选区: [${normX0}, ${normY0}, ${normX1}, ${normY1}] · 尺寸: ${Math.round(w)} × ${Math.round(h)}`;
  }
}

function updateCropPreview() {
  if (!currentSelection) return;
  const renderCanvas = $('pdf-render-canvas');
  const previewCanvas = $('cropper-preview-canvas');
  if (!renderCanvas || !previewCanvas) return;

  const dpr = window.devicePixelRatio || 1;
  const { x, y, w, h } = currentSelection;

  previewCanvas.width = Math.min(400, w * dpr);
  previewCanvas.height = Math.min(300, h * dpr);

  const pctx = previewCanvas.getContext('2d');
  pctx.drawImage(
    renderCanvas,
    x * dpr, y * dpr, w * dpr, h * dpr,
    0, 0, previewCanvas.width, previewCanvas.height
  );
}

async function confirmCropAction() {
  const rendered = cropperReady;
  if (!rendered || rendered.task !== current || rendered.source !== cropperSourcePath ||
      rendered.page !== cropperCurrentPage || rendered.load !== cropperLoadRequest ||
      rendered.request !== cropperRenderRequest) {
    notify('请等待当前任务的原页完成加载与渲染，再选择裁剪区域');
    return;
  }
  if (!currentSelection || currentSelection.w < 10 || currentSelection.h < 10) {
    notify('请先在页面上拖拽框选图示区域');
    return;
  }
  const canvas = $('pdf-render-canvas');
  const dpr = window.devicePixelRatio || 1;
  const cssW = rendered.cssWidth;
  const cssH = rendered.cssHeight;

  const normX0 = Math.max(0.0, Math.min(1.0, currentSelection.x / cssW));
  const normY0 = Math.max(0.0, Math.min(1.0, currentSelection.y / cssH));
  const normX1 = Math.max(0.0, Math.min(1.0, (currentSelection.x + currentSelection.w) / cssW));
  const normY1 = Math.max(0.0, Math.min(1.0, (currentSelection.y + currentSelection.h) / cssH));

  const caption = $('cropper-caption-input')?.value.trim() || `第 ${cropperCurrentPage} 页选区题图`;

  notify('正在以 300 DPI 高清裁剪并生成题图资产…');
  try {
    const payload = {
      source_path: rendered.source,
      page: rendered.page,
      bbox: [normX0, normY0, normX1, normY1],
      caption: caption,
      status: 'confirmed'
    };
    const asset = await api(`/api/jobs/${rendered.task}/figures/crop`, 'POST', payload);
    if (rendered.task !== current || cropperReady !== rendered) return;
    notify(`题图资产已创建: ${asset.caption} (${asset.width}×${asset.height})`);
    closePdfCropper();
    await loadFigures(current);
  } catch (err) {
    notify('裁剪保存失败: ' + err.message);
  }
}

// ==========================================
// 3. Markdown Editor Figure Inserter
// ==========================================

function openFigurePicker() {
  selectedPickerAsset = null;
  const modal = $('figure-picker-modal');
  if (modal) modal.classList.remove('hidden');
  renderPickerGrid();
}

function closeFigurePicker() {
  const modal = $('figure-picker-modal');
  if (modal) modal.classList.add('hidden');
}

function renderPickerGrid() {
  const container = $('picker-figures-grid');
  if (!container) return;

  const search = ($('picker-search')?.value || '').toLowerCase().trim();
  const filtered = figuresState.filter(f => {
    if (f.status === 'rejected') return false;
    if (f.source_file.toLowerCase().endsWith('.pdf') && f.extraction_type !== 'cropped') return false;
    if (search) {
      return (f.caption + ' ' + f.source_file).toLowerCase().includes(search);
    }
    return true;
  });

  if (!filtered.length) {
    container.innerHTML = '<div class="empty-state" style="grid-column: 1/-1;">暂无完整原图可绑定；PDF 请先框选包含全部参数的原图区域。</div>';
    return;
  }

  container.innerHTML = filtered.map(f => `
    <div class="picker-card ${selectedPickerAsset?.asset_id === f.asset_id ? 'selected' : ''}" onclick="selectPickerAsset('${esc(f.asset_id)}')">
      <img src="/api/jobs/${current}/figures/asset/${esc(f.asset_id)}" alt="${esc(f.caption)}">
      <b>${esc(f.caption || f.asset_id)}</b>
      <small>${esc(f.source_file)} · p.${f.page_index}</small>
    </div>
  `).join('');
}

function selectPickerAsset(assetId) {
  selectedPickerAsset = figuresState.find(f => f.asset_id === assetId) || null;
  renderPickerGrid();
  updatePickerPreview();
}

function updatePickerPreview() {
  if (!selectedPickerAsset) {
    $('picker-insert-btn').disabled = true;
    $('picker-code-preview').textContent = '请选择一张题图…';
    return;
  }
  $('picker-insert-btn').disabled = false;
  const caption = $('picker-caption-override')?.value.trim() || selectedPickerAsset.caption || '题图';
  const mdCode = `![${caption}](figures/${selectedPickerAsset.asset_id}.png)`;
  $('picker-code-preview').textContent = mdCode;
}

async function insertFigureToEditor() {
  if (!selectedPickerAsset || !documentState || documentJob !== current) return;
  const textarea = $('markdown-editor');
  if (!textarea || textarea.disabled) return;
  const task = current, path = documentState.path;
  const cursorLine = textarea.value.substring(0, textarea.selectionStart).split('\n').length;
  const asset = selectedPickerAsset;
  const caption = $('picker-caption-override')?.value.trim() || asset.caption;
  if (dirty && !await saveDocument()) return;
  if (task !== current || documentState?.path !== path) return;
  const request = selectionRequest;
  textarea.disabled = true;
  $('picker-insert-btn').disabled = true;
  try {
    const result = await api(`/api/jobs/${task}/figures/bind`, 'POST', {
      path, revision: documentState.revision, asset_id: asset.asset_id,
      cursor_line: cursorLine, caption
    });
    if (task !== current || selectionRequest !== request || documentState?.path !== path) return;
    documentState = result.document;
    textarea.value = result.document.content;
    dirty = false;
    renderPreview();
    await loadDocuments();
    closeFigurePicker();
    notify('已绑定当前题目；后续构建自动核验题干和原图，变化后自动省略');
  } catch (err) {
    notify('未插入题图：' + err.message);
  } finally {
    textarea.disabled = editorBusy || loadingDocument || !documentState || documentJob !== current;
    $('picker-insert-btn').disabled = false;
  }
}

// ==========================================
// 4. Missing Figure Audit
// ==========================================

async function openFigureAudit() {
  if (!current) return;
  const modal = $('figure-audit-modal');
  if (modal) modal.classList.remove('hidden');
  $('audit-loading').classList.remove('hidden');
  $('audit-results').classList.add('hidden');

  try {
    const report = await api(`/api/jobs/${current}/figures/audit`);
    renderAuditResults(report);
  } catch (err) {
    notify('审核检查失败: ' + err.message);
    if (modal) modal.classList.add('hidden');
  } finally {
    $('audit-loading').classList.add('hidden');
    $('audit-results').classList.remove('hidden');
  }
}

function closeFigureAudit() {
  const modal = $('figure-audit-modal');
  if (modal) modal.classList.add('hidden');
}

function renderAuditResults(report) {
  $('audit-m-total').textContent = report.total_figures_in_handout;
  $('audit-m-valid').textContent = report.valid_source_figures;
  $('audit-m-missing').textContent = report.missing_image_files;
  $('audit-m-pending').textContent = report.pending_review_figures;
  $('audit-m-warnings').textContent = report.missing_figure_warnings.length;

  const warnList = $('audit-warnings-list');
  if (!warnList) return;

  if (!report.missing_figure_warnings.length) {
    warnList.innerHTML = `<div class="empty-state" style="padding: 24px; color: #2e7d32; text-align: center;">
      未发现缺图提示词；这不代表未绑定图片已经通过来源核验。
    </div>`;
    return;
  }

  warnList.innerHTML = report.missing_figure_warnings.map((w, idx) => {
    return `
      <div class="audit-warning-card">
        <div class="warn-head">
          <span class="warn-badge">⚠️ 缺图警告</span>
          <b>${esc(w.file_path)} : 第 ${w.line_number} 行</b>
          <span class="warn-trigger">匹配词: 「${esc(w.matched_text)}」</span>
        </div>
        <div class="warn-snippet">${esc(w.snippet)}</div>
        <div class="warn-candidates">
          <span style="font-size: 11px; color: #64748b; font-weight: 600;">推荐原图：</span>
          ${w.candidate_figures.length ? w.candidate_figures.map(cid => {
            const fig = figuresState.find(f => f.asset_id === cid);
            return fig ? `
              <div class="cand-item" onclick="openFigurePickerForSnippet('${esc(cid)}')">
                <img src="/api/jobs/${current}/figures/asset/${esc(cid)}" alt="${esc(fig.caption)}">
                <span>${esc(fig.caption)} (p.${fig.page_index})</span>
              </div>
            ` : '';
          }).join('') : '<span style="font-size: 11px; color: #94a3b8;">未自动匹配到明确原图，请在原图库中搜索或手动框选</span>'}
          <button class="outline-btn small-btn" style="margin-left: auto;" onclick="closeFigureAudit(); openPdfCropper();">
            在 PDF 中框选原图
          </button>
        </div>
      </div>
    `;
  }).join('');
}

function openFigurePickerForSnippet(assetId) {
  closeFigureAudit();
  openFigurePicker();
  selectPickerAsset(assetId);
}

// Navigation between Studio Views
function showFiguresPanel() {
  $('workspace').classList.add('hidden');
  $('editor').classList.add('hidden');
  $('figures-panel').classList.remove('hidden');
  loadFigures(current);
}

function backToWorkspaceFromFigures() {
  $('figures-panel').classList.add('hidden');
  $('workspace').classList.remove('hidden');
}

// Event Bindings
window.addEventListener('DOMContentLoaded', () => {
  $('open-figures-btn')?.addEventListener('click', showFiguresPanel);
  $('close-figures-panel')?.addEventListener('click', backToWorkspaceFromFigures);
  $('fig-scan-btn')?.addEventListener('click', scanFiguresAction);
  $('fig-crop-btn')?.addEventListener('click', () => openPdfCropper());
  $('fig-audit-btn')?.addEventListener('click', openFigureAudit);
  $('audit-figures-btn')?.addEventListener('click', openFigureAudit);

  $('fig-status-select')?.addEventListener('change', renderFiguresGrid);
  $('fig-source-select')?.addEventListener('change', renderFiguresGrid);
  $('fig-search-input')?.addEventListener('input', renderFiguresGrid);

  // Cropper Controls
  $('cropper-close-btn')?.addEventListener('click', closePdfCropper);
  $('cropper-prev-btn')?.addEventListener('click', () => {
    if (cropperCurrentPage > 1) renderPdfPage(cropperCurrentPage - 1);
  });
  $('cropper-next-btn')?.addEventListener('click', () => {
    if (cropperCurrentPage < cropperTotalPages) renderPdfPage(cropperCurrentPage + 1);
  });
  $('cropper-page-num')?.addEventListener('change', (e) => {
    renderPdfPage(parseInt(e.target.value) || 1);
  });
  $('cropper-file-select')?.addEventListener('change', (e) => {
    cropperSourcePath = e.target.value;
    cropperCurrentPage = 1;
    loadPdfDocument(cropperSourcePath).then(loaded => loaded && renderPdfPage(1));
  });
  $('cropper-zoom-in')?.addEventListener('click', () => {
    cropperZoom = Math.min(3.0, cropperZoom + 0.25);
    $('cropper-zoom-level').textContent = `${Math.round(cropperZoom * 100)}%`;
    renderPdfPage(cropperCurrentPage);
  });
  $('cropper-zoom-out')?.addEventListener('click', () => {
    cropperZoom = Math.max(0.5, cropperZoom - 0.25);
    $('cropper-zoom-level').textContent = `${Math.round(cropperZoom * 100)}%`;
    renderPdfPage(cropperCurrentPage);
  });
  $('cropper-confirm-btn')?.addEventListener('click', confirmCropAction);

  // Editor figure inserter
  $('editor-insert-fig-btn')?.addEventListener('click', openFigurePicker);
  $('editor-audit-fig-btn')?.addEventListener('click', openFigureAudit);
  $('picker-close-btn')?.addEventListener('click', closeFigurePicker);
  $('picker-insert-btn')?.addEventListener('click', insertFigureToEditor);
  $('picker-width-select')?.addEventListener('change', updatePickerPreview);
  $('picker-align-select')?.addEventListener('change', updatePickerPreview);
  $('picker-caption-override')?.addEventListener('input', updatePickerPreview);
  $('picker-search')?.addEventListener('input', renderPickerGrid);

  // Audit modal
  $('audit-close-btn')?.addEventListener('click', closeFigureAudit);
});
