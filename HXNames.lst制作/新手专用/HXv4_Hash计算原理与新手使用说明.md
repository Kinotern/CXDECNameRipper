# HXv4 HxNames 计算原理与新手使用说明

这份说明面向第一次接触 `HxNames.lst`、HXv4 hash、Kirikiroid/KRKR 资源反混淆的人。重点解释三个问题：

1. 这个工具为什么不用打开游戏也能算出 hash。
2. `HxNames.lst` 里面的 hash 到底是怎么来的。
3. 新手应该按什么顺序使用 GUI，避免一上来就选错目录。

---

## 1. 一句话结论

这个工具不是通过启动游戏来计算 hash，而是通过项目自带的 DLL 离线计算。

核心文件是：

```text
binaries/KrkrHxv4Hash.dll
```

Python 程序会加载这个 DLL，然后把明文文件名或目录名传进去。DLL 内部实现了 HXv4 的 hash 算法，所以可以直接得到游戏资源中使用的 hash 名。

简单流程：

```text
明文名 -> Python 转成 UTF-16LE -> 调用 KrkrHxv4Hash.dll -> 得到 hash -> 写入 HxNames.lst
```

所以它不需要打开游戏，也不需要让游戏运行起来。

---

## 2. HxNames.lst 是什么

`HxNames.lst` 是一个“hash 与明文名的对照表”。

格式通常是：

```text
hash:明文名
```

例如：

```text
94D4A97C61498621:/
0123456789ABCDEF:bgimage/
00A93384A021B7BEC8FF4E8993126ABC11AE9473B411D1893594DC96271F219E:bg001.png
```

其中：

- 左边是游戏资源里实际看到的 hash。
- 右边是推测或收集到的原始明文名称。

工具拿到这个表以后，就可以把资源目录中的 hash 文件名还原成更容易看懂的名字。

---

## 3. 文件 hash 和目录 hash 不一样

HXv4 里常见两类 hash。

### 3.1 目录 hash

目录 hash 长度是 16 个十六进制字符。

例如：

```text
94D4A97C61498621
```

代码里对应：

```python
get_path_hash(pathname)
```

返回值是一个 64 位整数，Python 再把它格式化成 16 位大写十六进制字符串。

目录名通常带 `/`，例如：

```text
/
bgimage/
fgimage/
voice/chara/
```

注意：目录 hash 算的是路径名，不是普通文件名。

### 3.2 文件 hash

文件 hash 长度是 64 个十六进制字符。

例如：

```text
00A93384A021B7BEC8FF4E8993126ABC11AE9473B411D1893594DC96271F219E
```

代码里对应：

```python
get_file_hash(filename)
```

DLL 返回 32 个字节，Python 把这 32 个字节转成 64 个十六进制字符。

文件名通常是：

```text
base.stage
cg001.png
voice001.ogg
replay.ks
```

---

## 4. Python 代码实际做了什么

相关代码在：

```text
utils/krkr/hxv4/hash.py
```

核心逻辑大概是：

```python
mylib = ctypes.CDLL(str(data.resolve()))
```

这行会加载 DLL。

然后声明 DLL 函数参数和返回值：

```python
mylib.get_filename_hash.argtypes = [ctypes.c_wchar_p]
mylib.get_filename_hash.restype = ctypes.POINTER(ctypes.c_uint8)

mylib.get_path_hash.argtypes = [ctypes.c_wchar_p]
mylib.get_path_hash.restype = ctypes.c_uint64
```

意思是：

- `get_filename_hash` 接收一个宽字符字符串，返回 32 字节 hash。
- `get_path_hash` 接收一个宽字符字符串，返回一个 64 位整数。

---

## 5. 为什么要转 UTF-16LE

Windows 下很多原生程序和 DLL 使用宽字符，也就是 `wchar_t` 风格字符串。

Python 里的字符串不能直接丢给这个 DLL，所以工具先做转换：

```python
def _str_to_utf16_ptr(s: str):
    utf16_bytes = s.encode("utf-16le") + b"\x00\x00"
    buf = ctypes.create_string_buffer(utf16_bytes)
    return ctypes.cast(buf, ctypes.c_wchar_p)
```

这段做了三件事：

1. 把 Python 字符串编码成 `UTF-16LE`。
2. 末尾补 `\x00\x00`，表示宽字符字符串结束。
3. 转成 DLL 能接收的 `c_wchar_p` 指针。

也就是说：

```text
"bg001.png"
```

会先变成 Windows 宽字符形式，再交给 DLL。

---

## 6. 文件名 hash 的计算流程

代码：

```python
def get_file_hash(filename: str) -> str:
    ptr = _str_to_utf16_ptr(filename)
    arr_ptr = mylib.get_filename_hash(ptr)
    hash_result = ''.join(f"{arr_ptr[i]:02X}" for i in range(32))
    return hash_result
```

逐步解释：

1. `filename` 是明文文件名，例如 `bg001.png`。
2. `_str_to_utf16_ptr(filename)` 把它转成 DLL 能读的宽字符指针。
3. `mylib.get_filename_hash(ptr)` 调用 DLL 里的文件名 hash 函数。
4. DLL 返回 32 个字节。
5. Python 循环读取这 32 个字节。
6. 每个字节格式化成 2 位大写十六进制。
7. 最终拼成 64 位十六进制字符串。

示意：

```text
bg001.png
  -> UTF-16LE 宽字符
  -> get_filename_hash
  -> 32 bytes
  -> 64 hex chars
```

---

## 7. 目录 hash 的计算流程

代码：

```python
def get_path_hash(pathname: str) -> str:
    ptr = _str_to_utf16_ptr(pathname)
    num = mylib.get_path_hash(ptr)
    hash_result = f"{num:016X}"
    return hash_result
```

逐步解释：

1. `pathname` 是明文目录名或路径，例如 `bgimage/`。
2. 转成 UTF-16LE 宽字符。
3. 调用 DLL 的 `get_path_hash`。
4. DLL 返回一个 64 位整数。
5. Python 把它格式化成 16 位大写十六进制。

示意：

```text
bgimage/
  -> UTF-16LE 宽字符
  -> get_path_hash
  -> uint64
  -> 16 hex chars
```

---

## 8. 为什么它需要“明文来源”

这个工具能计算 hash，但它不能凭空知道原文件名。

也就是说，它能做的是：

```text
已知明文名 -> 算出 hash
```

它不能直接做：

```text
只给 hash -> 反推出明文名
```

hash 本质上是单向映射，不能可靠逆推。因此工具必须先收集一批候选明文名。

这些候选明文名来自：

- `scn` / PSB 剧本文件
- 未加密资源目录
- 体验版或旧版资源目录
- `base.stage`
- `cglist.csv`
- `soundlist.csv`
- `charvoice.csv`
- `imagediffmap.csv`
- `savelist.csv`
- `scenelist.csv`
- `replay.ks`
- KrkrDump 日志
- `fgimage` 立绘目录
- PBD 文件或目录

收集到候选名后，工具再批量计算它们的 hash，写成 `HxNames.lst`。

---

## 9. 整体工作流程

完整流程可以理解成：

```text
解包游戏资源
  -> 得到一堆 hash 文件名/目录名
  -> 从脚本、CSV、旧版资源、日志中收集可能的明文名
  -> 对每个明文名离线计算 HXv4 hash
  -> 生成 HxNames.lst
  -> 用 HxNames.lst 把 hash 文件名重命名回明文名
```

更细一点：

```text
明文候选名列表
  -> get_path_hash / get_file_hash
  -> hash:明文名
  -> HxNames.lst
  -> 匹配磁盘上的 hash 文件名
  -> 重命名
```

---

## 10. GUI 推荐使用顺序

新手建议按这个顺序来。

### 第一步：先解包游戏

先用你习惯的工具把 xp3 解包出来，例如：

- KrkrExtractForCxdecV2
- GARBro / GARBro2
- 其他支持目标游戏的解包工具

解包后应该得到一个资源目录，里面可能有大量 hash 名文件或目录。

### 第二步：打开 GUI

双击：

```text
启动GUI.bat
```

它会安装 `requirements.txt` 里的依赖，然后启动：

```text
hxv4_gui.py
```

### 第三步：选择“要处理的目录”

这里选解包后的资源总目录。

不要选工具目录本身，除非你的资源真的就在工具目录里。

### 第四步：选择 HxNames.lst 输出位置

默认是：

```text
工具目录/HxNames.lst
```

通常保持默认即可。

### 第五步：勾选明文来源

不知道选什么时，优先级如下：

1. 有 `scn` 或 PSB 剧本目录：勾选“扫描 scn/PSB 剧本目录”。
2. 有未加密版、体验版、旧版资源：勾选“从明文目录收集文件名”。
3. 看到 `cglist.csv`、`soundlist.csv`、`charvoice.csv` 等文件：对应勾选。
4. 有 KrkrDump 日志：勾选 KrkrDump 日志目录。
5. 有 `fgimage`、PBD、`_chthum_index.pbd`：对应勾选。

### 第六步：第一次建议只生成不重命名

第一次使用建议点击：

```text
只生成不重命名
```

这样会先生成 `HxNames.lst`，但不会改你的资源目录。

确认日志没有明显报错后，再考虑点击：

```text
生成 HxNames 并重命名
```

---

## 11. 每个来源选项是什么意思

### 扫描 scn/PSB 剧本目录

适合有脚本目录时使用。

脚本里通常会出现：

- 背景图名
- BGM 名
- 音效名
- 语音名
- 立绘名
- 演出资源名

这个来源通常很重要。

### 从明文目录收集文件名

适合你有另一份能看懂文件名的资源目录。

常见情况：

- 体验版没有完全加密
- 旧版资源名是明文
- 其他平台版本资源名是明文
- 有人已经整理过一份明文资源目录

这是提升还原率最有效的来源之一。

### 读取 base.stage

`base.stage` 里可能包含基础资源引用。

如果解包目录里能找到它，就可以勾选。

### 读取 cglist.csv

CG 列表，通常能补 CG 图片相关文件名。

### 读取 soundlist.csv

音效列表，通常能补 SE、BGM 或其他声音文件名。

### 读取 charvoice.csv

角色语音列表，通常能补系统语音或角色语音文件名。

### 读取 imagediffmap.csv

图片差分映射表，可能补差分图相关文件名。

### 扫描背景语音目录

用于补 `bgv` 一类背景语音文件。

### 读取 savelist.csv

可能补存档缩略图、回想、系统相关文件名。

### 读取 scenelist.csv

可能补章节、场景、回想列表相关资源名。

### 读取 KrkrDump 日志目录

如果你用 KrkrDump 或类似工具抓过资源访问日志，可以从日志里提取明文名。

### 扫描 fgimage 立绘目录

用于补立绘文件名。

### 扫描 PBD 目录

用于补 PBD 相关资源名。

### 读取 _chthum_index.pbd

用于补人物缩略图或相关索引里的名字。

### 读取 replay.ks 影片列表

用于补视频文件名。

---

## 12. 为什么还原率不是 100%

因为工具只能计算“已经知道明文名”的 hash。

如果某个资源名从来没有出现在：

- 剧本
- CSV
- 明文目录
- 日志
- PBD 索引
- 默认文件名列表

那工具就没有候选名，自然算不出对应关系。

所以还原率低时，通常不是 hash 算错了，而是明文来源不够。

提升还原率的方法：

1. 找更多同游戏旧版、体验版、其他平台版本资源。
2. 多收集 CSV、脚本、PBD、日志。
3. 用 KrkrDump 运行游戏流程，收集更多实际访问到的名字。
4. 手动补充你确认过的明文名。

---

## 13. HxNames.lst 里为什么有 16 位和 64 位 hash 混在一起

这是正常的。

判断规则：

```text
16 位 hash  -> 目录 hash
64 位 hash  -> 文件 hash
```

代码里也是这样判断的：

```python
if len(hx_hash) == 16:
    path_hash_map[hx_name] = hx_hash
elif len(hx_hash) == 64:
    file_hash_map[hx_name] = hx_hash
```

所以一个 `HxNames.lst` 同时保存目录名和文件名。

---

## 14. 小写副本是什么意思

GUI 里有一个选项：

```text
同时加入小写文件名/目录名
```

它会把已有候选名复制一份小写版本。

例如：

```text
AppConfig.tjs
```

会额外加入：

```text
appconfig.tjs
```

这样做的原因是：有些游戏或工具链里，大小写可能不完全一致。多算一份小写名，可以提高命中率。

缺点是：候选数量会变多，`HxNames.lst` 也会更大。

---

## 15. 自动重命名做了什么

当选择“生成后自动重命名目录和文件”时，工具会：

1. 读取 `HxNames.lst`。
2. 建立 `hash -> 明文名` 的反查表。
3. 遍历你选择的资源目录。
4. 如果文件名命中某个文件 hash，就重命名成明文文件名。
5. 如果目录名命中某个目录 hash，就重命名成明文目录名。

如果目标名字已经存在，工具会用 `get_unique_name` 自动加后缀，避免直接覆盖。

例如：

```text
bg001.png
bg001_1.png
bg001_2.png
```

---

## 16. 为什么建议第一次只生成不重命名

因为自动重命名会修改你的解包目录。

如果你第一次路径选错，可能会把不该处理的目录也改名。

建议流程：

1. 第一次点击“只生成不重命名”。
2. 看日志是否报错。
3. 检查 `HxNames.lst` 是否生成。
4. 确认要处理的目录没选错。
5. 再点击“生成 HxNames 并重命名”。

更稳妥的话，先复制一份解包目录作为备份。

---

## 17. 常见错误

### 17.1 找不到 hxv4_gui.py

报错类似：

```text
python: can't open file '...\hxv4_gui.py': [Errno 2] No such file or directory
```

原因：启动脚本要运行 `hxv4_gui.py`，但文件不存在。

解决：确认工具目录下有：

```text
hxv4_gui.py
```

### 17.2 找不到 KrkrHxv4Hash.dll

如果 DLL 缺失，hash 计算无法进行。

确认存在：

```text
binaries/KrkrHxv4Hash.dll
```

### 17.3 勾选了来源但没有填路径

GUI 日志会提示跳过。

解决：取消勾选，或者点击“浏览”选择对应文件/目录。

### 17.4 还原率很低

常见原因：明文来源太少。

解决：增加来源，例如：

- 更多 CSV
- 剧本目录
- 明文资源目录
- KrkrDump 日志
- PBD 索引

### 17.5 目录和文件选反

有些选项需要目录，有些选项需要文件。

例如：

```text
扫描 scn/PSB 剧本目录 -> 选择目录
读取 cglist.csv -> 选择文件
```

选错后可能会报路径错误或没有结果。

---

## 18. 这个工具和“开游戏抓 hash”的区别

有些工具需要开游戏，是因为它们依赖游戏运行时：

- 让游戏自己访问资源
- 从内存或日志里抓资源名
- 或者通过引擎函数计算 hash

这个工具不同。

它已经有离线 hash DLL：

```text
KrkrHxv4Hash.dll
```

所以只要知道明文候选名，就能直接算 hash。

对比：

```text
开游戏抓取方式：运行游戏 -> 观察游戏访问了什么 -> 得到名字或 hash
本工具方式：收集明文候选名 -> 离线调用 DLL -> 得到 hash
```

两者可以配合使用。

KrkrDump 日志就是一种补充明文来源的方法。你可以先用运行时工具收集日志，再让本工具读取日志，提高候选名数量。

---

## 19. 最重要的理解

这个工具不是“破解 hash”。

它做的是：

```text
我猜这个文件原名可能叫 bg001.png
  -> 算一下 bg001.png 的 HXv4 hash
  -> 看这个 hash 是否和磁盘上的 hash 文件名一致
  -> 一致就知道它原来叫 bg001.png
```

所以它的核心能力是：

```text
批量验证候选明文名
```

而不是：

```text
从 hash 直接反推出原名
```

---

## 20. 推荐新手流程总结

最省心的流程：

1. 解包游戏 xp3。
2. 双击 `启动GUI.bat`。
3. “要处理的目录”选择解包后的资源总目录。
4. 勾选 `扫描 scn/PSB 剧本目录`，路径选择 `scn` 或包含 PSB 的目录。
5. 如果有体验版/旧版/未加密资源，勾选 `从明文目录收集文件名`。
6. 有 CSV、PBD、replay.ks 就对应勾选。
7. 第一次点击 `只生成不重命名`。
8. 没报错后，再点击 `生成 HxNames 并重命名`。
9. 如果还原率低，继续补更多明文来源。

---

## 21. 文件对应关系速查

```text
启动GUI.bat
  启动 GUI。

hxv4_gui.py
  新手向导界面，负责收集路径、调用生成逻辑、执行重命名。

plain_dict.py
  从脚本、CSV、目录、日志等来源收集候选明文名。

utils/krkr/hxv4/hash.py
  通过 ctypes 调用 KrkrHxv4Hash.dll 计算 hash。

binaries/KrkrHxv4Hash.dll
  真正实现 HXv4 hash 算法的 DLL。

HxNames.lst
  生成出来的 hash:明文名 对照表。

HxNames-clean.lst
  发布前可生成的精简版对照表。
```

---

## 22. 一张简图

```text
             明文来源
  scn / csv / pbd / 旧版资源 / dump日志
                 |
                 v
          plain_dict.py 收集候选名
                 |
                 v
       utils/krkr/hxv4/hash.py
                 |
                 v
        KrkrHxv4Hash.dll 离线计算
                 |
                 v
              HxNames.lst
                 |
                 v
        按 hash 匹配并重命名资源
```

---

## 23. 结论

它不用开游戏，是因为 hash 算法已经被封装在本地 DLL 里。

它能不能还原出更多名字，主要取决于你给它多少明文候选来源。

可以记成一句话：

```text
DLL 负责算 hash，plain_dict 负责找候选名，HxNames.lst 负责保存对应关系，GUI 负责把流程串起来。
```
