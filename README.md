# CourseLM Automation Pipeline

[![CI](https://github.com/OrdoAbChao7/courselm/actions/workflows/ci.yml/badge.svg)](https://github.com/OrdoAbChao7/courselm/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

个人课程资料自动化处理系统：把大学课程资料放进 `courses/<课程名>/`，一条命令完成
上传 NotebookLM → 执行固定 Prompt → 生成结构化 Obsidian 复习文档。

```
courselm generate 电磁场
```

## 特性

- **一键流水线**：扫描 → 上传 → 两阶段提问 → 生成 → 同步 Vault，全自动
- **两阶段 Prompt 编排**：先生成知识结构 / 题型总结 / 公式总结，再从题型清单动态派生每个题型的详解文档
- **断点续跑**：Prompt 回答实时缓存，中断或部分失败后重跑同一命令，自动跳过已成功部分（省每日 chats 配额）
- **增量上传**：只上传上次未传过的新资料，Notebook 按 `CourseLM-<课程名>` 复用
- **Obsidian 友好输出**：Front Matter 元数据（course / type / tags / type_name，可被 Dataview 查询）、LaTeX 公式定界符归一（`\(..\)` → `$..$`）、代码块保护
- **配置驱动**：Prompt 模板、路径、超时、题型数量上限全部在 YAML 中调整，无需改代码
- **图形启动器（Windows）**：PyInstaller 打包双击即用，实时日志窗口
- **可测试**：122 项单元/集成测试全部零网络，CI（Windows × Python 3.11/3.12）双版本把关

## 产出示例

写入 Obsidian Vault（`课程/<课程名>/`）：

```
课程/电磁场/
├── 知识结构.md            # 整本书的知识结构（章节/依赖/学习路线）
├── 公式总结.md            # 全书公式清单（适用条件/易混对比/记忆建议）
└── 题型/
    ├── 题型总结.md        # 常考题型清单 + 每类高频解法
    └── <题型名>.md       # 每类题型一个文件：例题/解法/易错点/题型间联系
```

题型文件数量由资料内容动态决定（上限默认 12，可在配置中调整）。

## 工作流程

```
扫描 courses/<课程名>/
  → 创建/复用 NotebookLM Notebook，增量上传全部资料
  → 阶段一（固定 Prompt）：知识结构 + 题型总结 + 公式总结
  → 解析题型总结得到题型清单
  → 阶段二（动态 Prompt）：每个题型生成详解文件
  → 转换为 Obsidian Markdown（Front Matter / LaTeX / [[内链]]）
  → 写入 Vault
```

## 环境要求

- Windows（图形启动器与代理自动检测面向 Windows；核心流水线为纯 Python，跨平台可用）
- Python 3.11+
- 网络环境需可访问 Google（Windows 下自动检测系统代理，或在 `config.yaml` 显式指定）
- 首次使用需一次浏览器登录（自动下载 Chromium，约 170 MB）
- [Obsidian](https://obsidian.md/)（可选，用于阅读生成的文档）

## 快速开始

```powershell
git clone https://github.com/OrdoAbChao7/courselm.git
cd courselm
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

1. 把课程资料放进 `courses\<课程名>\`（支持 PDF / PPT / DOCX / 图片）
2. 编辑 `config\config.yaml`，填写 `obsidian.vault_path` 为你的 Obsidian Vault 根目录
3. 登录 NotebookLM（打开浏览器登录 Google 账号，登录态自动持久化）：

```powershell
.venv\Scripts\courselm login
```

4. 生成复习文档：

```powershell
.venv\Scripts\courselm generate 电磁场
```

## 使用

### 命令行

```powershell
.venv\Scripts\courselm scan 电磁场              # 只扫描课程目录，列出识别到的资料
.venv\Scripts\courselm generate 电磁场          # 完整流水线（两阶段）
.venv\Scripts\courselm generate 电磁场 --fresh  # 强制新建 Notebook、忽略缓存重跑
.venv\Scripts\courselm generate 电磁场 --prompts question_type_summary  # 只跑指定 Prompt（调试）
```

退出码：`0` 全部成功；`1` 配置/参数错误；`2` 运行时失败或部分 Prompt 失败
（重跑同一命令自动续跑，只补失败部分）。

### 图形启动器（Windows）

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_launcher.ps1
```

构建完成后双击 `dist\CourseLM.exe`：下拉选择课程 → 登录 / 生成，窗口实时显示日志。

启动器只是现有 CLI 的壳，不复制流水线逻辑——登录态、配置与缓存全部沿用项目目录。
因此 `CourseLM.exe` 必须位于项目根目录或其 `dist` 子目录中，不能脱离项目单独分发。

## 常见问题

**登录态失效（提示重跑 login）**
Google 会话可能数周过期一次，属逆向方案的固有不稳定性。重新执行
`.venv\Scripts\courselm login` 即可，已有 Notebook 与 raw 缓存不受影响。

**上传卡在索引阶段**
大 PDF（几百页教材）索引可能超过默认等待时长（300 秒）。可在
`config.yaml` 的 `notebooklm.upload_wait_timeout` 调大，重跑同一命令会续传。

**需要代理访问**
Windows 下 `network.proxy: auto` 自动读取系统代理；也可显式指定
（如 `http://127.0.0.1:7897`）或 `none` 直连。

**想强制全量重跑**
删除 `output\<课程名>\` 目录（raw 缓存 + 上传记录）后重跑。

## 配置

| 文件 | 内容 |
|------|------|
| `config/config.yaml` | 路径、Obsidian Vault 位置、超时、重试、题型数量上限、资料扩展名（**使用前必须填写 `obsidian.vault_path`**） |
| `config/prompts.yaml` | 全部 Prompt 模板，可自行修改措辞而不动代码 |

## 项目结构

```
courselm/
├── main.py                 # CLI 入口（login / scan / generate）
├── launcher.py             # Windows 图形启动器（tkinter）
├── config/                 # 配置与 Prompt 模板
│   ├── config.yaml
│   └── prompts.yaml
├── modules/                # 功能模块
│   ├── file_manager.py     # 课程资料扫描
│   ├── notebooklm.py       # NotebookLM 适配层（异常翻译/上传续传）
│   ├── prompts.py          # Prompt 配置加载与渲染
│   ├── prompt_runner.py    # 两阶段 Prompt 编排（题型解析/断点缓存/重试）
│   ├── markdown_generator.py  # Obsidian Markdown 生成（清洗/Front Matter）
│   ├── obsidian_sync.py    # Vault 同步
│   ├── network.py          # 系统代理适配
│   └── config.py           # 配置加载与校验（pydantic）
├── tests/                  # 单元测试（pytest，全部零网络）
├── scripts/                # 启动器构建 / NotebookLM 冒烟验证
├── courses/                # 课程资料（输入）
├── output/                 # 中间产物与缓存（raw 回答 + 生成的 md）
├── logs/                   # 运行日志（按日滚动）
└── docs/                   # 设计文档
```

## 技术说明

NotebookLM 无官方 API。本项目采用 [notebooklm-py](https://github.com/teng-lin/notebooklm-py)
（MIT 协议的逆向 RPC 客户端）作为交互层：Playwright 仅用于首次登录采集 Cookie，
之后全部操作走其内部接口，比浏览器 UI 自动化稳定得多。该库为非官方实现，
接口可能随 Google 更新而变动，届时升级依赖版本即可。

## 测试

```powershell
.venv\Scripts\python -m pytest tests/ -q
```

全部测试零网络、零真实账号（NotebookLM 适配层用 FakeClient 注入）。
NotebookLM 真实环境的冒烟验证脚本见 `scripts/verify_notebooklm.py`，
验证方式见 `docs/design.md` §6。

## License

[MIT](LICENSE)
