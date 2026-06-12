import os
import queue
import shutil
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from config import Config
from plain_dict import PlainDict
from utils.file_utils import get_unique_name, merge_dir
from utils.generate_clean_hxnames import generate_clean_hxnames
from utils.krkr_hxv4_hash import get_file_hash, get_path_hash, set_hashlib
from utils.restore_dir_structure import restore_dir_structure

DEFAULT_FILENAMES = [
    "base.stage", "cglist.csv", "soundlist.csv", "charvoice.csv",
    "imagediffmap.csv", "savelist.csv", "scenelist.csv", "replay.ks",
    "_chthum_index.pbd",
]

SOURCE_DEFS = [
    ("scan_psb_and_decompile", "扫描 scn/PSB 剧本目录", "dir", "从脚本补场景、立绘、语音名"),
    ("from_unobfuscated_directory", "从明文目录收集文件名", "dir", "有体验版/旧版/未加密资源时优先选"),
    ("from_base_stage", "读取 base.stage", "file", "补基础资源名"),
    ("from_cglist_csv", "读取 cglist.csv", "file", "补 CG 名"),
    ("from_soundlist_csv", "读取 soundlist.csv", "file", "补音效名"),
    ("add_char_sys_voices", "读取 charvoice.csv", "file", "补角色系统语音"),
    ("from_imagediffmap_csv", "读取 imagediffmap.csv", "file", "补差分图"),
    ("from_bgv_csv", "扫描背景语音目录", "dir", "补 bgv 语音"),
    ("from_savelist_csv", "读取 savelist.csv", "file", "补存档相关名"),
    ("from_scenelist_csv", "读取 scenelist.csv", "file", "补场景列表"),
    ("from_krkrdump_logs", "读取 KrkrDump 日志目录", "dir", "从 dump 日志补命中名"),
    ("from_stand_files", "扫描 fgimage 立绘目录", "dir", "补立绘名"),
    ("from_pbd_files", "扫描 PBD 目录", "dir", "补 PBD 资源名"),
    ("from_chthum_index_pbd", "读取 _chthum_index.pbd", "file", "补人物缩略图"),
    ("add_movies", "读取 replay.ks 影片列表", "file", "补视频名"),
]

class QueueWriter:
    def __init__(self, output_queue):
        self.output_queue = output_queue
    def write(self, text):
        if text:
            self.output_queue.put(text)
    def flush(self):
        pass

def read_hxnames(path):
    path_hash_map, file_hash_map = {}, {}
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            parts = line.rstrip("\n").split(":")
            if len(parts) != 2:
                print(f"跳过格式错误的行: {line.rstrip()}")
                continue
            hx_hash, hx_name = parts
            if len(hx_hash) == 16:
                path_hash_map[hx_name] = hx_hash
            elif len(hx_hash) == 64:
                file_hash_map[hx_name] = hx_hash
            else:
                print(f"跳过未知 hash 长度: {line.rstrip()}")
    return path_hash_map, file_hash_map

def write_hxnames(path, path_hash_map, file_hash_map):
    with path.open("w", encoding="utf-8") as handle:
        for hash_map in (path_hash_map, file_hash_map):
            for name, hx_hash in hash_map.items():
                if name.strip():
                    handle.write(f"{hx_hash}:{name}\n")

def rename_hashed_items(rename_dir, path_hash_map, file_hash_map):
    renamed_file_count = renamed_dir_count = 0
    hash_path_map = {value: key for key, value in path_hash_map.items()}
    hash_file_map = {value: key for key, value in file_hash_map.items()}
    for root, dirs, files in os.walk(rename_dir, topdown=False):
        for filename in files:
            filepath = os.path.join(root, filename)
            if filename not in hash_file_map:
                continue
            new_path = get_unique_name(os.path.join(root, hash_file_map[filename]))
            try:
                os.rename(filepath, new_path)
                renamed_file_count += 1
                print(f"文件重命名成功: {Path(filepath).relative_to(rename_dir)} -> {Path(new_path).relative_to(rename_dir)}")
            except Exception as exc:
                print(f"文件重命名失败: {Path(filepath).relative_to(rename_dir)} -> {Path(new_path).relative_to(rename_dir)}, 原因: {exc}")
        for dirname in dirs:
            dirpath = os.path.join(root, dirname)
            if dirname not in hash_path_map:
                continue
            dest_path = os.path.join(root, hash_path_map[dirname].rstrip("/\\"))
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            try:
                if os.path.exists(dest_path):
                    merge_dir(dirpath, dest_path)
                else:
                    shutil.move(dirpath, dest_path)
                renamed_dir_count += 1
                print(f"目录重命名成功: {Path(dirpath).relative_to(rename_dir)} -> {Path(dest_path).relative_to(rename_dir)}")
            except Exception as exc:
                print(f"目录重命名失败: {Path(dirpath).relative_to(rename_dir)} -> {Path(dest_path).relative_to(rename_dir)}, 原因: {exc}")
    print(f"重命名完成: 文件 {renamed_file_count} 个，目录 {renamed_dir_count} 个。")

class Hxv4Gui:
    def __init__(self, root):
        self.root = root
        self.root.title("HXv4 HxNames 新手向导")
        self.root.geometry("1120x780")
        self.project_dir = Path(__file__).resolve().parent
        self.output_queue = queue.Queue()
        self.running = False
        self.rename_dir = StringVar()
        self.hxnames_path = StringVar(value=str(self.project_dir / "HxNames.lst"))
        self.clean_output_path = StringVar(value=str(self.project_dir / "HxNames-clean.lst"))
        self.restore_dir = StringVar()
        self.clean_dir = StringVar()
        self.do_rename = BooleanVar(value=True)
        self.duplicate_lower = BooleanVar(value=True)
        self.source_vars, self.source_paths = {}, {}
        self._build_ui()
        self.root.after(80, self._poll_output)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)
        guide = ttk.LabelFrame(main, text="推荐流程")
        guide.pack(fill="x")
        ttk.Label(guide, text="1. 选解包后的总目录  ->  2. 勾选你手头有的来源  ->  3. 先试“只生成不重命名”，确认后再自动重命名").pack(anchor="w", padx=8, pady=(6, 2))
        ttk.Label(guide, text="不知道选什么时：优先选 scn/PSB 剧本目录；如果有未加密版/体验版资源，再选明文目录。其他 CSV/PBD 有就补，没有就不勾。", foreground="#4b5563").pack(anchor="w", padx=8, pady=(0, 8))
        top = ttk.LabelFrame(main, text="第 1 步：基础路径")
        top.pack(fill="x", pady=(10, 0))
        self._path_row(top, "要处理的目录", self.rename_dir, "dir", 0, "解包出来、里面有 hash 文件名的总目录")
        self._path_row(top, "HxNames.lst 输出", self.hxnames_path, "save", 1, "默认放在本工具目录")
        ttk.Checkbutton(top, text="生成后自动重命名目录和文件", variable=self.do_rename).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Checkbutton(top, text="同时加入小写文件名/目录名", variable=self.duplicate_lower).grid(row=3, column=1, sticky="w", pady=4)
        top.columnconfigure(1, weight=1)
        sources = ttk.LabelFrame(main, text="第 2 步：明文字典来源")
        sources.pack(fill="x", pady=(10, 0))
        for index, (method_name, label, path_type, hint) in enumerate(SOURCE_DEFS):
            enabled, value = BooleanVar(value=False), StringVar()
            self.source_vars[method_name], self.source_paths[method_name] = enabled, value
            row, col = index // 2, (index % 2) * 4
            ttk.Checkbutton(sources, text=label, variable=enabled).grid(row=row, column=col, sticky="w", padx=(4, 4), pady=3)
            ttk.Entry(sources, textvariable=value).grid(row=row, column=col + 1, sticky="ew", padx=4, pady=3)
            ttk.Button(sources, text="浏览", command=lambda v=value, t=path_type: self._browse(v, t)).grid(row=row, column=col + 2, padx=(0, 8), pady=3)
            ttk.Label(sources, text=hint, foreground="#6b7280").grid(row=row, column=col + 3, sticky="w", padx=(0, 8), pady=3)
            sources.columnconfigure(col + 1, weight=1)
        actions = ttk.LabelFrame(main, text="第 3 步：执行")
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="只生成不重命名", command=self.run_generate_only).grid(row=0, column=0, padx=4, pady=6)
        ttk.Button(actions, text="生成 HxNames 并重命名", command=self.run_generate).grid(row=0, column=1, padx=4, pady=6)
        ttk.Button(actions, text="我不知道怎么选", command=self._show_quick_guide).grid(row=0, column=2, padx=4, pady=6)
        self._path_row(actions, "恢复目录结构", self.restore_dir, "dir", 1, "GARBro 把目录 hash 和文件 hash 拼在一起时用")
        ttk.Button(actions, text="执行恢复", command=self.run_restore).grid(row=1, column=3, padx=4, pady=4)
        self._path_row(actions, "待清理目录", self.clean_dir, "dir", 2, "已经反混淆过的目录")
        self._path_row(actions, "清理输出 lst", self.clean_output_path, "save", 3, "发布前导出更干净的列表")
        ttk.Button(actions, text="生成干净 HxNames", command=self.run_clean).grid(row=3, column=3, padx=4, pady=4)
        actions.columnconfigure(1, weight=1)
        log_frame = ttk.LabelFrame(main, text="运行日志")
        log_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.log = ScrolledText(log_frame, height=16, wrap="word")
        self.log.pack(fill="both", expand=True)
        self.log.insert("end", "欢迎。第一次建议先点“只生成不重命名”，确认没有报错后再执行自动重命名。\n")

    def _path_row(self, parent, label, variable, path_type, row, tip=""):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(parent, text="浏览", command=lambda: self._browse(variable, path_type)).grid(row=row, column=2, padx=4, pady=4)
        if tip:
            ttk.Label(parent, text=tip, foreground="#6b7280").grid(row=row, column=3, sticky="w", padx=(0, 4), pady=4)

    def _browse(self, variable, path_type):
        if path_type == "dir":
            selected = filedialog.askdirectory()
        elif path_type == "file":
            selected = filedialog.askopenfilename()
        else:
            selected = filedialog.asksaveasfilename(defaultextension=".lst", filetypes=[("HxNames list", "*.lst"), ("All files", "*.*")])
        if selected:
            variable.set(selected)

    def _show_quick_guide(self):
        messagebox.showinfo("怎么选来源", "最短路线：\n1. 要处理的目录：选解包后的资源总目录。\n2. 有 scn 目录就勾“扫描 scn/PSB 剧本目录”。\n3. 有未加密版、体验版或旧版资源目录，就勾“从明文目录收集文件名”。\n4. CSV、PBD、replay.ks 看见哪个就勾哪个。\n5. 第一次建议点“只生成不重命名”。")

    def _poll_output(self):
        while True:
            try:
                text = self.output_queue.get_nowait()
            except queue.Empty:
                break
            self.log.insert("end", text)
            self.log.see("end")
        self.root.after(80, self._poll_output)

    def _run_worker(self, target):
        if self.running:
            messagebox.showinfo("正在运行", "当前任务还没结束，请等它跑完。")
            return
        self.running = True
        self.log.delete("1.0", "end")
        def worker():
            writer = QueueWriter(self.output_queue)
            with redirect_stdout(writer), redirect_stderr(writer):
                try:
                    target()
                    print("\n完成。")
                except Exception:
                    print("\n发生错误:")
                    traceback.print_exc()
                finally:
                    self.running = False
        threading.Thread(target=worker, daemon=True).start()

    def run_generate(self):
        self._run_worker(self._generate)

    def run_generate_only(self):
        previous = self.do_rename.get()
        self.do_rename.set(False)
        def runner():
            try:
                self._generate()
            finally:
                self.do_rename.set(previous)
        self._run_worker(runner)

    def _generate(self):
        rename_dir = Path(self.rename_dir.get()).expanduser().resolve()
        hxnames_path = Path(self.hxnames_path.get()).expanduser().resolve()
        if not rename_dir.exists():
            raise FileNotFoundError(f"要处理的目录不存在: {rename_dir}")
        config = Config(project_dir=self.project_dir, rename_dir=rename_dir)
        set_hashlib(config)
        dictionary = PlainDict(config=config, pathnames=["/"], filenames=DEFAULT_FILENAMES.copy())
        selected_count = 0
        for method_name, label, _path_type, _hint in SOURCE_DEFS:
            if not self.source_vars[method_name].get():
                continue
            source_path = self.source_paths[method_name].get().strip()
            if not source_path:
                print(f"跳过 {label}: 勾选了但没有填写路径")
                continue
            print(f"读取来源: {label}\n  {source_path}")
            getattr(dictionary, method_name)(source_path)
            selected_count += 1
        if selected_count == 0:
            print("没有选择额外来源，只使用内置常见文件名。还原率通常会比较低。")
        if self.duplicate_lower.get():
            dictionary.duplicate_lower()
        path_hash_map, file_hash_map = read_hxnames(hxnames_path)
        path_to_hash = dictionary.pathname_plaintexts - set(path_hash_map.keys())
        file_to_hash = dictionary.filename_plaintexts - set(file_hash_map.keys())
        print(f"新增目录名: {len(path_to_hash)} 个")
        print(f"新增文件名: {len(file_to_hash)} 个")
        for pathname in sorted(path_to_hash):
            pathname = pathname.strip().replace("\ufeff", "")
            if pathname:
                path_hash_map[pathname] = get_path_hash(pathname)
        for filename in sorted(file_to_hash):
            filename = filename.strip().replace("\ufeff", "")
            if filename:
                file_hash_map[filename] = get_file_hash(filename)
        write_hxnames(hxnames_path, path_hash_map, file_hash_map)
        print(f"已写入: {hxnames_path}")
        if self.do_rename.get():
            print("开始按 HxNames 重命名目录和文件...")
            rename_hashed_items(rename_dir, path_hash_map, file_hash_map)
        else:
            print("已跳过自动重命名，只生成 HxNames.lst。")

    def run_restore(self):
        self._run_worker(self._restore)

    def _restore(self):
        root_dir = Path(self.restore_dir.get()).expanduser().resolve()
        if not root_dir.exists():
            raise FileNotFoundError(f"目录不存在: {root_dir}")
        for child in root_dir.iterdir():
            if child.is_dir():
                print(f"恢复目录: {child}")
                restore_dir_structure(str(child))

    def run_clean(self):
        self._run_worker(self._clean)

    def _clean(self):
        hxnames_path = Path(self.hxnames_path.get()).expanduser().resolve()
        clean_dir = Path(self.clean_dir.get()).expanduser().resolve()
        clean_output_path = Path(self.clean_output_path.get()).expanduser().resolve()
        if not hxnames_path.exists():
            raise FileNotFoundError(f"HxNames 不存在: {hxnames_path}")
        if not clean_dir.exists():
            raise FileNotFoundError(f"待清理目录不存在: {clean_dir}")
        generate_clean_hxnames(hxnames_path, clean_dir, clean_output_path)
        print(f"已写入: {clean_output_path}")

if __name__ == "__main__":
    root = Tk()
    Hxv4Gui(root)
    root.mainloop()
