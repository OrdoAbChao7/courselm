"""CourseLM Windows 图形启动器。

启动器不复制流水线逻辑，而是调用项目 .venv 中的 Python 运行现有 CLI，
这样 NotebookLM 登录态、配置文件和缓存都继续使用当前项目的数据。
"""

from __future__ import annotations

import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText


class LauncherError(RuntimeError):
    """启动器无法定位项目或运行时。"""


def find_project_root(start: Path) -> Path:
    """从脚本/可执行文件所在位置向上查找项目根目录。"""
    location = start.resolve()
    if location.is_file():
        location = location.parent

    for candidate in (location, *location.parents):
        if (candidate / "main.py").is_file() and (candidate / "pyproject.toml").is_file():
            return candidate
        if (candidate / "config").is_dir() and (candidate / "CourseLM.exe").is_file():
            return candidate
    raise LauncherError("找不到项目根目录，请将 CourseLM.exe 放在项目目录或 dist 目录中。")


def discover_courses(project_root: Path) -> list[str]:
    """返回 courses 目录下的课程目录名。"""
    courses_dir = project_root / "courses"
    if not courses_dir.is_dir():
        return []
    return sorted(
        path.name
        for path in courses_dir.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )


def _python_executable(project_root: Path) -> Path:
    python = project_root / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise LauncherError(f"找不到项目虚拟环境：{python}")
    return python


def build_command(project_root: Path, action: str, course: str | None = None) -> list[str]:
    """构造交给现有 main.py 的命令。"""
    if action not in {"login", "generate"}:
        raise LauncherError(f"不支持的操作：{action}")
    if action == "generate" and not course:
        raise LauncherError("生成文档前请选择课程。")

    command = [str(_python_executable(project_root)), "main.py", action]
    if course:
        command.append(course)
    return command


class CourseLMApp:
    """Tkinter 界面及子进程生命周期管理。"""

    def __init__(self, root: tk.Tk, project_root: Path) -> None:
        self.root = root
        self.project_root = project_root
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None

        root.title("CourseLM 课程复习文档生成器")
        root.geometry("760x520")
        root.minsize(620, 420)
        root.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(root, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="课程").pack(anchor=tk.W)

        self.course_var = tk.StringVar()
        self.course_box = ttk.Combobox(
            frame,
            textvariable=self.course_var,
            state="readonly",
        )
        self.course_box.pack(fill=tk.X, pady=(4, 12))

        actions = ttk.Frame(frame)
        actions.pack(fill=tk.X)
        self.login_button = ttk.Button(actions, text="登录 NotebookLM", command=self.login)
        self.login_button.pack(side=tk.LEFT)
        self.generate_button = ttk.Button(actions, text="生成复习文档", command=self.generate)
        self.generate_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="刷新课程", command=self.refresh_courses).pack(side=tk.LEFT, padx=(8, 0))

        self.status_var = tk.StringVar(value=f"项目目录：{project_root}")
        ttk.Label(frame, textvariable=self.status_var).pack(anchor=tk.W, pady=(12, 4))
        self.output = ScrolledText(frame, height=20, state=tk.DISABLED, wrap=tk.WORD)
        self.output.pack(fill=tk.BOTH, expand=True)
        self.root.after(100, self._drain_messages)

        # Initialize courses and component states
        self.refresh_courses()

    def refresh_courses(self) -> None:
        courses = discover_courses(self.project_root)
        if courses:
            self.course_box.configure(state="readonly")
            self.course_box["values"] = courses
            if self.course_var.get() not in courses:
                self.course_box.current(0)
            if self.process is None:
                self.generate_button.state(["!disabled"])
        else:
            self.course_box.configure(state="disabled")
            self.course_box["values"] = []
            self.course_var.set("(未发现课程，请在 courses 目录中添加)")
            self.generate_button.state(["disabled"])
        self._append(f"已发现 {len(courses)} 个课程目录。\n")

    def login(self) -> None:
        self._run("login")

    def generate(self) -> None:
        course = self.course_var.get().strip()
        if not course:
            messagebox.showwarning("请选择课程", "请先选择一个课程目录。")
            return
        self._run("generate", course)

    def _run(self, action: str, course: str | None = None) -> None:
        if self.process is not None:
            messagebox.showinfo("任务运行中", "当前已有任务正在运行，请等待它完成。")
            return
        if getattr(sys, "frozen", False):
            self._set_running(action, course)
            threading.Thread(
                target=self._run_in_process,
                args=(action, course),
                daemon=True,
            ).start()
            return

        try:
            command = build_command(self.project_root, action, course)
            self.process = subprocess.Popen(
                command,
                cwd=self.project_root,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, LauncherError) as exc:
            self.process = None
            messagebox.showerror("启动失败", str(exc))
            return

        self._set_running(action, course)
        self._append(f">>> {' '.join(command)}\n")
        threading.Thread(target=self._read_output, daemon=True).start()

    def _set_running(self, action: str, course: str | None) -> None:
        self.login_button.state(["disabled"])
        self.generate_button.state(["disabled"])
        self.status_var.set(f"正在执行：{action}{f' {course}' if course else ''}")

    def _run_in_process(self, action: str, course: str | None) -> None:
        """Portable 模式直接运行打包进 EXE 的主程序。"""
        from contextlib import redirect_stderr, redirect_stdout

        class QueueWriter:
            def write(writer_self, value: str) -> int:
                self.messages.put(("output", value))
                return len(value)

            def flush(writer_self) -> None:
                return None

        argv = [action] + ([course] if course else [])
        writer = QueueWriter()
        try:
            import main as application

            with redirect_stdout(writer), redirect_stderr(writer):
                code = application.main(argv)
        except Exception:
            self.messages.put(("output", traceback.format_exc()))
            code = 2
        self.messages.put(("done", str(code)))

    def _read_output(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        for line in self.process.stdout:
            self.messages.put(("output", line))
        self.messages.put(("done", str(self.process.wait())))

    def _drain_messages(self) -> None:
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == "output":
                    self._append(value)
                else:
                    self.process = None
                    self.login_button.state(["!disabled"])
                    self.generate_button.state(["!disabled"])
                    code = int(value)
                    self.status_var.set("任务完成" if code == 0 else f"任务结束，退出码：{code}")
                    self._append(f"\n<<< 任务结束，退出码：{code}\n")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_messages)

    def _append(self, text: str) -> None:
        self.output.configure(state=tk.NORMAL)
        self.output.insert(tk.END, text)
        self.output.see(tk.END)
        self.output.configure(state=tk.DISABLED)

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            if not messagebox.askyesno("退出", "任务仍在运行，确定要退出吗？"):
                return
            self.process.terminate()
        self.root.destroy()


def main() -> None:
    executable_location = Path(sys.executable if getattr(sys, "frozen", False) else __file__)
    project_root = find_project_root(executable_location)
    root = tk.Tk()
    CourseLMApp(root, project_root)
    root.mainloop()


if __name__ == "__main__":
    main()
