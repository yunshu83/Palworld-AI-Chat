"""伙伴技能分类。

为什么单独做：配队时"辅助位"必须真能帮到主C或保命，
而帕鲁的伙伴技能有十几种作用，光靠关键词"提升"会把骑乘加速、
掉落加成都算成辅助（实测就把碧月龙、精灵龙塞进了辅助位）。

分类只看技能描述文本，规则按"从具体到宽泛"的顺序匹配。
"""
from __future__ import annotations

import re

# 能顶上"辅助位"的分类：对队伍或玩家有实际增益的分类
SUPPORT_ROLES = ("攻击增益", "克制增伤", "防御增益", "治疗")

# 只服务骑手自己的（占一个位但不加队伍输出）
RIDE_ROLES = ("坐骑", "骑乘采集", "滑翔辅助")

ROLES = (
    "治疗",
    "克制增伤",
    "异常增伤",
    "攻击增益",
    "防御增益",
    "减伤抗性",
    "掉落加成",
    "捕获辅助",
    "协助战斗",
    "滑翔辅助",
    "骑乘采集",
    "坐骑",
    "移动探索",
    "潜行",
    "控制",
    "化身装备",
    "主动攻击技",
    "负重载运",
    "牧场产出",
    "工作加成",
    "探索探测",
    "其他",
)

# 判断"是否作用于队伍"要用严格的措辞：
# "若它在队伍中"只是位置说明，不是作用范围（很多武器增伤也这么开头）
_TEAM = re.compile(r"队伍内的帕鲁|玩家和帕鲁|并肩作战|一同攻击|我方|其他据点帕鲁")
_ELEMENTS = "火冰暗龙地雷水草无"


def target_element(desc: str) -> str:
    """技能加成限定在哪个属性上；不限定时返回空串。

    很多辅助只加"某属性帕鲁"的攻击，配错属性就是空占位置。
    """
    text = desc or ""
    match = re.search(r"([%s])属性帕鲁" % _ELEMENTS, text)
    return match.group(1) if match else ""


def target_scope(desc: str) -> str:
    """加成对象：队伍 / 玩家 / 自己。"""
    text = desc or ""
    if _TEAM.search(text):
        return "队伍"
    # "若它在队伍中，X属性帕鲁的……" 也是队伍向（很多辅助这么写）；
    # 但"若它在队伍中，武器的弹匣……"是玩家向，靠后半句有没有"帕鲁/属性"区分
    if "队伍中" in text:
        tail = text.split("队伍中", 1)[1][:60]
        if "帕鲁" in tail or "属性" in tail:
            return "队伍"
    if re.search(r"玩家|武器|弹匣|近战|弓箭|枪械", text):
        return "玩家"
    return "自己"


def classify_clause(desc: str) -> str:
    """返回单句伙伴技能的分类。"""
    text = (desc or "").strip()
    if not text:
        return "其他"

    team = _TEAM.search(text) is not None

    # 1. 治疗 / 复活
    if re.search(r"(恢复|回复)[^。]{0,14}(生命|HP)", text) or "复活" in text:
        return "治疗"

    # 2. 克制增伤：队伍打"被自己属性克制"的目标时伤害提升
    #    这类在配队里最值钱，先判，避免被别的关键词抢走
    if re.search(r"克制的属性时伤害[^。]{0,6}(提升|增加)", text):
        return "克制增伤"
    # 2.5 异常增伤：对处于某种异常状态的敌人伤害提升
    if re.search(r"对[^。]{0,10}状态的敌人[^。]{0,14}伤害[^。]{0,8}(提升|增加)", text):
        return "异常增伤"

    # 3. 攻击增益：队伍攻击力提升，或玩家自己的攻击/武器伤害提升
    if re.search(r"攻击力[^。]{0,16}(提升|增加)", text):
        return "攻击增益"
    if re.search(r"(近战武器|弓箭|枪械|远程武器|武器)[^。]{0,14}(伤害|攻击速度|蓄力速度|装弹)[^。]{0,8}(提升|增加)", text):
        return "攻击增益"

    # 4. 防御 / 减伤 / 免疫
    if re.search(r"防御力[^。]{0,30}(提升|增加)", text):
        return "防御增益"
    if re.search(r"(生成|提供)[^。]{0,10}护盾", text):
        return "防御增益"
    if re.search(r"(受到|承受)[^。]{0,10}伤害[^。]{0,8}(减少|降低|减轻)", text):
        return "减伤抗性"
    if re.search(r"不会陷入[^。]{0,10}状态", text) or re.search(r"不受[^。]{0,12}影响", text):
        return "减伤抗性"

    # 5. 收益类
    if re.search(r"掉落道具[^。]{0,12}(增加|提升)", text):
        return "掉落加成"
    if re.search(r"(垂钓|打捞)[^。]{0,10}(获得|道具)[^。]{0,10}(增加|提升)", text):
        return "掉落加成"
    if re.search(r"捕获(概率|计量槽|率)", text):
        return "捕获辅助"

    # 6. 移动类
    if "滑翔" in text:
        return "滑翔辅助"
    if "骑乘" in text and re.search(r"(效率|破坏岩石|破坏树木)[^。]{0,8}(提升|增加)", text):
        return "骑乘采集"
    if "骑乘" in text or "可骑在它的背上" in text or re.search(r"(空中|水上)移动|飞行时", text):
        return "坐骑"
    if re.search(r"(攀爬|游泳|潜水|滑铲|移动速度)[^。]{0,12}(提升|增加|变快)", text):
        return "移动探索"

    # 6.5 潜行 / 控制
    if re.search(r"透明|隐去身形|不被[^。]{0,6}发现|不容易被[^。]{0,6}发现", text):
        return "潜行"
    if re.search(r"(陷入|附加)[^。]{0,12}(冻结|中毒|点燃|感电|睡眠|眩晕|异常状态值|缠绕)", text):
        return "控制"

    # 7. 化身 / 主动技
    if re.search(r"化身为|装备在玩家身上|装备在手上|装备火箭发射器", text):
        return "化身装备"
    if re.search(r"发动后[^。]{0,40}(冲向敌人|扫射|射击|爆炸|攻击[^。]{0,8}(目标|敌人))", text):
        return "主动攻击技"
    if re.search(r"破坏(矿石|岩石|树木)[^。]{0,10}效率[^。]{0,8}(提升|增加)", text):
        return "骑乘采集"

    # 8. 负重
    if re.search(r"负重|载运|行李|重量[^。]{0,8}(减轻|降低)", text):
        return "负重载运"

    # 9. 牧场
    if re.search(r"家畜牧场|产下|牧场", text):
        return "牧场产出"

    # 10. 协同战斗
    if re.search(r"配合玩家|一同攻击|追击|一起攻击|出现在玩家身边", text):
        return "协助战斗"

    # 11. 据点工作 / 探测
    if re.search(r"(工作速度|工作适应性|工作效率)[^。]{0,14}(提升|增加|\+1)", text):
        return "工作加成"
    if re.search(r"作物[^。]{0,12}(生长|收获|收获量)[^。]{0,8}(加速|提升|增加)", text):
        return "工作加成"
    if re.search(r"击倒[^。]{0,12}(获得量|掉落)[^。]{0,8}(提升|增加)", text):
        return "掉落加成"
    if re.search(r"弱点部位|击中弱点", text):
        return "攻击增益"
    if "探测" in text:
        return "探索探测"

    return "其他"


# 一条伙伴技能可能同时有多条效果（例如艾小兔：队伍克制增伤 + 据点工作效率）。
# 解析时按句拆开，每条效果单独记录。
_PRIORITY = (
    "治疗",
    "克制增伤",
    "异常增伤",
    "攻击增益",
    "防御增益",
    "减伤抗性",
    "协助战斗",
    "控制",
    "潜行",
    "骑乘采集",
    "坐骑",
    "滑翔辅助",
    "移动探索",
    "化身装备",
    "主动攻击技",
    "掉落加成",
    "捕获辅助",
    "负重载运",
    "牧场产出",
    "工作加成",
    "探索探测",
)

# 只在据点里生效的效果（不影响队伍配队，但要让人知道）
BASE_ROLES = ("工作加成", "牧场产出")


def _sentences(desc: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。；\n]", desc or "") if part.strip()]


def effects(desc: str) -> list[dict]:
    """把一条伙伴技能拆成多条效果。

    返回 [{"role", "scope", "element", "lv1", "lv5", "text"}, ...]，按优先级排序。
    """
    found: dict[tuple, dict] = {}
    for sentence in _sentences(desc):
        role = classify_clause(sentence)
        if role == "其他":
            continue
        lv1, lv5 = level_range(sentence)
        key = (role, target_element(sentence), target_scope(sentence))
        if key in found and found[key]["lv5"] >= lv5:
            continue
        found[key] = {
            "role": role,
            "scope": target_scope(sentence),
            "element": target_element(sentence),
            "lv1": lv1,
            "lv5": lv5,
            "text": sentence,
        }
    return sorted(found.values(), key=lambda item: _PRIORITY.index(item["role"]))


def classify(desc: str) -> str:
    """主分类：多条效果里优先级最高的那条。"""
    found = effects(desc)
    return found[0]["role"] if found else "其他"


_RANGE = re.compile(r"\((\d+)(?:~(\d+))?\)%")


def level_range(desc: str) -> tuple[int, int]:
    """描述里第一处百分比区间 = 伙伴技能 1 级 ~ 5 级的数值。

    只取第一处：后面的数值往往是别的效果（比如艾小兔的工作效率 200~400%），
    混进来会把增益夸大成十倍。
    """
    match = _RANGE.search(desc or "")
    if not match:
        return 0, 0
    low = int(match.group(1))
    high = int(match.group(2) or low)
    return low, high


def max_percent(desc: str) -> int:
    """满级（5 级）数值：取区间上限。官网只给区间，不给逐级表。"""
    return level_range(desc)[1]


# 每类被动对"出场主C"的贡献分
_ROLE_SCORE = {
    "克制增伤": 3.0,
    "异常增伤": 2.5,
    "攻击增益": 3.0,
    "防御增益": 1.5,
    "治疗": 2.0,
    "减伤抗性": 1.0,
}


def _score_effect(effect: dict, element: str) -> tuple[float, str]:
    role = effect["role"]
    score = _ROLE_SCORE.get(role, 0.0)
    if score <= 0:
        return 0.0, ""

    limit = effect["element"]
    if limit and element and limit != element:
        return 0.0, ""  # 只加成别的属性，主C吃不到

    # 克制增伤是"某属性攻击打被克制目标时增伤"，属性对不上就没用
    if role == "克制增伤":
        match = re.search(r"([%s])属性攻击克制" % _ELEMENTS, effect["text"])
        if match and element and match.group(1) != element:
            return 0.0, ""
        return 3.0, f"{match.group(1)}系克制增伤" if match else "克制增伤"

    scope = effect["scope"]
    if scope == "自己":
        return 0.0, ""  # 只对自己生效（骑乘之类），不出场就没用

    pct = effect["lv5"]
    # 强度要参与评分：+1% 和 +40% 不该同分
    score = score * (0.6 + min(pct, 120) / 120.0)
    scope_text = "玩家" if scope == "玩家" else (f"{limit}系" if limit else "全队")

    if role == "攻击增益":
        reason = f"{scope_text}攻击+{pct}%（5级）" if pct else f"{scope_text}攻击提升"
        if scope == "玩家":
            score -= 1.0  # 只加玩家自己的输出，不如加成主C
        if "生命值会逐渐减少" in effect["text"]:
            reason += "（掉血换攻）"  # 织夜鹿这类，要提醒代价
    elif role == "防御增益":
        reason = f"{scope_text}防御+{pct}%（5级）" if pct else f"{scope_text}防御提升"
    elif role == "治疗":
        reason = f"回血{pct}%（5级）" if pct else "回血"
    elif role == "异常增伤":
        reason = "异常状态增伤"
    else:
        reason = role
    return score, reason


def synergy(desc: str, element: str, role: str | None = None) -> tuple[float, str]:
    """给"这只帕鲁的被动对某属性主C有多大用"打分。

    一条技能可能有多条效果，取对这只主C最有利的那条计分。
    返回 (分数, 理由)。分数 0 表示没有实际收益。
    机制：同时只能召唤一只主C，其余帕鲁留在队伍里靠被动生效，
    所以只有"对队伍/玩家生效"且"属性对得上"的加成才算数。
    """
    best: tuple[float, str] = (0.0, "")
    for effect in effects(desc):
        if role is not None and effect["role"] != role:
            continue
        score, reason = _score_effect(effect, element)
        if score > best[0]:
            best = (score, reason)
    return best
