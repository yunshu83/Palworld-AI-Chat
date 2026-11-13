--[[
PalChatRelay —— 把服务器收到的游戏内聊天打印进 UE4SS.log，供外部机器人（Python）读取。

原理：只读不写。这里不修改任何游戏参数，也不调用发送接口，
      所以不会触发 UE4SS 在写聊天参数时的崩溃问题。
输出格式：  [PALBOT] 玩家名<TAB>聊天内容
外部程序按这个前缀过滤 UE4SS.log 即可。

装法：把整个 PalChatRelay 文件夹放到
      [服务器]\Pal\Binaries\Win64\ue4ss\Mods\PalChatRelay\
      并在 mods.txt 里加一行：PalChatRelay : 1

实测记录（UE4SS v3.0.1 Beta + 帕鲁专用服 v1.0.5，2026-11）：
  * 聊天入口是 /Script/Pal.PalGameStateInGame:BroadcastChatMessage；
    PlayerController 上的 ServerSendChatMessage 等名字全部不存在。
  * 回调参数不是 Lua 值，而是 UE4SS 的 RemoteUnrealParam / LocalUnrealParam
    包装对象，必须用 :get() 解包，直接 tostring 只会得到地址。
]]--

local MARKER = "[PALBOT]"

local CANDIDATES = {
    "/Script/Pal.PalGameStateInGame:BroadcastChatMessage",
    "/Script/Pal.PalGameStateInGame:SendChatMessage",
    "/Script/Pal.PalPlayerController:ServerSendChatMessage",
    "/Script/Pal.PalPlayerController:Server_SendChatMessage",
    "/Script/Pal.PalPlayerController:SendChatMessage",
    "/Script/Pal.PalChatManager:SendChatMessage",
}

-- 启动时把相关类里名字带 chat 的函数列出来，换版本后定位用；平时关掉
local DUMP_CHAT_FUNCTIONS = false
local DUMP_CLASSES = {
    "/Script/Pal.PalGameStateInGame",
    "/Script/Pal.PalPlayerController",
    "/Script/Pal.PalPlayerState",
}

-- 调试开关：打开后每条聊天会多打一行参数详情。排查换版本问题时再开。
local DEBUG_INVOCATIONS = false

-- UE4SS 的 Lua print 不会自动换行，不补的话下一条日志会直接粘在这一行后面
local function log(text)
    print(text .. "\n")
end

local function truncate(text, limit)
    if type(text) ~= "string" then
        return text
    end
    if #text > limit then
        return string.sub(text, 1, limit) .. "..."
    end
    return text
end

local function raw_try(fn, ...)
    local ok, value = pcall(fn, ...)
    if ok and value ~= nil then
        local text = tostring(value)
        if #text > 0 then
            return text
        end
    end
    return nil
end

local function looks_like_wrapper(text)
    if type(text) ~= "string" then
        return false
    end
    if string.find(text, "UnrealParam:", 1, true) ~= nil then
        return true
    end
    if string.find(text, "FString:", 1, true) ~= nil then
        return true
    end
    if string.find(text, "TrivialObject:", 1, true) ~= nil then
        return true
    end
    return false
end

-- 把 RemoteUnrealParam / LocalUnrealParam 一层层解成真正的 Lua 值
local function unwrap(value)
    for _ = 1, 4 do
        if type(value) ~= "userdata" then
            return value
        end
        local ok, inner = pcall(function()
            return value:get()
        end)
        if not ok or inner == nil then
            return value
        end
        value = inner
    end
    return value
end

local function describe_value(value)
    local kind = type(value)
    if kind == "string" then
        return string.format("string(%s)", truncate(value, 80))
    end

    local parts = { kind }
    local plain = raw_try(tostring, value)
    if plain then
        parts[#parts + 1] = "tostring=" .. truncate(plain, 60)
    end
    local inner = raw_try(function()
        return value:get()
    end)
    if inner then
        parts[#parts + 1] = "get=" .. truncate(inner, 80)
    end
    return table.concat(parts, " ")
end

local function describe_args(...)
    local parts = {}
    for index = 1, select("#", ...) do
        parts[#parts + 1] = string.format("%d=%s", index, describe_value((select(index, ...))))
    end
    return table.concat(parts, " | ")
end

local function clean(value)
    if type(value) ~= "string" then
        return ""
    end
    return (value:gsub("[\t\r\n]+", " "))
end

local function player_name(self)
    local name = "玩家"
    pcall(function()
        local resolved = clean(tostring(self:GetPlayerName()))
        if #resolved > 0 and not looks_like_wrapper(resolved) then
            name = resolved
        end
    end)
    return name
end

local function extract_message(...)
    for index = 2, select("#", ...) do
        local value = unwrap((select(index, ...)))
        if type(value) == "string" then
            local text = clean(value)
            if #text > 0 and not looks_like_wrapper(text) then
                return text
            end
        end
    end
    return nil
end

local PROBE_FIELDS = {
    "Message", "message", "Text", "text", "Content", "content",
    "Sender", "SenderName", "PlayerName", "ChatMessage", "Msg", "Body", "MessageType",
}

local function probe_struct(param)
    local inner = nil
    local ok, value = pcall(function()
        return param:get()
    end)
    if ok then
        inner = value
    end

    if type(inner) == "userdata" then
        local label = raw_try(function()
            return inner:GetFullName()
        end) or "?"
        log(string.format("%s PROBE inner=%s", MARKER, truncate(label, 80)))

        local dumped = pcall(function()
            inner:ForEachProperty(function(prop)
                local prop_name = raw_try(function()
                    return prop:GetFullName()
                end) or "?"
                log(string.format("%s PROP %s", MARKER, truncate(prop_name, 100)))
            end)
        end)
        if not dumped then
            log(string.format("%s PROBE ForEachProperty 不可用", MARKER))
        end
    end

    for _, key in ipairs(PROBE_FIELDS) do
        local direct = raw_try(function()
            return param[key]
        end)
        if direct and not looks_like_wrapper(direct) then
            log(string.format("%s FIELD param.%s = %s", MARKER, key, truncate(direct, 60)))
        end

        if type(inner) == "userdata" then
            local via_inner = raw_try(function()
                return inner[key]
            end)
            if via_inner and not looks_like_wrapper(via_inner) then
                log(string.format("%s FIELD inner.%s = %s", MARKER, key, truncate(via_inner, 60)))
            end

            local via_getter = raw_try(function()
                return inner:GetPropertyValue(key)
            end)
            if via_getter and not looks_like_wrapper(via_getter) then
                log(string.format("%s FIELD GetPropertyValue(%s) = %s", MARKER, key, truncate(via_getter, 60)))
            end
        end
    end
end

local function probe_actor(param)
    local actor = nil
    local ok, value = pcall(function()
        return param:get()
    end)
    if ok then
        actor = value
    end
    if type(actor) ~= "userdata" then
        return
    end

    log(string.format("%s ACTOR %s", MARKER, truncate(raw_try(function()
        return actor:GetFullName()
    end) or "?", 100)))

    local state = nil
    pcall(function()
        state = actor:GetPlayerState()
    end)
    if state == nil then
        pcall(function()
            state = actor.PlayerState
        end)
    end
    if state ~= nil then
        local name = raw_try(function()
            return state:GetPlayerName()
        end)
        if name then
            log(string.format("%s ACTOR player=%s", MARKER, truncate(name, 60)))
        end
    end
end

-- 把 FString 包装对象转成 Lua 字符串：不同 UE4SS 版本支持的取法不一样，依次尝试
local FSTRING_GETTERS = {
    function(obj)
        return obj:ToString()
    end,
    function(obj)
        return obj:get()
    end,
    function(obj)
        return obj:Get()
    end,
    function(obj)
        return obj.Value
    end,
    function(obj)
        return obj.Data
    end,
}

local function read_fstring(obj)
    if obj == nil then
        return nil
    end
    if type(obj) == "string" then
        local text = clean(obj)
        if #text > 0 and not looks_like_wrapper(text) then
            return text
        end
        return nil
    end
    for _, getter in ipairs(FSTRING_GETTERS) do
        local text = raw_try(getter, obj)
        if text and #text > 0 and not looks_like_wrapper(text) then
            return clean(text)
        end
    end
    return nil
end

-- FPalChatMessage 的实际结构（实测）：
--   StrProperty Sender（发送者名）、StrProperty Message（聊天内容）
local function extract_from_struct(param)
    local inner = nil
    local ok = pcall(function()
        inner = param:get()
    end)
    if not ok or inner == nil then
        return nil, nil
    end

    local message = raw_try(function()
        return read_fstring(inner.Message)
    end)
    local sender = raw_try(function()
        return read_fstring(inner.Sender)
    end)
    return message, sender
end

local function on_chat(...)
    if DEBUG_INVOCATIONS then
        log(string.format("%s fired n=%d [%s]", MARKER, select("#", ...), describe_args(...)))
    end

    -- 优先从 FPalChatMessage 结构体取，那里同时有发送者名和内容
    local message, sender = extract_from_struct((select(2, ...)))
    if not message then
        message = extract_message(...)
    end
    if not message then
        return
    end

    local name = sender
    if not name or #name == 0 then
        name = player_name(select(1, ...))
    end

    -- 系统公告（包括机器人自己发的）也会走这个广播，记下来只会造成自问自答
    if string.upper(name) == "SYSTEM" or name == "系统" then
        return
    end

    log(string.format("%s %s\t%s", MARKER, name, message))
end

local function dump_class(path, pattern)
    local class = nil
    local found = pcall(function()
        class = StaticFindObject(path)
    end)
    if not found or class == nil then
        log(string.format("%s DUMP %s : 类不存在", MARKER, path))
        return 0
    end

    local count = 0
    local ok = pcall(function()
        class:ForEachFunction(function(a, b)
            local fn = a
            if type(a) == "number" then
                fn = b
            end
            if fn == nil then
                return
            end
            local read_ok, full = pcall(function()
                return tostring(fn:GetFullName())
            end)
            if read_ok and full and string.find(string.lower(full), pattern) then
                count = count + 1
                log(string.format("%s CAND %s", MARKER, full))
            end
        end)
    end)
    if not ok then
        log(string.format("%s DUMP %s : ForEachFunction 不可用", MARKER, path))
        return -1
    end
    log(string.format("%s DUMP %s : %d 个含 %s", MARKER, path, count, pattern))
    return count
end

local installed = 0
for _, path in ipairs(CANDIDATES) do
    local ok = pcall(function()
        RegisterHook(path, on_chat)
    end)
    if ok then
        installed = installed + 1
        log(string.format("%s hooked %s", MARKER, path))
    else
        log(string.format("%s miss   %s", MARKER, path))
    end
end

if DUMP_CHAT_FUNCTIONS then
    for _, path in ipairs(DUMP_CLASSES) do
        dump_class(path, "chat")
    end
end

log(string.format("%s ready, %d hook(s)", MARKER, installed))
