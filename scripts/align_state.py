import asyncio
import json
import os
import sys
from pathlib import Path
from modules.path_manager import build_runtime_env
from modules.config import load_config
from modules.network import setup_proxy
from modules.notebooklm import NotebookLMService
from modules.file_manager import scan_course

sys.stdout.reconfigure(encoding="utf-8")
os.environ.update(build_runtime_env())
cfg = load_config()
setup_proxy(cfg.network.proxy)

async def align_state(course_name: str):
    manifest = scan_course(cfg.paths.courses_dir, course_name, cfg.file_types)
    out_dir = cfg.paths.output_dir / course_name
    out_dir.mkdir(parents=True, exist_ok=True)
    state_file = out_dir / "state.json"
    
    async with NotebookLMService() as svc:
        nb_id = await svc.find_notebook_id(course_name)
        if not nb_id:
            print(f"Notebook {course_name} not found!")
            return
        sources = await svc.client.sources.list(nb_id)
        source_titles = {s.title.strip() for s in sources}
        print(f"Course {course_name}: found {len(source_titles)} sources in notebook {nb_id}")
        
        uploaded_rels = []
        for f in manifest.files:
            rel = f.path.relative_to(manifest.root).as_posix()
            if f.path.name.strip() in source_titles:
                uploaded_rels.append(rel)
        
        print(f"Matched {len(uploaded_rels)} / {len(manifest.files)} local files already uploaded.")
        pending = [f.path.relative_to(manifest.root).as_posix() for f in manifest.files if f.path.relative_to(manifest.root).as_posix() not in uploaded_rels]
        print(f"Pending to upload: {len(pending)}")
        for p in pending[:5]:
            print(f" - {p}")
        
        state_data = {
            "generation_schema_version": 3,
            "notebook_id": nb_id,
            "uploaded_files": sorted(uploaded_rels)
        }
        state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {state_file}")

if __name__ == "__main__":
    course = sys.argv[1] if len(sys.argv) > 1 else "高等代数"
    asyncio.run(align_state(course))
