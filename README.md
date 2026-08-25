# CourseLM Automation Pipeline

个人课程资料自动化处理系统：把大学课程资料放进 `courses/<课程名>/`，一条命令完成
上传 NotebookLM → 执行固定 Prompt → 生成结构化 Obsidian 复习文档。

```
courselm generate 电磁场
```

产出（写入 Obsidian Vault）：

```
<Vault>/课程/电磁场/
├── 知识结构.md            # 整本书的知识结构（章节/依赖/学习路线）
├── 公式总结.md            # 全书公式清单（适用条件/易混对比/记忆建议）
└── 题型/
    ├── 题型总结.md        # 常考题型清单 + 每类高频解法
    └── <题型名>.md       # 每类题型一个文件：例题/解法/易错点/题型间联系
```

## 工作流程

```
扫描 courses/<课程名>/
  → 创建/复用 NotebookLM Notebook，上传全部资料
  → 阶段一（固定 Prompt）：知识结构 + 题型总结 + 公式总结
  → 解析题型总结得到题型清单
  → 阶段二（动态 Prompt）：每个题型生成详解文件
  → 转换为 Obsidian Markdown（Front Matter / LaTeX / [[内链]]）
  → 写入 Vault
```

## 安装

要求：Python 3.11+（在 [python.org](https://www.python.org/downloads/) 安装，勾选 Add to PATH）。

```powershell
cd e:\Projects\note-agent
python -m venv .venv
.venv\Scripts\pip install -e .
```

首次使用前登录 NotebookLM（打开浏览器，登录 Google 账号，登录态自动持久化，之后无需重复登录）：

```powershell
.venv\Scripts\courselm login
```

> 首次 login 会自动下载 Chromium（约 170 MB，无进度条，需等待）。

## 使用

```powershell
.venv\Scripts\courselm scan 电磁场              # 只扫描课程目录，列出识别到的资料
.venv\Scripts\courselm generate 电磁场          # 完整流水线（两阶段）
.venv\Scripts\courselm generate 电磁场 --fresh  # 强制新建 Notebook、忽略缓存重跑
.venv\Scripts\courselm generate 电磁场 --prompts question_type_summary  # 只跑指定 Prompt（调试）
```

说明：

- 重复 `generate` 同一课程会复用已有 Notebook，已成功的 Prompt 读缓存跳过（节省每日 chats 配额）
- 中间产物保存在 `output/<课程名>/`（raw 回答缓存 + 生成的 md），删除该目录即可强制全量重跑
- 日志按日滚动保存在 `logs/`

## 配置

- `config/config.yaml`：路径、Obsidian Vault 位置、超时、重试、题型数量上限、资料扩展名
  （**使用前必须填写 `obsidian.vault_path`**）
- `config/prompts.yaml`：全部 Prompt 模板，可自行修改措辞而不动代码

## 项目结构

```
note-agent/
├── main.py                 # CLI 入口
├── config/                 # 配置与 Prompt 模板
├── modules/                # 功能模块
│   ├── file_manager.py     # 课程资料扫描
│   ├── notebooklm.py       # NotebookLM 适配层
│   ├── prompt_runner.py    # 两阶段 Prompt 编排
│   ├── markdown_generator.py  # Obsidian Markdown 生成
│   └── obsidian_sync.py    # Vault 同步
├── courses/                # 课程资料（输入）
├── output/                 # 中间产物与缓存
├── logs/                   # 运行日志
└── docs/                   # 设计文档
```

## 技术说明

NotebookLM 无官方 API。本项目采用 [notebooklm-py](https://github.com/teng-lin/notebooklm-py)
（MIT 协议的逆向 RPC 客户端）作为交互层：Playwright 仅用于首次登录采集 Cookie，
之后全部操作走其内部接口，比浏览器 UI 自动化稳定得多。该库为非官方实现，
接口可能随 Google 更新而变动，届时升级依赖版本即可。

## 测试

- 单元测试（纯本地模块）：`pytest tests/`
- NotebookLM 适配层需真实账号，验证方式见 `docs/design.md` §6
