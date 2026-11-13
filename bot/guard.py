"""生成后的名字校验。

模型在没有资料支撑时，会顺着"帕鲁应该叫这种名字"编出像模像样的假名字
（实测编过 寒空蝠 / 霜角鹿 / 凋零蔷薇）。提示词只能降低概率，不能杜绝，
所以这里在发送前做一次硬校验：

  回答里凡是长得像帕鲁名（以常见种族字结尾）的词，
  都要能在资料库的 299 个名字里找到，否则整条回复作废。

宁可少答一句，也不让玩家按着一个不存在的名字去找半天。
"""
from __future__ import annotations

import re

# 帕鲁名字常见的结尾字，用来判断"这看起来像个帕鲁名"
SUFFIXES = (
    "蝠鹿龙兽鸟猫犬狐兔龟蛇蛾鲸猿马牛羊鸡猪蝶蜂蟹虾鱼鹰狮狼豹熊象犀"
    "蝶蝶貂鼠鸦蝎蛛螳蝠"
)

_PATTERN = re.compile(r"[\u4e00-\u9fa5]{1,3}[" + "".join(dict.fromkeys(SUFFIXES)) + r"]")

# 她自己、以及常用普通词，不算帕鲁名
_ALLOW = {
    "大肥鱼",
    "小鱼",
    "肥鱼",
    "前排",
    "后排",
    "输出",
    "奶妈",
    "坐骑",
    "词条",
    "技能",
}


# 名字前面常粘上的连接词/虚词，校验前先剥掉
# （"用寒空蝠" → "寒空蝠"，"灵曦龙本身龙属性" → "龙" → 长度不足，放过）
_LEADING = (
    "或和用是带配上只的再加跟与个把再换拿本身属性了就在有这那些傻笨臭死"
    "你我他她它谁别太真很挺个嘛啊呀吧"
)

# 剥完之后短于这个长度就当作普通词，不判为帕鲁名
# （真实帕鲁名最短是两个字，两个字又太容易撞普通词，所以取 3）
_MIN_LEN = 3


def unknown_names(reply: str, names: list[str]) -> list[str]:
    """返回回答里"看起来像帕鲁名、但资料库里没有"的词。"""
    if not reply or not names:
        return []
    pool = [name for name in names if isinstance(name, str) and name]
    suspects: list[str] = []
    for match in _PATTERN.finditer(reply):
        word = match.group(0)
        while len(word) > _MIN_LEN - 1 and word[0] in _LEADING:
            word = word[1:]
        if len(word) < _MIN_LEN or word in _ALLOW or word in suspects:
            continue
        # 只要能在任意一个真实名字里找到，就算合法（兼容简称）
        if any(word in name or name in word for name in pool):
            continue
        suspects.append(word)
    return suspects
