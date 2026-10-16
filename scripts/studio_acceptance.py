"""Create a clearly labelled offline acceptance task with real XeLaTeX output.

Run from repository root: python scripts/studio_acceptance.py
This does not access NotebookLM or copy any personal course material.
"""
from pathlib import Path
import json
import sys
import uuid
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio.workspace import Workspace, atomic_write, write_json


def create_fixture():
    jobid = uuid.uuid4().hex[:12]
    course = '验收样例-导数入门'
    course_id = course + '-' + jobid
    job = ROOT / 'studio_data/jobs' / jobid
    write_json(job / 'status.json', {'id':jobid, 'course':course, 'course_id':course_id,
        'status':'draft_ready', 'mode':'comprehensive', 'style':'academic', 'stage':'离线测试夹具',
        'percent':0, 'generation_complete':True, 'created_at':datetime.now().isoformat(),
        'artifacts':{}, 'chapters_done':1, 'chapters_total':1})
    write_json(job / 'request.json', {'course':course, 'course_id':course_id, 'fixture':True})
    base = ROOT / 'output' / course_id / 'md'
    atomic_write(base / '00-绪论.md', '# 导读\n\n这是公开的验收样例，不是 NotebookLM 生成结果。用于验证编辑、公式预览、保存、编译和审核流程。\n')
    atomic_write(base / 'chapters/01-导数.md', r'''# 第1章 导数与变化率

## 核心概念

导数描述函数在某点的瞬时变化率。对 $f(x)=x^2$，有：

$$
f'(x)=\lim_{h\to 0}\frac{(x+h)^2-x^2}{h}=2x
$$

| 函数 | 导数 | 适用条件 |
| --- | --- | --- |
| $x^2$ | $2x$ | 实数范围 |
| $x^3$ | $3x^2$ | 实数范围 |

## 题型一：计算指定点的导数

### 标准例题：计算变化率

已知 $f(x)=x^2$，求 $f'(3)$。[必要补充]

### 跟着做

1. 使用幂函数求导法则，得到 $f'(x)=2x$。
2. 将 $x=3$ 代入，得到 $f'(3)=6$。

> [!TIP] 核查提示
> 先求导再代入，注意函数值与导数的区别。

### 自己试

计算 $g(x)=x^3$ 在 $x=2$ 处的导数。

#### 解答

$g'(x)=3x^2$，所以 $g'(2)=12$。
''')
    w = Workspace(ROOT, jobid)
    result = w.build()
    report = {'job_id':jobid, 'course_id':course_id, 'status':result['status'],
              'pdf_current':result.get('pdf_current'), 'url':'http://127.0.0.1:8765'}
    write_json(ROOT / 'output/studio-acceptance/report.json', report)
    print(json.dumps(report, ensure_ascii=False))
    return w


if __name__ == '__main__':
    create_fixture()
