# UE4SS + PalChatRelay 安装与验证（Windows 自建服）

目标：让服务端把游戏内聊天写进 `UE4SS.log`，外部机器人才能读到。
全程**只读**——`PalChatRelay` 不修改任何游戏参数，也不调用发送接口。

下面用 `C:\PalServer` 当服务器根目录，换成你自己的路径。

---

## 实测记录（UE4SS v3.0.1 Beta + 帕鲁专用服 v1.0.5）

这些是踩出来的，不是猜的，换版本时先对照这里：

| 项目 | 结论 |
| --- | --- |
| 聊天入口 | `/Script/Pal.PalGameStateInGame:BroadcastChatMessage` |
| 不存在 | `PalPlayerController:ServerSendChatMessage`、`SendChatMessage`、`PalChatManager`（整个类都没有） |
| 回调参数 | 不是 Lua 值，是 `RemoteUnrealParam` / `LocalUnrealParam`，必须 `:get()` 解包 |
| 参数 1 | `AActor`（发送者角色） |
| 参数 2 | `FPalChatMessage` 结构体：`Sender`(StrProperty)、`Message`(StrProperty)、`Category`、`MessageId`、`MessageArgValues` |
| 取文本 | `param:get().Message` 得到 `FString` 包装，再 `:ToString()` 才是字符串 |
| 触发次数 | 同一条聊天会触发 **2 次**，机器人侧靠 30 秒去重挡掉 |
| 日志格式 | `[PALBOT] 玩家名<TAB>聊天内容` |
| Lua print | 不会自动换行，`print(x .. "\n")` 才能保证下一条日志不粘连 |

> 另一个坑：如果服务器控制台窗口被关掉，UE4SS 的日志输出通道会死掉（进程还活着、REST 正常、
> 玩家也在线，但 `UE4SS.log` 不再增长）。解决办法是用隐藏窗口 + 输出重定向启动，
> 别让窗口暴露出来被人误关。

---

## 0. 准备

1. **先停服**：DLL 被占用时复制会失败。
2. 确认目录结构（`PalServer-Win64-Shipping.exe` 必须在这个位置）：

```powershell
$Srv   = "C:\PalServer"
$Win64 = "$Srv\Pal\Binaries\Win64"
Test-Path "$Win64\PalServer-Win64-Shipping.exe"   # 应该返回 True
```

3. 记下你的帕鲁版本（Steam 库 → 右键 Palworld → 属性 → 已安装文件），
   UE4SS 的版本要和它匹配，否则会加载失败或直接崩。

---

## 1. 装 UE4SS

1. 打开 [Okaetsu/RE-UE4SS 的 experimental-palworld release](https://github.com/Okaetsu/RE-UE4SS/releases/tag/experimental-palworld)，
   下 `UE4SS-Palworld.zip`。
2. 解压后应该看到两样东西：

```
dwmapi.dll
ue4ss\
```

3. 把这两样**都**复制进 `$Win64`（和 `PalServer-Win64-Shipping.exe` 同目录）：

```powershell
Copy-Item "C:\下载\UE4SS-Palworld\dwmapi.dll" $Win64 -Force
Copy-Item "C:\下载\UE4SS-Palworld\ue4ss" $Win64 -Recurse -Force
```

4. **解除锁定**（从网上下载的 DLL 会被 Windows 标记，不解除经常加载失败）：

```powershell
Unblock-File "$Win64\dwmapi.dll"
Get-ChildItem "$Win64\ue4ss" -Recurse -File | Unblock-File
```

> 杀软有可能直接把 `dwmapi.dll` 删掉。装完先看一眼文件还在不在。

---

## 2. 验证 UE4SS 本身加载了

启动服务器，然后：

```powershell
Test-Path "$Win64\ue4ss\UE4SS.log"          # True = UE4SS 起来了
Get-Content "$Win64\ue4ss\UE4SS.log" -Tail 20
```

- 文件存在、里面有 `UE4SS` 版本号和加载信息 → 继续下一步。
- 文件不存在 → UE4SS 没加载。按顺序查：
  1. `dwmapi.dll` 还在不在（被杀软吃了）；
  2. 是不是解压到了 `Pal\Binaries\Win64` 而不是服务器根目录；
  3. 该版本 UE4SS 是否支持你的帕鲁版本（换 release）。

有的构建启动时会额外弹一个黑色的 UE4SS 控制台窗口，那个窗口里能直接看到 Lua 的 `print` 输出。

---

## 3. 装 PalChatRelay

1. 把仓库里的整个文件夹复制过去（**目录名和层级必须保持**：

   ```
   ue4ss\Mods\PalChatRelay\Scripts\main.lua
   ```
   `Scripts` 里必须是 `main.lua`，不是 `main.lua.txt`）：

```powershell
Copy-Item "C:\...\palworld-deepseek-bot\ue4ss\Mods\PalChatRelay" "$Win64\ue4ss\Mods\" -Recurse -Force
```

2. 在 `ue4ss\Mods\mods.txt` 里加一行（文件末尾追加即可）：

```powershell
Add-Content "$Win64\ue4ss\Mods\mods.txt" "`r`nPalChatRelay : 1"
Get-Content "$Win64\ue4ss\Mods\mods.txt" -Tail 5     # 确认加上了
```

   格式就是 `模块名 : 1`，`1` 表示启用。原有的 `BPModLoaderMod : 1` 之类不要删。

3. 重启服务器。

---

## 4. 验证 mod 加载

```powershell
Select-String -Path "$Win64\ue4ss\UE4SS.log" -Pattern '\[PALBOT\]'
```

按下面对号入座：

| 日志里出现 | 含义 | 下一步 |
| --- | --- | --- |
| `[PALBOT] hooked /Script/Pal...` ×N + `ready, N hook(s)` | 钩子挂上了 | 进游戏说句话，看第 5 步 |
| 全是 `[PALBOT] miss ...` + `WARN` + `CANDIDATE ...` | 钩子名对不上，但自动列出了候选 | 把这些行发我 |
| `WARN /Script/Pal.PalPlayerController 不存在` | 类路径不对或 UE4SS 没吃上 | 确认第 2 步 |
| 一条 `[PALBOT]` 都没有 | mod 没被加载 | 查 `mods.txt`、目录层级、`media/lua` 是否被拦 |

---

## 5. 验证聊天真的出来了

保持服务器运行，进游戏随便说一句话，然后：

```powershell
Get-Content "$Win64\ue4ss\UE4SS.log" -Wait -Tail 20 | Select-String '\[PALBOT\]'
```

预期看到：

```
[PALBOT] 你的名字	你说的那句话
```

- 看到了 → 把机器人切到真链路：
  ```toml
  [server]
  mode = "log"
  log_path = 'C:\PalServer\Pal\Binaries\Win64\ue4ss\UE4SS.log'
  ```
  再 `python run.py --doctor`，`聊天来源` 应该变 `✓`。
- 只有 `ready` 但没有聊天行 → 说明**挂上的是错函数**（注册成功但游戏不调它）。
  把 `hooked` 的那几行发我，我会换成别的候选。

---

## 6. 如果自动发现也给不出候选

三个办法，按省事程度排：

1. **看现成 mod 怎么写的**：Nexus 上搜 Palworld 的 UE4SS 聊天/指令 mod，下载后看
   `Scripts\main.lua` 里的 `RegisterHook` 那行写的是什么路径，直接把它发我。
2. **UE4SS 控制台**：如果启动了 GUI 控制台，输入 `help`，看有没有
   `dump_object` / `DumpObject` 之类的命令，用它 dump `/Script/Pal.PalPlayerController`，
   把含 `Chat` 的函数名发我。
3. **UE4SS 自带的 dump**：有些构建会在 `ue4ss\Dumps\` 下生成类结构文件，
   在里面搜 `Chat` 也能找到函数名。

---

## 7. 常见故障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 服务器启动即崩 | UE4SS 版本不匹配 | 换与游戏版本对应的 release；先把 `ue4ss\Mods` 清空只留本体试 |
| 联机正常但日志不更新 | 日志被别的东西锁住 / 换构建了 | 关服后确认文件时间戳 |
| `main.lua` 被改名成 `main.lua.txt` | Windows 隐藏扩展名 | 关掉"隐藏已知文件扩展名"再改 |
| 每次更新游戏后 mod 失效 | 帕鲁更新会改类/函数 | 更新 UE4SS，并把新的 `[PALBOT]` 行发我 |
