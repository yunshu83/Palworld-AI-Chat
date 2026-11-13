# 小鱼（鲸鱼娘）· 帕鲁服务端 DeepSeek 聊天助手

玩家在游戏里说话 → 只挑命中**关键词**的那几条 → 问 DeepSeek → 以「小鱼」人设回一两句。
问好、道谢、叫她"大肥鱼"这类话走**本地预设**，一个 token 都不花。

---

## 快速部署（换机器 / 重新部署看这里）

**不需要装 Python**：本目录下的 `python\` 就是内置的 Python 3.12（便携版）。
`start.bat` 会优先用它；没有才去系统里找。

```bat
:: 1. 配置（探测服务器路径、装聊天钩子、填 Key、选模型）
setup.bat
:: 或： python run.py wizard

:: 2. 体检
python run.py --doctor

:: 3. 启动
start.bat
:: 或： python run.py
```

向导会做五件事：

1. 从 Steam 库目录自动找 `PalServer`；找不到才让你粘路径；
2. 检查服务器是否装了 **UE4SS**（没装会给出下载地址，因为读聊天必须靠它）；
3. 把 `PalChatRelay` 装进 `ue4ss\Mods\` 并写进 `mods.txt`（改前先备份）；
4. 选**接口地址**：官方 `https://api.deepseek.com`，或自己的中转站 URL；
5. 填 API Key 后**自动拉取该接口可用的模型列表**，让你选（默认推荐便宜的那档）；
6. 写 `config.local.json`（含 API Key，**明文**，已加入 `.gitignore`，不会进仓库）。

随时可以用 `python run.py models` 重新查看可用模型。

> 中转站：地址照它给的填，通常以 `/v1` 结尾（程序会自动补 `https://`、去掉尾部斜杠）。
> 有些中转站不支持 `/models`，向导会让你直接手输模型名。

装完记得**重启服务器**，mod 才会生效。

### 常用命令

| 命令 | 作用 |
| --- | --- |
| `python run.py` | 启动（没有配置会自动进向导） |
| `python run.py wizard` | 重新配置 |
| `python run.py models` | 列出当前 Key 可用的模型 |
| `python run.py data check` | 数据自检（0 错误才建议启动） |
| `python run.py data update` | 游戏更新后重新抓数据（默认试运行） |
| `python run.py data update --apply` | 确认无误后真正落盘 |
| `python run.py data import 文件.csv` | 用 Excel 批量补字段 |
| `python run.py --doctor` | 配置/Key/接口/日志全链路体检 |
| `python run.py --dry-run` | 不调模型，只看触发逻辑 |

### 手工补数据

抓取数据会被 `update-data` 覆盖，人工补充写到 `data/overrides/`：

```json
{ "items": [ { "name": "枯星龙", "set": { "elements": ["火", "暗"] } } ] }
```

同名条目会被 `set` 覆盖、`add` 追加；补丁里独有的名字会作为新条目加入。

补进去的字段要在 `data/fields.json` 里登记才会被用上：

```json
{ "fields": { "spawn": { "label": "刷新位置", "keywords": ["在哪", "刷新", "抓"] } } }
```

只有玩家问题命中 `keywords` 时，这个字段才会进提示词——这样补几十个字段也不会让每条消息都变长。

批量补数据用 Excel 更方便，存成 CSV（UTF-8）后导入：

```csv
name,spawn,capture
覆海龙,雪山地带,约 8%
雷鸣鸟,,约 5%
```

```bat
python run.py data import 我的补充.csv
```

空单元格会被跳过，不会覆盖已有值；结果写进 `data/overrides/paldex.json`，`update-data` 不会冲掉。

### 数据更新（游戏改版后）

```bat
python run.py data update            :: 抓取 + 校验 + 出报告，然后回滚（试运行）
python run.py data update --apply    :: 看完报告没问题，真正保留
```

流程固定五步：**备份 → 抓取 → 校验 → 出报告 → 落盘**。任何一步发现 `error` 都会自动回滚，
不会把好数据冲掉。报告写在 `data/UPDATE-<时间戳>.md`，列出新增/删除/数量变化。

`teams.json`、`elements.json`、`fields.json` 是人工维护的，抓不到，报告里会提醒你确认。

---

## 先看清一件事：帕鲁服务端读不到聊天

帕鲁官方 REST API 只能 `announce`（广播）、`kick`、`ban`、查在线人数，**没有任何接口能读到玩家聊天内容**。
所以"游戏内聊天 → AI"这条路，必须有一个跑在服务端进程里的 mod 把聊天事件送出来：

| 路线 | 能读聊天 | 能发回复 | 代价 |
| --- | --- | --- | --- |
| **UE4SS + 本项目的 PalChatRelay**（Windows 自建服，推荐） | 聊天打进 `UE4SS.log` | 官方 REST 公告 | 要装 UE4SS；只读不写，最稳 |
| **Palladium**（Docker 全套） | `player.chat` 事件 | `server.announce` / `player.message` | 建议 16GB 内存，整服搬进 Docker |
| **Takaro**（第三方桥） | 有 | 有 | 要注册 Takaro 账号，桥是闭源 exe |
| **官方 REST API 单独用** | ❌ 读不到 | 只能全服公告 | 只能"单向播报"，做不了问答 |

最后一行是关键：REST 好用到让人以为能读聊天，实际不行。如果你的服是租的托管面板、放不进 UE4SS，
那这套方案没法落地——这是帕鲁本身的限制，不是配置问题。

---

## 目录结构

```
palworld-deepseek-bot/
├─ run.py                 # 启动入口
├─ config.toml            # 全部配置：关键词、预设话、限额、连接方式
├─ persona.md             # 人设（改这个文件就能换人格，不用改代码）
├─ persona-lite.md        # 同一人设的精简版，省 token 用
├─ server_facts.md        # 本服事实 + 「不许编数值」规则
├─ bot/
│  ├─ settings.py         # 配置加载
│  ├─ router.py           # 触发判定：预设 / AI / 不理
│  ├─ deepseek.py         # DeepSeek 接口（OpenAI 兼容）
│  ├─ adapters.py         # 读聊天 / 发回复的各种通道
│  ├─ doctor.py           # --doctor 逐项体检
│  └─ service.py          # 主循环、提示词拼装、回复清洗
├─ ue4ss/Mods/PalChatRelay/Scripts/main.lua   # 服务端 mod：只把聊天打到日志
├─ tools/start-all.bat    # 双击 = 起服务器 + 起机器人（推荐日常用这个）
├─ tools/stop-all.bat     # 正常停服，机器人会跟着停
├─ docs/ue4ss-setup.md    # UE4SS 安装与验证的详细步骤
└─ tests/test_router.py   # 本地自检，不需要服务器和 Key
```

零第三方依赖，只要 **Python 3.11+**（用到标准库 `tomllib`）。

### 运行环境怎么来

- 用 DeepSeek Harness 的话，它自带一个 Python，路径形如
  `C:\Users\<你>\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`，
  直接拿它跑 `run.py` 就行，**不用 pip 装任何东西**。
- 想自己装就去 python.org 下 3.12，安装时勾 **Add python.exe to PATH**，之后命令就是 `python run.py`。
- 自检：`python -c "import sys, tomllib; print(sys.version)"`，能打印版本且不报错就够用。

---

## 第 0 步：一条命令看链路

接入过程里最常见的现象是"机器人不说话"，但原因可能出在三段中的任意一段。先体检：

```powershell
& "C:\Users\<你>\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" run.py --doctor
```

输出长这样：

```
小鱼 · 链路自检

  ✓ 配置：...\config.toml
  ✓ 人设：1832 字
  ✓ 触发规则：6 个关键词 / 6 条预设（18 句）
  ✗ DeepSeek Key：没读到
      → 设置环境变量 DEEPSEEK_API_KEY，或填 config.toml 的 [deepseek].api_key
  ! 回复出口：console（只打印，不发进游戏）
  ! 聊天来源：stdin（手动输入，没接服务器）
```

`✓` 通过、`!` 提醒（多半是还没接服务器）、`✗` 必须修。它只调 DeepSeek 的 `/models`
和帕鲁的 `/v1/api/info`，**不花 token**，可以随时跑。

---

## 第一步：不连服务器，先试跑一遍

```bash
# 1. 本地自检（判定逻辑对不对）
python tests/test_router.py

# 2. 用键盘假装玩家说话，dry-run 不花钱
python run.py --dry-run

# 然后在提示符后输入（格式「玩家名: 内容」）：
#   小明: 大肥鱼在吗
#   → 走出预设炸毛，不调 AI
#   小明: 小鱼 这游戏怎么快速升级
#   → 打印 "[dry-run] 这里会调用 deepseek-chat 生成回复"
#   小明: 今天打了三个帕鲁
#   → 跳过（没关键词）
```

`config.toml` 出厂就是 `[server].mode = "stdin"` + `[reply].transport = "console"`，
不连服务器、不发游戏内消息，也不改任何配置就能直接跑。

---

## 第二步：把真 key 配上

```powershell
# Windows PowerShell（当前窗口有效）
$env:DEEPSEEK_API_KEY = "sk-你的key"
python run.py            # 真调一次，能出回复就通了
```

```bash
# Linux
export DEEPSEEK_API_KEY="sk-你的key"
```

Key 在 <https://platform.deepseek.com> 的「API Keys」里建。建议用环境变量，别写进 `config.toml`（文件容易被截图外传）。

---

## 第三步：让服务端把聊天交出来

帕鲁官方 API 读不到聊天，必须在服务端进程里挂一个 mod。两条路，按你的服选一条。

### 路线 A：Windows 自建服（你的情况）

**详细到每条命令的版本：[docs/ue4ss-setup.md](docs/ue4ss-setup.md)**（含四种失败情形怎么判读）。下面是要点。

用 UE4SS + 本项目自带的 `PalChatRelay`。这个 mod **只读不写**：把聊天 `print` 进 `UE4SS.log`，
Python 按 `[PALBOT]` 前缀 tail。回复走官方 REST 的 `/v1/api/announce`（全服公告）。
因为完全不碰游戏参数，也就不会踩到 UE4SS 写聊天参数崩溃那个坑。

1. **装 UE4SS**：从 [Okaetsu 的 experimental-palworld 构建](https://github.com/Okaetsu/RE-UE4SS/releases/tag/experimental-palworld)
   下 `UE4SS-Palworld.zip`，把 `dwmapi.dll` 和 `ue4ss/` 放进 `[服务器]\Pal\Binaries\Win64\`。
   被 Windows 拦了就在文件属性里勾「解除锁定」。
2. **装 chat mod**：把本仓库的 `ue4ss/Mods/PalChatRelay/` 整个复制到
   `[服务器]\Pal\Binaries\Win64\ue4ss\Mods\PalChatRelay\`，
   然后在 `ue4ss\Mods\mods.txt` 里加一行：

   ```
   PalChatRelay : 1
   ```
3. **开官方 REST**：`Pal\Saved\Config\WindowsServer\PalWorldSettings.ini` 里设

   ```ini
   RESTAPIEnabled=True
   RESTAPIPort=8212
   AdminPassword=自己设一个
   ```
4. **填配置**：

   ```toml
   [server]
   mode = "log"
   log_path = 'C:\PalServer\Pal\Binaries\Win64\ue4ss\UE4SS.log'   # 改成你的真实路径

   [reply]
   transport = "rest"
   target = "announce"

   [palworld_rest]
   url = "http://127.0.0.1:8212"
   admin_password = "和 ini 里的一致"
   ```
5. **先启动服务器，再启动机器人**：

   ```powershell
   python run.py
   ```

6. **验证**：进游戏随便说句话，然后看 `UE4SS.log` 里有没有这样一行：

   ```
   [PALBOT] 你的名字	你说的那句话
   ```

   实测通过的样子（UE4SS v3.0.1 + 帕鲁 v1.0.5）：

   ```
   [PALBOT] hooked /Script/Pal.PalGameStateInGame:BroadcastChatMessage
   [PALBOT] ready, 1 hook(s)
   [PALBOT] 愈发想与你相会	小鱼 这游戏怎么升级快
   ```

   然后 `python run.py --once` 应该能看到：

   ```
   命中 愈发想与你相会: '小鱼 这游戏怎么升级快' → keyword:小鱼
   回复 ... (1067 tokens（缓存命中 896，计费口径 171）)
   ```

   - 没有 `[PALBOT]` 行 → 把 `UE4SS.log` 里所有 `[PALBOT]` 开头的行发我。
   - 有 `ready` 但没有聊天行 → 钩子挂上了但不接玩家发言，同样把那几行发我。

7. **常驻运行**：机器人要一直开着，关窗口就停了。推荐直接用一键脚本：

   ```powershell
   tools\start-all.bat     # 起服务器 + 起机器人，都是隐藏窗口
   tools\stop-all.bat      # 正常停服（走 REST，会存档），机器人跟着停
   ```

   `start-all.bat` 会：服务器没开就先开 → 等 REST 端口就绪 → 起机器人 → 之后一直盯着，
   服务器一退出就把机器人也停掉。两个进程都是**独立进程**，跟终端窗口、跟 DeepSeek Harness 都没关系，
   关掉它们不会影响机器人。

   日志都在 `logs\` 下：`bot-*.log` 是机器人输出，`launcher-*.log` 是启动器的流水账。

   手动跑也行（先服务器后机器人，机器人启动时要能读到日志）：

   ```powershell
   cd C:\Users\<你>\...\palworld-deepseek-bot
   python run.py
   ```

> `AdminPassword` 改完要重启服务器；REST 端口只开在本机，别映射到公网。

### 路线 B：Palladium（Docker 全套）

如果你愿意把服务器搬进 Docker，Palladium 提供完整的 HTTP 桥（`player.chat` 事件 + `server.announce` 动作）。
官方 quickstart：<https://argseby.github.io/Palladium/docs/quickstart/>。
资源要求：4 核、建议 16GB 内存、约 25GB 磁盘。它的镜像自带 UE4SS。

1. 按 quickstart 跑起来，确认面板 `http://<服务器IP>:3000` 能登录。
2. 面板里建 **API Token**，权限勾 `read` + `write`（发广播要 write）。
3. 配置：

   ```toml
   [server]
   mode = "palladium"
   bridge_url = "http://127.0.0.1:8080"
   bridge_token = "palup_xxxxxx"

   [reply]
   transport = "palladium"
   target = "announce"      # announce=全服可见；player=只回给提问的人
   ```

4. `python run.py`，进游戏说「小鱼 这游戏怎么升级快」。

> 拿不到 HTTP 端口时（容器端口没映射），把 `mode` 改成 `tail`、`jsonl_path` 指向
> `/palworld/logs/bridge-events.jsonl` 在宿主机上的挂载路径，回复仍走 HTTP。

---

## 只想用官方 REST 发回复？

把回复出口换成帕鲁官方的公告接口，好处是不用给面板 write token，坏处是只能全服公告：

```toml
[reply]
transport = "rest"
target = "announce"       # REST 只有全服公告，写 player 也会被强制成 announce

[palworld_rest]
url = "http://127.0.0.1:8212"
admin_password = "和 PalWorldSettings.ini 里 AdminPassword 一致"
```

同时 `PalWorldSettings.ini` 里要有 `RESTAPIEnabled=True`、`RESTAPIPort=8212`。

注意：REST **只管发，不管收**。换成它之后，聊天读取还得靠 `mode = "log"`（UE4SS.log）
或 `mode = "palladium"` / `"tail"`，光改 transport 不会凭空多出读取能力。

---

## 它怎么省 token：三道闸门

一条聊天进来，依次过三关，任何一关不过就不花钱：

1. **长度/前缀/去重**：`!` `/` `#` 开头的不理（留给别的插件），超长粘贴不理，30 秒内同一句重复不理。
2. **预设话**（`[[preset.rules]]`）：命中"你好/谢谢/大肥鱼"等，直接从本地数组里挑一句发出去——**0 token**，同一玩家 45 秒内不重复回。
3. **关键词**（`[trigger].ai_keywords`）：必须出现「小鱼 / 肥鱼 / 小助手 / 问问 / 求助 / deepseek」其中之一，才会调模型。

第 2 关里「大肥鱼」是特意排在 AI 之前拦下来的：她的雷点，必须当场炸毛，不能花 token 去问模型。

过了三关，还有三道上限：

- `per_player_cooldown = 10`：同一玩家 10 秒内只调一次（太长会让人以为机器人坏了）；
- `global_replies_per_minute = 6`：全服每分钟最多 6 次；
- `daily_token_budget = 200000`：当天用完就只回预设话，第二天自动重置。

**真实用量**（实测 2026-11，一次简单问答）：总 `1067 tokens`，其中 `896` 命中前缀缓存，
**计费口径只有 171**（缓存未命中 151 + 回复 20）。这个比例会稳定复现。

所以 `daily_token_budget` 扣的是**计费口径**，不是总 token——否则稳定的人设前缀每次都被按全价记账，
20 万预算只能撑 190 次，钱其实没花出去。按 171/次算，20 万预算约 **1000+ 次真实问答**。

三个省钱杠杆，按效果排序：

1. `history_turns = 0`：不留上下文，每次省掉历史那部分；
2. 精简 `persona.md`：影响的是**冷启动和缓存失效后的第一次**（约 1000 token 全价），
   热缓存下影响很小。所以它决定的是"每次重启/改人设后的第一笔"，不是常态；
3. `max_tokens = 80`：只影响回复那十几个 token，作用最小。

DeepSeek 的**上下文前缀缓存**是自动的，前提是前缀逐字节相同：
所以 `bot/service.py` 里 system 提示是所有玩家共用一段、**绝不拼玩家名**的，玩家名放在 user 消息里。
你改 `persona.md` 会让缓存失效一次，之后恢复。日志里每次都会打 `缓存命中 / 计费口径`，方便你盯。

**更省的模式**：把 `command_prefix = "问:"`，关键词就完全不起作用，只有玩家明确打「问:xxx」才触发 AI，日常闲聊一律静默。

---

## 帕鲁资料库（可选，但强烈建议）

`server_facts.md` 只能告诉模型"别编"，不能告诉它"正确答案"。真正让它答对的是本地资料库
`data/paldex.json`：

- 问题里认出了帕鲁名或工作类型（发电/挖矿/生火…）→ 把**准确的那几行**塞进这轮的 user 消息；
- 没认出 → 什么都不塞，模型按规则糊弄过去（"记不清，图鉴里翻"）。

所以没数据时它不会瞎编，有数据时它才敢报数字。文件格式：

```json
{
  "version": "v1.0.5",
  "source": "数据来源说明",
  "pals": [
    {
      "name": "阿努比斯",
      "aliases": ["Anubis", "阿努"],
      "elements": ["地"],
      "work": { "handiwork": 4, "mining": 3, "transporting": 2 },
      "stats": { "hp": 120, "attack": 130 },
      "drops": ["骨头", "巨大帕鲁之魂"]
    }
  ]
}
```

`work` 的键固定是这几个：`kindling` 生火、`watering` 浇水、`planting` 播种、
`generating_electricity` 发电、`handiwork` 手工、`gathering` 采集、`lumbering` 砍伐、
`mining` 采掘、`medicine_production` 制药、`cooling` 冷却、`transporting` 搬运、`farming` 牧场。

文件不存在时自动跳过，不影响机器人启动。改完重启机器人即可，不用动代码。

### 数据从哪来、怎么更新

`data/paldex.json` 由 `tools/scrape_paldb.py` 抓 [paldb.cn](https://paldb.cn/) 的帕鲁页面生成：

```powershell
python tools\scrape_paldb.py            # 全量（首次约 5 分钟，之后走缓存）
python tools\scrape_paldb.py --refresh  # 忽略缓存重新抓
python tools\scrape_paldb.py --limit 3  # 只抓前 3 个，验证解析
```

- 只读 `/pals/...` 页面，**不碰 `/api/`**（站点 robots.txt 明确禁止）；
- 每页间隔 0.5 秒，原始 HTML 缓存在 `data/raw/`，重复运行不会重复请求；
- 游戏大版本更新后，`--refresh` 重跑一遍即可。

字段：名字、英文名（别名）、属性、工作适应性等级、基础属性（HP/攻击/防御/工作速度）、
移动能力（行走/奔跑/游泳/耐力）、80 级属性范围、掉落物（含数量与概率）、
主动技能、被动技能、伙伴技能。

### 技能 / 材料 / 传奇图纸 / 科技树

`data/skills.json`、`data/materials.json`、`data/schematics.json` 由 `tools/scrape_extra.py` 生成；
`data/tech.json` 由 `tools/scrape_tech.py`（等级/科技点/描述）与 `tools/scrape_items.py`
（311 个物品页 → 材料清单，按名字合并进科技）共同生成（数据源是另一个站，见下）：

```powershell
python tools\scrape_extra.py            # 技能 326 页 + 材料 189 页 + 图纸列表页
python tools\scrape_extra.py --only skills
python tools\scrape_tech.py             # 科技树，单页
python tools\scrape_tech.py --refresh   # 忽略缓存重抓
```

| 文件 | 内容 | 条数 |
| --- | --- | --- |
| `skills.json` | 技能名、属性、远近、威力、冷却、描述 | 326 |
| `materials.json` | 材料名、描述、重量、堆叠上限 | 189 |
| `schematics.json` | 图纸名、品质（只留传奇） | 121（总 601） |
| `tech.json` | 科技名、解锁等级、科技点、描述、**材料清单** | 587（1~80 级，其中 82 条有材料） |
| `items.json` | 物品名 + 制作材料（供科技匹配用） | 311（160 条有配方） |

命中时机器人会把这些当成事实喂给模型，没命中就不给（照样说"记不清"）。
缓存目录是 `data/raw_extra/`。

> 科技树的数据来自 **palworlddb.com**，因为 paldb.cn 的科技页是前端渲染的、抓不到。
> 该站 robots 的 content signals 是 `search=yes, ai-train=no, use=reference`：
> 我们只做"查资料"式的引用（`use=reference`），**不做任何训练**，也不碰它的 API。
> 如果你不想用这个来源，删掉 `data/tech.json` 即可，机器人会自动退回"记不清"。

### 配队参考（1.0）

`data/teams.json` 是**手工整理**的配队数据，不是抓取的原文。主要来源是 B 站 up 主
13haonan / Ultima-015 的《全毕业配队目录》一图流（13 张图），补充了 17173 的两篇 1.0 攻略。

内容：

- **总则**：常规配队 = 双C + 波鲁杰克斯 + 织夜鹿 + 克制增伤帕鲁；主C 词条固定三件套 + 第四件二选一；
- **按属性的主C**：火/冰/暗/龙/土/电/水/草/无，每系 2~4 只；
- **26 只帕鲁的毕业方案**：词条、主动技能、适用场景（打哪个 boss、要不要换技能）；
- **四条通用提醒**：无系没克制、草系偏弱、龙系技能弱、脱手技能能叠伤害。

结构：

```json
{
  "rules": ["常规配队：双C + 波鲁杰克斯 + 织夜鹿 + 克制增伤帕鲁"],
  "elements": { "火": ["狱熙龙", "流焰龙", "丹烽"] },
  "builds": [{
    "pal": "覆海龙", "element": "龙/水",
    "traits": ["湖之主", "海皇", "沉着冷静", "不死之身"],
    "skills": ["潮涌迸发", "瀑流击", "旋涡新星"],
    "note": "双属伤词条+优秀伙伴技能，适合打高难荷鲁斯"
  }],
  "tips": ["..."]
}
```

命中规则：问「某只帕鲁怎么配/词条/技能」→ 给它的毕业方案；问「X系主C」→ 给该系名单；
问「怎么配队」→ 给总则。问别的不会注入。**直接编辑这个文件**就能更新建议。

### 配队问题的处理顺序（检索优先）

配队这类"需要从数据里组合"的问题，不让模型自由发挥，而是先查再答：

```
识别意图（"雷系配队" / "帮我配个队"）
  → 选出主C（按攻击力，属性对得上）
  → 按"对这只主C的增益"给其余帕鲁打分排序（bot/partner.py 的 synergy）
  → 把候选名单 + 每条的理由和分数交给模型
  → 模型只负责挑人和措辞
  → 发送前再校验一遍名字（bot/guard.py 兜底）
```

**关键战斗机制**（配队逻辑的依据）：帕鲁同时只能召唤一只，只有主C出场打伤害；
其他位置的帕鲁留在队伍里，靠伙伴技能被动生效，不需要召唤出来。
所以队里不存在"召唤个肉盾扛伤"，防守靠被动减伤/回血。
因此：

- 没有"前排"这个概念，只有**主C**和**备用主C**；
- 其余位置只看一件事：**它的被动能不能加成出场的那只主C**（与它自己什么属性无关）；
- 坐骑单独算，骑乘才生效。

增益评分 = 类别基础分 × 强度（描述里的百分比）× 属性是否对得上：

| 类别 | 基础分 | 说明 |
| --- | --- | --- |
| 克制增伤 | 3.0 | 且"以X属性攻击"要跟主C对得上，对不上直接 0 |
| 攻击增益 | 3.0 | 只加玩家自己的 -1；"掉血换攻"会标注代价 |
| 异常增伤 | 2.5 | 对异常状态敌人增伤 |
| 治疗 | 2.0 | 回血/复活 |
| 防御增益 | 1.5 | 队伍防御 |
| 减伤抗性 | 1.0 | 属性减伤 |

实测「暗系配队」会给出 `织夜鹿（全队攻击+80%，掉血换攻）/ 极道蛙（暗系克制增伤）/
兜兜灵（异常增伤）` 这样的排序，而不是随机塞两个名字。

候选会被"数据可信度"过滤：属性是「未知」或数值明显是占位（站点没填完的帕鲁）不参与推荐。

### 伙伴技能分类

`bot/partner.py` 把 299 只帕鲁的伙伴技能分成 21 类，结果落在 `data/partner_skills.json`：

| 分类 | 数量 | 说明 |
| --- | --- | --- |
| 坐骑 | 68 | 骑乘赶路/飞行 |
| 攻击增益 | 59 | 队伍或玩家的攻击力提升 |
| 防御增益 | 19 | 队伍防御力提升 |
| 掉落加成 | 15 | 刷素材用 |
| 减伤抗性 | 13 | 某属性伤害减免 |
| 主动攻击技 | 13 | 放出来打一段 |
| 牧场产出 | 12 | 放牧场产蛋/产毛 |
| 克制增伤 | 8 | **队伍打被克制属性时伤害提升**（配队最值钱） |
| 治疗 | 8 | 回血/复活 |
| 异常增伤 | 7 | 对处于异常状态的敌人伤害提升 |
| …其余 11 类 | | 捕获辅助、协助战斗、滑翔辅助、潜行、控制、化身装备、负重载运、工作加成、探索探测、骑乘采集、移动探索 |

只有 **攻击增益 / 克制增伤 / 防御增益 / 治疗** 能顶辅助位；坐骑、掉落、牧场这些单独归类，
不会被当成"辅助"塞进队伍。

**属性限定**也解析出来了：很多技能只加"某属性帕鲁"的攻击，
比如米露菲只加成无属性、伏特喵只加成雷属性。配队时会标成
`啼卡尔〔暗影睿智·攻击增益·限暗系〕`，并**按主C属性过滤**——
给暗系队推荐米露菲（限无系）这种空占位的情况不会再出现。

### 伙伴技能的等级数值

伙伴技能有 1~5 级，官网只给**一个区间**（如 `(15~30)%`），下限是 1 级、上限是 5 级，
**不提供逐级表**——paldb.cn 的帕鲁页和 `/partner-skills` 页都没有 Lv.1~Lv.5 的明细。

所以按约定：**推荐时一律按 5 级（区间上限）做对比**。
`data/partner_skills.json` 里每条都存了 `lv1` / `lv5` 两个数：

```json
{ "name": "米露菲", "role": "攻击增益", "lv1": 15, "lv5": 30 }
```

两个容易踩的坑，已经处理：

1. **只取描述里第一处百分比**。艾小兔的描述有两组数：
   `克制的属性时伤害提升(25~40)%` 和 `工作效率提升(200~400)%`，
   取错了会把战斗增益夸大成 400%。
2. **区间取上限**（`(40~80)%` → 80），不是下限。

输出里会标成 `织夜鹿〔混沌的祝福·全队攻击+80%（5级）（掉血换攻）〕`。

### 一条技能可以有多个效果

伙伴技能不一定只有一种作用。典型例子是艾小兔：

```
若它在队伍中，玩家和帕鲁以草属性攻击克制的属性时伤害提升(25~40)%。
艾小兔在武器制作台或武器工厂等处工作时，工作效率将会提升(200~400)%。
```

一句话里其实有两条独立效果：**队伍克制增伤 25~40%** 和 **据点工作效率 200~400%**。

所以解析是**按句拆分**的，每条效果单独记录角色、作用对象、属性限定和 1/5 级数值，
存在 `data/partner_skills.json` 的 `effects` 数组里（299 只里有 98 只是多效果，共 383 条）。

用途区分：

- **问某只帕鲁**（"艾小兔有什么增益"）→ 两条效果都报；
- **配队参考**（"暗系配队"）→ **只用战斗类效果**，据点工作/牧场产出这类一律不参与，
  避免拿"工作效率+400%"去凑辅助位。

注意：同一句里第二组百分比不能混用。取错了会把艾小兔的战斗增益算成 400%，
实际战斗收益只有 40%，所以每条效果只读**它自己那句**里的第一个区间。

### 属性克制

`data/elements.json` 存克制链，`bot/elements.py` 负责查表和算倍率：

```
火克草、冰   草克地   地克雷   雷克水   水克火
冰克龙       龙克暗   暗克无
克制 ×2，被克 ×0.5，其余 ×1；双属性连乘，最高 ×4
```

它做三件事：

1. **回答属性问题**：问「雷系怕什么」→ 地系；问「火克什么」→ 草、冰；问「双属性怎么算」→ 给出连乘规则。
2. **配队时自动换属性**：问「打雷系 boss 配队」，会先用克制表算出该用**地系**，再按地系筛候选，
   而不是直接按"雷系"给一队雷系（那样是去打自己）。
3. **同系约束**：限定属性时，主C/前排/辅助都只从该系里挑，避免模型把别系辅助混进来。

> 注意「流焰龙」这类双属性帕鲁（火 + 地）会被算作地系，这是数据本身如此，不是误判。

### 还差一块：配种公式

`/breeding` 页面只有 50KB、不含任何帕鲁名，配种数据同样是前端算的，走接口。
paldb.cn 的 robots 明确 `Disallow: /api/`，所以不做。遇到配种问题，小鱼会说记不清、让人去计算器查。


---

## 换人设 / 调语气

改 `persona.md` 就行，改完重启 `run.py`，不用动代码。现在这版是按插件里的**活人版**
（`src/persona-v2-live.md`）改的：保留了「先像真人，再谈人设」的原则、10 条说话铁律、
性格、雷点、AI 味黑名单和示例；只做了游戏场景必要的压缩——把「分条发」改成「挑重点先说」，
加了「公屏像群友」和「只聊帕鲁」两节，去掉了记忆系统和工具说明。

**想省 token 换精简版**：`persona-lite.md` 是同一人设的压缩版（约 400 字，成本约为活人版的一半，
性格和雷点都在）。在 `config.toml` 里改一行即可切换：

```toml
persona_file = "persona-lite.md"
```

`config.toml` 的 `[reply].prefix` 控制游戏里显示的前缀（默认 `【大肥鱼】`，设成空字符串就不加）。

> 提醒一句：插件里「大肥鱼」是她的**雷点称呼**，不是她的名字。你要是希望游戏里她自称大肥鱼，
> 得改 `persona.md` 里「绝不承认胖」和「雷点」两段，以及 `config.toml` 里 `fatfish` 那条预设。
>
> 本仓库当前是**刻意不一致**的：公告签名用 `【大肥鱼】`，而人设里她自称小鱼、被叫大肥鱼会炸毛。
> 所以你会看到「【大肥鱼】才不是大肥鱼！是小鲸鱼！」这种自相矛盾的画面——这是选定的效果，不是 bug。
> 想改成一致，按上面那段改人设 + `fatfish` 预设即可。

---

## 配置速查

| 配置 | 作用 | 建议 |
| --- | --- | --- |
| `server.mode` | 聊天从哪来 | Windows 服填 `log` |
| `deepseek.model` | 用哪个模型 | `deepseek-v4-pro`（更强）/ `deepseek-flash`（更省） |
| `deepseek.thinking` | 推理模型是否思考 | 游戏里必须 `false`，否则正文会是空的 |
| `server.log_path` | UE4SS.log 路径 | 改成你的真实路径 |
| `reply.transport` | 回复怎么发 | Windows 服填 `rest` |
| `deepseek.history_turns` | 每人记几轮上下文 | `3`；省钱改 `0` |
| `deepseek.max_tokens` | 单次回复上限 | `160`，够两句话 |
| `deepseek.temperature` | 人设活泼度 | `1.15`，想更稳改 `0.9` |
| `trigger.ai_keywords` | 触发词 | 越少越省 |
| `trigger.command_prefix` | 指令前缀 | 想极省就填 `"问:"` |
| `limits.max_reply_chars` | 游戏内单条长度硬上限 | `120`（只防跑飞，不卡日常长度） |
| `reply.target` | 全服公告 / 只回本人 | 只有 Palladium 支持 `player` |
| `persona_file` | 用哪份人设 | 默认 `persona.md`（活人版） |
| `memory.enabled` | 是否记住当天对话 | 默认开 |
| `memory.max_players` | 最多记多少人 | `50`，超了淘汰最早的 |
| `clock.enabled` | 是否整点/半点报时 | 默认开 |
| `clock.interval_minutes` | 报时间隔 | `30` = 整点和半点 |
| `clock.templates` | 报时文案 | 用 `{time}` `{period}` 占位，按时段轮换 |

---

## 报时

每 30 分钟（整点和半点）在聊天框播一条，用**独立的 `【报时】` 前缀**跟普通回复区分开：

```
【报时】09:30 ● 半点了 起来动动 咕噜
【报时】10:00 ● 正好整点 喝口水吧
```

- **不花 token**：走本地模板，不调模型（报时让模型现编既慢又可能把时间说错）；
- 模板在 `[clock].templates` 里改，`{time}` 换时间、`{period}` 换「整点/半点」，按时段轮换；
- 错过超过 2 分钟就不补发，避免断线重连后一次刷出好几条过时时间；
- 想关：`[clock].enabled = false`。

> 如果你看到特殊符号变成方块，把模板里的 `●` 换成普通字符即可——帕鲁的聊天字体对符号支持有限。

---

## 当天记忆

小鱼会记住**今天**谁跟她说过什么，存在 `data/memory.json`：

- **跨重启保留**：机器人重启、服务器重启，当天的对话还在；
- **跨天清空**：日期一变就自动重置，不用手动删（"每天第一次启动重置"就是这么实现的）；
- 每人记几轮由 `deepseek.history_turns` 控制（默认 3 轮 = 6 条消息），设 `0` 等于关闭；
- 最多记 `memory.max_players` 个人，超了淘汰最早的。

想立刻清空：删掉 `data/memory.json`。想彻底关掉：`[memory].enabled = false`。

注意：记忆是按**玩家名**存的（日志里那行 `[PALBOT] 名字`），玩家改名就相当于换了个人。

---

## 常见问题

**游戏里看不到回复**
`target = "announce"` 走的是系统公告，不会出现在普通聊天流里，看屏幕上方/公告区。
如果是 `player.message`，检查 token 是否有 `write` 权限、以及 `bridge_url` 从你这台机器能不能访问。

**机器人一直不说话**
看控制台日志里的 `→ 原因`：
`no_trigger` 说明没命中关键词（把玩家原话和 `ai_keywords` 对一下）；
`cooldown` / `rate_limited` / `daily_budget_exhausted` 是限额挡住了，正常；
`duplicate` 是同一句话重复了。

**UE4SS.log 里没有 `[PALBOT]` 开头的行**
说明聊天钩子名和你的游戏版本对不上。把日志里所有 `[PALBOT]` 行（含 `miss` / `WARN`）发我，
我按实际函数名改 `ue4ss/Mods/PalChatRelay/Scripts/main.lua` 里的 `CANDIDATES` 列表。
在那之前机器人不会说话，这是正常的——它读不到东西。

**UE4SS 装上后服务器崩溃**
先只留 UE4SS 本体跑一次，确认不是版本问题；帕鲁每个大版本更新后 UE4SS 都要跟着换。
`PalChatRelay` 只做 `print`，不写游戏参数，正常情况下不会引起崩溃。

**回复太长被截断**
`limits.max_reply_chars` 只是防跑飞的硬上限（默认 120），**不参与日常长度控制**。
长度由 `persona.md` 和系统指令里的自然语言要求决定：简单问题十几个字、复杂点的问题
最多到一百字，模型自己判断，不卡死。

**想加更多预设话**
在 `[[preset.rules]]` 下面照抄一段，`keywords` 命中任意一个就用 `replies` 里随机一句。

**机器人会不会回答自己发的公告？**
不会。广播出去的公告也会被聊天钩子捕获，但内容以 `[reply].prefix`（默认 `【大肥鱼】`）开头，
路由器直接丢弃（日志里显示 `self_prefix`）。你改前缀它会自动跟着改，不需要额外配置。
UE4SS 那边还会额外过滤掉 `Sender` 为 `SYSTEM` 的系统消息，双保险。

---

## 验证状态（请先看这个）

- 判定逻辑有 `tests/test_router.py` 覆盖，其中包含直接加载**出厂 `config.toml`** 的路由检查
  （"大肥鱼在吗"必须走预设、"小鱼 …"必须走 AI），所以配置写错会被测出来。
- 但整套**没有在真实服务器上跑过**：写它的时候开发环境的终端起不来，没法执行 Python。
  第一次跑如果报错，把控制台输出发我，我按实际报错改。
- `main.lua` 里的六个候选钩子名是社区常见写法，**没在你的游戏版本上验证过**。
  第一次一定要先看 `UE4SS.log` 的 `[PALBOT]` 行，对不上我改。
- Palladium 的字段（`player.chat` 的 `message`、`server.announce` 的 `message`）取自其官方 bridge 文档。
