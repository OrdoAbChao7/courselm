# CourseLM Studio：本地讲义生产与编辑工作台

在现有 CourseLM CLI 和生成引擎上增量开发，沿用 Python 标准库 HTTP 服务和原生 HTML/CSS/JavaScript。无数据库，无新增服务端运行依赖。

## 启动

```powershell
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python main.py login
.venv\Scripts\python -m studio.server
```

或双击仓库根目录的 `启动CourseLM工作台.bat`，优先使用项目 `.venv`。浏览器访问 http://127.0.0.1:8765。更换端口：`python -m studio.server --port 8766 --no-browser`。仅监听 `127.0.0.1`；Windows 使用独占端口，避免重复启动。

PDF 需要 PATH 中的 XeLaTeX（TeX Live 或 MiKTeX）。首次使用 MiKTeX 应先完成本机初始化、宏包与字体安装。NotebookLM 使用原项目 `user_data/` 登录态及 `config/config.yaml` 的代理设置。

## 使用流程

1. 输入课程名，通过 Windows 文件夹选择器或手动路径选择资料，点击扫描，核对文件名、类型与大小。
2. 选择考前冲刺、完整精讲或题型突破；选择四种风格、讲义标题后缀、副标题及主题色，再开始生成。
3. 在进度区查看实际阶段、章节数量、事件与工作进程日志。生成失败可继续，成功章节和已保存编辑保留；取消会停止该任务的进程树。
4. 点击历史任务，再点击「打开章节编辑器」。左侧选择章节或绪论、附录，中间编辑 Markdown，右侧查看浏览器内容预览。
5. 点击「保存」或 Ctrl+S。原生文本编辑支持 Ctrl+Z；历史版本可恢复。未保存时切换章节、任务或离开页面会提示。保存冲突时先复制当前草稿，再重新加载，避免覆盖外部修改。
6. 点击「保存并重新编译 PDF」。此操作只读取当前章节 Markdown，重新组装、排版与编译，不访问 NotebookLM，也不重新生成章节。
7. 选择「最终 PDF」查看最新成品。逐文件标记待审核、已审核或需要修改，核查公式、例题答案、事实来源和版权。全部审核通过且当前 PDF 编译成功后，才能确认整份讲义可交付。
8. 从制作工作台进度区下载 Markdown、LaTeX、PDF，编辑区也可下载 PDF。

修改并保存后，旧的 PDF 和审核状态会失效，需重新编译。编译失败保留章节 Markdown、已组装 Markdown 与 TeX，显示错误日志，修改后可再编译。浏览器预览与最终 XeLaTeX 排版不是像素级一致。

## 模式、风格与边界

- 模式为每个任务复制独立 PromptBook，真实影响绪论和章节提示词，不修改全局 `config/prompts.yaml`。保留现有章节结构校验要求。
- 四种风格写入任务独立 `handout.yaml`，映射到真实渲染器的 `layout` 和颜色。学术经典与现代版式支持不同提示框样式；暖色书卷采用现代版式及暖色，黑白极简使用灰度配色。没有字体或版芯自定义控件。
- 当前 v3 引擎不单独向 AI 请求附录：题型索引从实际例题提取。人工编辑后的附录会保留；重编译不自动重写它，修改例题后应人工核对索引。
- 失败续跑会复用成功的有效原始缓存，只补失败部分，并保留已有 Markdown 编辑；不提供对任意成功章节强制重新生成的按钮。
- 内容编辑采用明确保存，不自动保存。切换章节会重置浏览器撤销栈，但磁盘历史备份可恢复。历史备份目前不自动清理。
- 单个 Markdown 最大 2 MB；每次资料扫描最多 200 文件 / 400 MB。当前调度一次执行一个任务；运行中的任务禁止编辑、审核和再次构建。
- 历史列表最近 20 个任务，页面展示其中最近 8 个。任务文件保留在本地。

## 数据流与文件位置

```text
原始资料（只读）
  → courses/<课程名>-<完整任务ID>/   复制资料 + handout.yaml
  → NotebookLM → run_pipeline() → output/<课程ID>/raw/v3/
  → generate_all() → output/<课程ID>/md/    ← 编辑器唯一编辑源
  → build_handout() → handout/manuscript.md
  → write_latex_document() → handout/main.tex
  → compile_latex() → release/讲义成品.pdf
```

`studio_data/jobs/<ID>/` 保存 `request.json`、`status.json`、`events.jsonl`、`worker.log`、`editor.json` 与 `versions/<文件路径哈希>/<版本ID>.md`。每个任务使用完整随机任务 ID，避免同名课程覆盖。Studio 固定使用仓库内 `courses/` 与 `output/`，CLI 仍遵循原配置路径。

`Workspace` 对章节、版本与下载路径进行任务范围校验，拒绝路径跳转、符号链接及 Windows junction。保存使用同目录临时文件、fsync 和原子替换，并以内容 SHA-256 检测版本冲突。构建记录全部章节与风格的指纹；下载接口再次核对，阻止导出过期产物。审核绑定具体内容版本，人工确认与模型生成、PDF 编译分开记录。

`run_pipeline()` 增加可选阶段回调，默认不影响 CLI。文件观察只统计真实产物，没有按时间递增的假进度或剩余时间预测。

## 安全与隐私

- 本机 Host / Origin 校验、同源 CSP；Markdown 经 DOMPurify 净化后渲染，KaTeX 禁用可信命令，禁用预览图片及 HTML 表单。恶意 HTML 不会直接执行。
- 前端 Marked 15.0.12、DOMPurify 3.2.7、KaTeX 0.16.22 及字体随仓库本地分发，许可证位于 `studio/static/vendor/`；运行时无需 CDN。用途分别为 Markdown、HTML 净化及数学排版。
- Studio 拒绝原始 TeX 文件访问与程序控制指令，仅允许常见数学环境。编译关闭 shell escape，设置保守文件访问策略并限制单次编译 180 秒。高级自定义宏可能被拒绝并显示源文件位置。这仍是本地个人工具，不是可对不可信用户开放的 TeX 沙箱。
- 原资料不会被删除或改写。课程资料、登录态、缓存及生成产物均由 `.gitignore` 排除，不应上传 GitHub。生成时资料会按原流程上传 NotebookLM；本地编辑和重编译不上传内容。
- 不要通过端口转发或反向代理公开工作台。服务不提供多用户身份认证，不支持多个实例同时修改同一任务。

## 验证

无网络测试：

```powershell
.venv\Scripts\python -m pytest tests studio/tests -q
node --check studio/static/app.js
node --check studio/static/editor.js
```

创建明确标注的离线验收任务（会实际调用 XeLaTeX，不访问 NotebookLM）：

```powershell
.venv\Scripts\python scripts/studio_acceptance.py
```

任务编号同时写入 `output/studio-acceptance/report.json`。若本机没有 XeLaTeX，样例会保留为草稿并报告原因。

可选浏览器验收需要 Playwright、Chromium 与 pypdf（仅测试用，原项目已通过 NotebookLM browser extra 提供 Playwright）：

```powershell
.venv\Scripts\python -m pip install pypdf
.venv\Scripts\python -m playwright install chromium
$env:COURSELM_BROWSER_URL='http://127.0.0.1:8765'
$env:COURSELM_TEST_JOB='<离线样例任务ID>'
.venv\Scripts\python -m pytest studio/tests/test_browser.py -q
```

该测试在浏览器修改章节，检查公式/表格、XSS、防止切章异步覆盖、安全保存、真实重编译、PDF 文本包含修改、三类下载和人工交付。截图输出 `output/playwright/studio-editor.png`。不要选择真实客户任务作为该测试的输入。运行前等待其他任务结束。

实际本机验收结果、已知未验证项见 `docs/studio-acceptance.md`。

## 原图自动准入

构建默认使用题目绑定，不再按“电路、波形”等关键词或相似度自动选图。扫描结果只是候选；旧版 `confirmed` 也不能授权插图。没有绑定的图片会自动省略，保留“配图待补”提示；完整原因记录在当前任务的 `handout/figure-report.json`，不会改写源 Markdown。

需要保留一张原图时，在章节编辑器把光标放到顶层“标准例题/练习”的题干内，选择原图并点击“绑定到当前题目”。PDF 必须先从原页框选包含全部参数、标号与连线的完整区域。这个操作会保存题干与原图的绑定；后续重编译自动复用，不需要重复审核每张图。表格、公式、代码或列表内部不能作为插图位置。

题干参数、来源文件、图像或图注改变后，旧绑定自动失效。仍然依赖缺失原图的题目只能导出带标记草稿，补齐或改写完整条件后才能交付。该机制不声称能自动理解任意扫描图；无法确定时会少图，不会猜图。

原图功能依赖可用以下命令安装；本轮已安装到项目 `.venv`：

```powershell
uv pip install --python .venv/Scripts/python.exe -e ".[figures,dev]"
```

实现范围和验证记录见 [原图实施记录](docs/figure-integrity-implementation.md)。
