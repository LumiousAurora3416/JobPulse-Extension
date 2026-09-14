"""JobPulse 状态规则 —— 「结果」状态机的唯一真相源（v1.9.0）

为什么单独一个模块：结果列的选项集、过程态/终态划分、卡片按钮映射，原本散落在
agent.py / cards.py / callback_server.py / message_agent.py 四处。任何一处漏改就是
静默故障——v1.8.0 的「更新状态分不清两列」和卡片「面试」按钮失效，根因都是同一类
"同一份事实存在多个副本"。**新增/修改状态值请只改本文件。**

⚠️ 飞书「结果」列的实际选项必须与本文件的 RESULT_OPTIONS 完全一致，否则写入会被
飞书拒绝（FieldConvFail，而且整条记录写入失败，不只是这一列丢值）。
改选项的顺序：**先在飞书网页端改列 → 再改本文件 → 跑 init_match_tables.py 校验**。
"""

# ---- 「结果」列的全部合法值 ----

# 过程态：投递还在流程中（面试不区分一二三面，因为"在面"时还看不出挂在哪轮）
RESULT_PROGRESS = ["待投递", "简历", "测评", "面试"]

# 终态：已有结论（挂要区分到轮次——"挂在哪一轮"是复盘/求职漏斗的关键数据）
RESULT_TERMINAL = ["简历挂", "一面挂", "二面挂", "三面挂", "offer", "无反馈", "放弃"]

RESULT_OPTIONS = RESULT_PROGRESS + RESULT_TERMINAL

# 会被跟进提醒催的过程态：排除「待投递」——还没投，催"跟进"没意义
RESULT_REMINDABLE = ["简历", "测评", "面试"]


def is_terminal(result: str) -> bool:
    """该结果是否已到终态（可以停止跟进）。"""
    return result in RESULT_TERMINAL


def should_remind(result: str) -> bool:
    """该结果是否还需要继续推跟进卡片。"""
    return result in RESULT_REMINDABLE


# ---- 跟进卡片的按钮：按当前结果给出「可能的下一步」 ----
# 这样每颗按钮写入的值必然取自 RESULT_OPTIONS，结构上不可能再写错。
# 「无反馈」「放弃」故意不进按钮——属于事后判断的极少数情况，手动标或跟 bot 说。
CARD_ACTIONS = {
    "简历": [("进面试", "面试"), ("测评", "测评"), ("简历挂", "简历挂")],
    "测评": [("进面试", "面试"), ("简历挂", "简历挂")],
    "面试": [("一面挂", "一面挂"), ("二面挂", "二面挂"), ("三面挂", "三面挂"), ("offer", "offer")],
}


def card_actions_for(result: str):
    """取某结果对应的按钮列表 [(文案, 写入值), ...]；终态/待投递返回空（不发卡片）。"""
    return CARD_ACTIONS.get(result, [])


# ---- 与飞书列的实际选项做一致性校验（供 init_match_tables.py 前置检查） ----

def diff_with_feishu(feishu_options):
    """对比飞书列实际选项与本地定义，返回 (缺失, 多余)。

    缺失 = 代码会写但列里没有 → 写入必失败，必须先补列选项。
    多余 = 列里有但代码未定义 → 大概率是拼写不一致（如全角/半角），也要查。
    """
    missing = [o for o in RESULT_OPTIONS if o not in feishu_options]
    extra = [o for o in feishu_options if o not in RESULT_OPTIONS]
    return missing, extra
