"""Graphical entry point. Backend processes are owned by this launcher window."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Event, Thread
import time
import webbrowser

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.desktop_runtime import (
    APP_VERSION, resource_root, restore_space, running_space, serve_space, start_space,
    stop_process, user_data_root, workspace_directory,
)


def launcher(*, check_only: bool = False) -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    if check_only:
        root.withdraw()
    root.title('泊序 · 项目物流协同')
    root.geometry('760x590')
    root.minsize(720, 570)
    root.configure(bg='#f4f5f3')
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('TFrame', background='#f4f5f3')
    style.configure('TLabel', background='#f4f5f3', font=('Microsoft YaHei UI', 10), foreground='#34403c')
    style.configure('Title.TLabel', font=('Microsoft YaHei UI', 25, 'bold'), foreground='#153e32')
    style.configure('Heading.TLabel', font=('Microsoft YaHei UI', 13, 'bold'))
    style.configure('TButton', font=('Microsoft YaHei UI', 10), padding=(15, 10))
    style.configure('Primary.TButton', background='#174e3e', foreground='white')
    style.map('Primary.TButton', background=[('active', '#236c54'), ('disabled', '#89968f')])
    frame = ttk.Frame(root, padding=30)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='泊序', style='Title.TLabel').pack(anchor='w')
    ttk.Label(frame, text=f'项目物流协同  /  v{APP_VERSION} 本地使用版').pack(anchor='w', pady=(3, 22))
    processes = {}
    workers = []
    events = Queue()
    buttons = {}
    closing = Event()
    restoring = [False]
    status_text = tk.StringVar(value='选择一个空间，应用将在默认浏览器打开。')
    address_text = tk.StringVar(value='')
    current_url = ['']

    def start(mode):
        for button in buttons.values():
            button.configure(state='disabled')
        restore_button.configure(state='disabled')
        status_text.set('正在准备演示资料…' if mode == 'demo' else '正在打开你的工作空间…')

        def worker():
            try:
                data = workspace_directory(mode)
                running = running_space(data, mode)
                if not running:
                    process = start_space(mode)
                    processes[mode] = process
                    for _ in range(160):
                        if closing.is_set():
                            stop_process(process)
                            return
                        if process.poll() is not None:
                            raise RuntimeError('启动失败。请查看资料目录中的 logs，或重新下载使用包。')
                        running = running_space(data, mode)
                        if running:
                            break
                        time.sleep(0.35)
                if not running:
                    raise RuntimeError('启动时间较长，请稍后重试。资料保留在本机。')
                if not closing.is_set():
                    webbrowser.open(running.url)
                    events.put(('ready', running.url))
            except Exception as error:
                events.put(('error', str(error)))
        thread = Thread(target=worker, daemon=True)
        workers.append(thread)
        thread.start()

    for mode, heading, description, label in (
        ('demo', '先体验完整流程', '含六种阶段的合成订单，可切换负责人、员工和货代身份。', '打开演示'),
        ('work', '建立自己的工作空间', '首次设置负责人账号；项目、订单和附件保存在你的电脑。', '打开我的空间'),
    ):
        row = ttk.Frame(frame, padding=(0, 12))
        row.pack(fill='x')
        text = ttk.Frame(row)
        text.pack(side='left', fill='x', expand=True)
        ttk.Label(text, text=heading, style='Heading.TLabel').pack(anchor='w')
        ttk.Label(text, text=description, wraplength=430).pack(anchor='w', pady=(6, 0))
        button = ttk.Button(row, text=label, style='Primary.TButton' if mode == 'demo' else 'TButton',
                            command=lambda selected=mode: start(selected))
        button.pack(side='right', padx=(10, 0))
        buttons[mode] = button
    ttk.Separator(frame).pack(fill='x', pady=(12, 14))
    ttk.Label(frame, textvariable=status_text, wraplength=650).pack(anchor='w')
    ttk.Label(frame, textvariable=address_text, foreground='#1d674e').pack(anchor='w', pady=(3, 12))
    actions = ttk.Frame(frame)
    actions.pack(fill='x')

    def open_data():
        data = user_data_root()
        data.mkdir(parents=True, exist_ok=True)
        os.startfile(str(data))

    ttk.Button(actions, text='使用说明', command=lambda: webbrowser.open((resource_root() / 'docs/QUICK-START.html').as_uri())).pack(side='left')
    ttk.Button(actions, text='打开资料目录', command=open_data).pack(side='left', padx=8)
    ttk.Button(actions, text='再次打开页面', command=lambda: webbrowser.open(current_url[0]) if current_url[0] else None).pack(side='right')

    def restore():
        data = workspace_directory('work')
        if running_space(data, 'work'):
            messagebox.showinfo('请先停止工作空间', '请关闭泊序启动窗口后重新打开，先恢复备份，再打开工作空间。已有资料不会被覆盖。', parent=root)
            return
        archive = filedialog.askopenfilename(parent=root, title='选择完整备份', filetypes=[('泊序完整备份', '*.json.gz')])
        if not archive:
            return
        if not messagebox.askokcancel('恢复到空白工作空间', '恢复会导入备份中的业务资料、账号和附件；已有资料的空间会拒绝恢复。继续前请确认备份来自你信任的来源。', parent=root):
            return
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command.append(str(resource_root() / 'scripts/desktop_app.py'))
        command.extend(['--restore-file', archive])
        for button in buttons.values():
            button.configure(state='disabled')
        restore_button.configure(state='disabled')
        restoring[0] = True
        status_text.set('正在核对并恢复备份…')

        def worker():
            try:
                result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=120,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if result.returncode:
                    reason = data / 'startup-error.log'
                    raise RuntimeError(reason.read_text('utf-8')[-600:] if reason.is_file() else '恢复失败，请核对备份和目标空间。')
                events.put(('restored', '已恢复。打开“我的空间”，使用备份中的账号密码登录。'))
            except Exception as error:
                events.put(('error', str(error)))
        thread = Thread(target=worker, daemon=True)
        workers.append(thread)
        thread.start()

    restore_button = ttk.Button(frame, text='从完整备份恢复（仅空白工作空间）', command=restore)
    restore_button.pack(anchor='w', pady=(10, 0))
    ttk.Label(frame, text='使用期间请保留这个窗口。退出时会停止由本窗口启动的服务。\n各电脑的数据彼此独立；当前版本仅支持本机使用。',
              wraplength=650, foreground='#67726c').pack(anchor='w', pady=(16, 0))

    def poll():
        try:
            while True:
                kind, value = events.get_nowait()
                restoring[0] = False
                for button in buttons.values():
                    button.configure(state='normal')
                restore_button.configure(state='normal')
                if kind == 'ready':
                    current_url[0] = value
                    address_text.set(value)
                    status_text.set('已打开。浏览器未出现时，可点击“再次打开页面”。')
                elif kind == 'restored':
                    status_text.set(value)
                    messagebox.showinfo('恢复完成', value, parent=root)
                else:
                    status_text.set(value)
                    messagebox.showerror('暂时无法打开', value, parent=root)
        except Empty:
            pass
        if not closing.is_set():
            root.after(200, poll)

    def close():
        if restoring[0]:
            messagebox.showinfo('正在恢复', '请等本次恢复结束后再退出。', parent=root)
            return
        closing.set()
        for worker in workers:
            worker.join(timeout=2)
        for process in list(processes.values()):
            try:
                stop_process(process)
            except (OSError, subprocess.TimeoutExpired):
                pass
        root.destroy()

    root.protocol('WM_DELETE_WINDOW', close)
    if check_only:
        root.update_idletasks()
        root.destroy()
        return
    root.after(200, poll)
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description='泊序 Windows 本地使用版')
    parser.add_argument('--server', action='store_true', help='直接启动空间（交付检查使用）')
    parser.add_argument('--mode', choices=['demo', 'work'], default='demo')
    parser.add_argument('--port', type=int)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--launcher-check', action='store_true', help='检查图形启动入口后退出')
    parser.add_argument('--restore-file', type=Path, help='验证完整备份后恢复到空白工作空间')
    args = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('此发行包适用于 Windows x64。')
    if args.restore_file:
        restore_space(args.restore_file)
    elif args.server:
        serve_space(args.mode, args.port, open_browser=not args.no_browser)
    else:
        if not (resource_root() / 'docs/QUICK-START.html').is_file():
            raise RuntimeError('使用说明缺失，请重新下载完整使用包。')
        launcher(check_only=args.launcher_check)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if '--server' in sys.argv or '--restore-file' in sys.argv:
            mode = 'demo' if '--mode' in sys.argv and sys.argv[sys.argv.index('--mode') + 1] == 'demo' else 'work'
            data = workspace_directory(mode)
            data.mkdir(parents=True, exist_ok=True)
            message = str(error) if isinstance(error, (ValueError, RuntimeError)) else '启动或恢复失败，请查看 logs 目录。'
            (data / 'startup-error.log').write_text(message, 'utf-8')
        else:
            from tkinter import messagebox
            messagebox.showerror('泊序启动失败', str(error))
        sys.exit(1)
