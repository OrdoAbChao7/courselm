# Studio 本机验收记录

日期：2026-10-15（Asia/Shanghai）。本次直接修改工作区，未提交、未推送。

## 审计与保留

起始分支为 `feat/cram-course-handout-style`。起始已有未提交的 `config/prompts.yaml`、`modules/latex_renderer.py`，以及未跟踪的 Studio、运行数据和维护脚本。沿用现有 Studio 的标准库 HTTP / 原生前端，没有推倒重写。`launcher.py` 不存在，使用根目录批处理和 `python -m studio.server` 启动。

工作期间还出现了 `modules/prompt_runner.py` 的来源标签修复及 `tests/test_prompt_runner.py` 的改动，已保留。本次只在该引擎增加可选 `on_progress` 回调，不重写用户的来源处理逻辑。

现有数据流为 `run_pipeline → raw/v3 → generate_all → md → build_handout → manuscript → write_latex_document → main.tex → compile_latex → PDF`。原 Studio 的 v2 观察路径和旧附录 Prompt 字段已修正为当前 v3 合同。当前题型索引由章节提取，并非额外 AI 调用。

## 本次修改/新增清单

- `studio/engine.py`：保留三模式、四风格映射，适配真实 Prompt 模型，来源可读性与链接检查，灰度主题。
- `studio/server.py`：文档、保存、版本、恢复、审核、交付、后台重编译、续跑 API；同源限制、任务隔离、日志、独占端口与取消进程树。
- `studio/worker.py`：真实阶段回调、v3 进度、失败保留成功稿、缓存续跑时保留人工编辑、调用统一构建适配器。
- 新增 `studio/workspace.py`：路径边界、原子保存、内容版本、历史备份、审核、构建指纹、导出时校验、TeX 预检。
- `studio/static/index.html`、`app.js`、`style.css`，新增 `editor.js`、`favicon.svg`：三栏编辑、语法高亮、公式/表格预览、未保存提示、历史恢复、审核与 PDF 预览。
- 新增 `studio/static/vendor/`：本地 Marked、DOMPurify、KaTeX、字体与各自许可证，版本见 README_STUDIO。
- `modules/handout_builder.py`：增加可选源标题优先、禁止自动重写人工索引选项，CLI 默认不变。
- `modules/prompt_runner.py`：增加可选阶段回调，CLI 默认不变。
- `main.py`：编译关闭 shell escape、增加文件行号、遇错停止、保守文件访问环境及超时处理。
- `pyproject.toml`：分发 Studio 包及静态资源；无新增服务端运行依赖。
- `.gitignore`：排除 Studio 私有数据和浏览器临时记录。
- `启动CourseLM工作台.bat`：优先使用项目虚拟环境。
- `README.md`、`README_STUDIO.md`、本记录：启动、流程、数据与限制。
- 新增 `scripts/studio_acceptance.py`：公开导数离线夹具，实际编译，不调用 NotebookLM。
- 新增 `studio/tests/test_workspace.py`、`test_http.py`、`test_worker.py`、`test_frontend.py`、`frontend_regressions.cjs`、`test_browser.py`。原 `studio/tests/test_studio.py` 保留。

## 自动化结果

```powershell
.venv\Scripts\python -m pytest tests studio/tests -q
```

最终结果：**192 passed, 2 skipped**。跳过项为未设置环境变量的可选真实浏览器测试，以及未授予 Windows 创建符号链接权限的 symlink 测试。Windows junction 真实创建、跨界读取/扫描/构建拒绝测试已通过，不依赖 symlink 特权。

```powershell
node --check studio/static/app.js
node --check studio/static/editor.js
```

均通过。Node VM 回归覆盖新任务跟踪、旧任务响应、审核晚返回造成错章保存、恢复晚返回造成丢稿。FakeService 使用原 CLI 测试的有效响应合同；测试真实运行 Studio worker，验证失败续跑只请求失败章节，已保存编辑保留并进入最终构建。

HTTP 实测覆盖历史、版本冲突、跨任务拒绝、跨站拒绝、同名课程目录隔离、源文件不变、原生文件夹选择器调用/销毁。文件夹选择器测试替换了对话框返回值，未声称自动操作真实 Windows 原生弹窗。

## 浏览器与真实 XeLaTeX

环境为本机 Chromium、MiKTeX XeLaTeX。首次沙箱内编译因无法写入本机 MiKTeX 日志目录失败；在获准的正常本机权限下完成真实编译。

```powershell
.venv\Scripts\python scripts/studio_acceptance.py
$env:COURSELM_BROWSER_URL='http://127.0.0.1:8877'
$env:COURSELM_TEST_JOB='4dd5474a1609'
.venv\Scripts\python -m pytest studio/tests/test_browser.py -q
```

结果：**1 passed**。此项为真实浏览器与 XeLaTeX 集成测试，不是服务端假编译。测试已验证：

- 修改 Markdown 后即时公式与表格预览；恶意 HTML 不执行。
- 保存成功、重新组装、实际编译 PDF；用 pypdf 提取 PDF 文本，确认包含 `STUDIO_ACCEPTANCE_42`。
- Markdown、TeX、PDF 均可下载；嵌入 PDF 预览请求可用。
- 全文件审核通过后整份确认可交付。
- 注入未定义数学命令，实际 XeLaTeX 报错；草稿仍存在，过期 PDF 下载被拒绝。
- 修复同一草稿后再次编译成功，审核保持待确认。
- 无 JavaScript pageerror 或浏览器 console error。

截图：`output/playwright/studio-editor.png`。夹具任务、版本备份和可检查 PDF 留在已忽略的本地任务/产物目录。最终夹具清理掉了攻击测试文本和重复修改标记。

## NotebookLM 联网验收边界

本机检测到登录态，已实际连接 NotebookLM、新建独立验收 Notebook、上传 1 份公开导数样例 PDF 并索引成功。该任务编号为 `ea06bf600d38`，相关信息保留在本地任务记录。

上游大纲模型请求长时间未返回，因此用该任务验证了取消，状态为 cancelled，缓存和上传记录保留。**没有声称真实模型完整生成到 PDF 已通过**；完整引擎流程由 FakeService 回归验证，真实模型端到端仍需网络及上游响应正常后复验。没有上传用户原课程资料进行本次验收。

## 已知限制与下一步

- 本地个人工具，只监听 127.0.0.1，不支持多用户、公网或多个服务实例同时编辑同一任务。
- 当前全局串行调度；失败续跑会补失败章节，不提供对成功章节的强制单章重生成。单章编辑、重编译已可用。
- 保存为显式保存；浏览器撤销栈不跨章节，磁盘历史可恢复，但暂不自动清理版本。
- 标题、副标题、颜色和两种真实布局可用；不提供字体、版芯或 PDF 所见即所得编辑。
- 原始 TeX 程序控制与文件访问指令被拒绝，高级宏和自定义环境可能不能编译；不是公网不可信 TeX 执行沙箱。
- 内容准确性、题型索引与例题来源仍需人工核对。原始生成引擎的来源标签处理没有在本次被重写。
- 下次优先在上游模型响应正常时复验真实资料全链路，再考虑单章强制重试和版本保留策略。

`studio_data/`、`courses/`、`output/`、`user_data/` 已确认被 Git 忽略，没有将资料、缓存、登录态或客户数据加入版本控制。

本次临时验收浏览器与服务已停止；临时浏览器会话记录已清理。截图、公开验收夹具、PDF 和取消任务缓存保留，便于检查与续验。
