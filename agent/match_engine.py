"""岗位匹配度引擎 — JD + 简历 → 结构化评分报告

契约：docs/match-schema.md（v0.1，单一事实来源，本文实现严格对齐）

流程（一次 LLM 调用）：
  ① 算法预核对层 keyword_check：jieba 分词 + 停用词 + 整词匹配 → 关键词命中信号
  ② LLM 一次调用评分：prompt 喂入 ① 的信号，输出完整评分报告
  ③ 后处理 _post_process：overall_score 按维度加权重算、verdict 强一致、字段钳制/清洗

用法：
  from match_engine import evaluate
  report = evaluate(jd_text, resume_text)
"""

import json
import re

import jieba
import jieba.posseg as pseg

from config import (
    LLM_API_KEY,
    LLM_API_BASE,
    LLM_MODEL,
    MATCH_THRESHOLD,
    MATCH_WEIGHTS,
    MATCH_MAX_JD_CHARS,
    MATCH_MAX_RESUME_CHARS,
)

# 维度顺序（与 match-schema §2 一致）
DIMENSION_ORDER = ["硬性门槛", "技能匹配", "经历相关性"]

# 中文招聘停用词：JD 里的标题/套话/福利词对技能判断无意义，会污染关键词命中率
STOPWORDS = set("""
的 了 和 与 及 等 在 有 是 对 为 能 会 可 需 要 将 并 或 个 中 上 下 于 从 向 由 以 而 其 之
岗位 工作 职位 职责 要求 条件 优先 加分项 能力 经验 相关 以下 需要 负责 参与 熟悉 了解 掌握
具备 具有 能够 善于 热爱 较强 一定 良好 优秀 扎实 熟练 精通 快速 学习 沟通 协作 团队 合作
精神 态度 责任心 执行 抗压 积极 主动 细致 严谨 逻辑 思维 表达 文字 功底 乐观 好奇 自驱
岗位职责 任职要求 岗位要求 工作内容 职位描述 职责描述 任职条件 岗位描述 岗位职责
五险一金 弹性工作 成长空间 福利待遇 带薪年假 零食下午茶 年终奖 氛围好 发展空间 扁平化管理
免费三餐 节日福利 期权 股票 晋升 通道 培训 报销 体检 补贴 补助 津贴 房补 交通 餐补
""".split())


def _extract_keywords(jd_text: str, top_n: int = 15) -> list:
    """从 JD 提取高频关键词（名词/专有名词/英数词，过滤停用词）。

    jieba.posseg 带词性标注：'n'名词 'nr'人名 'ns'地名 'nt'机构 'nz'专名
    'vn'动名词 'eng'英文词。只保留这些类别，剔除通用套话动词（熟悉/负责等，
    由 STOPWORDS 过滤）。按词频取 Top N。
    """
    keep_pos = {"n", "nr", "ns", "nt", "nz", "vn", "eng"}
    counter = {}
    for word, flag in pseg.lcut(jd_text):
        if flag not in keep_pos:
            continue
        if len(word) < 2 or word.isdigit():
            continue
        if word in STOPWORDS:
            continue
        counter[word] = counter.get(word, 0) + 1
    ranked = sorted(counter.items(), key=lambda x: -x[1])
    return [w for w, _ in ranked[:top_n]]


def _keyword_in_resume(keyword: str, resume_text: str) -> bool:
    """整词匹配：英文用整词边界正则防子串误命中（如 Pythonic 不中 Python）；
    中文用子串包含，容忍 JD 与简历分词不一致（如 JD 出"微服务"、简历写"微服务架构"）。
    """
    if re.search(r"[a-zA-Z]", keyword):
        return re.search(
            rf"(?<!\w){re.escape(keyword)}(?!\w)", resume_text, re.IGNORECASE
        ) is not None
    return keyword in resume_text


def keyword_check(jd_text: str, resume_text: str) -> dict:
    """① 算法预核对层（契约 §5）：关键词命中率 + 发散调整。

    定位：只证伪"分数虚高"（命中率低但 LLM 给高分 → 标记复核）；
    不能证伪"分数偏低"（词面不重叠但语义很配是盲区，靠 LLM 语义修正）。
    """
    keywords = _extract_keywords(jd_text)
    if not keywords:
        return {
            "keyword_hit_rate": 0.0,
            "matched_keywords": [],
            "missing_keywords": [],
            "discrepancy": "low",
        }

    matched = [k for k in keywords if _keyword_in_resume(k, resume_text)]
    hit_rate = len(matched) / len(keywords)

    # 发散调整：命中率过低 → LLM 高分有虚高风险，标记提醒复核（借鉴 @resurank）
    if hit_rate < 0.15:
        discrepancy = "high"
    elif hit_rate < 0.35:
        discrepancy = "medium"
    else:
        discrepancy = "low"

    return {
        "keyword_hit_rate": round(hit_rate, 2),
        "matched_keywords": matched,
        "missing_keywords": [k for k in keywords if k not in matched],
        "discrepancy": discrepancy,
    }


# System Prompt —— 严格对齐 match-schema §4.1，末尾附输出 JSON 结构
SYSTEM_PROMPT = """你是一名资深技术面试官和 ATS 简历评估专家。任务是评估「岗位 JD」与「求职简历」的匹配度，输出结构化的可解释评分报告。

【评分框架】
总分 = Σ(维度分 × 权重)，钳制 0-100：
- 硬性门槛 20%：学历 / 专业 / 年限 / 证书是否满足 JD 硬性要求
- 技能匹配 40%：JD 技能清单逐条命中的比例与深度
- 经历相关性 40%：实习 / 项目经历与 JD 职责的契合度（重点看量化成果）

【评分锚点】（严格对照，保证两次评估分数稳定）
- 技能命中率 ≥80% → 技能维度 85+；50%-80% → 60-80；<50% → ≤55
- 经历高度相关且有量化成果 → 85+；部分相关 → 60-80；不相关 → ≤55

【硬性门槛判定】
- 逐项判断学历 / 专业 / 年限 / 证书是否满足 JD 硬性要求
- 任一项不满足 → hard_gate.met = false，且 verdict 强制为「不建议投」
- 但硬性门槛的维度分与总分仍按实际加权计算（不人为压低），如实反映技能与经历的真实匹配度

【JD 要求命中表】
- 把 JD 的要求拆成逐条清单，类别为：技能 / 职责 / 软性 / 加分项
- 每条判断简历是否命中；matched=true 必须给出 evidence（简历原文摘录，1 句内）
- matched=false 的条目给出 gap（缺什么、差在哪），并标注 source：
  - resume：简历里已有体现（命中）
  - addable：简历可补——你有相关经历只是没写清楚（可注入）
  - missing：简历与可补范围都没有（真缺失）
- 诚实原则：只基于简历实际内容判断，绝不虚构简历不存在的经历

【verdict 规则】（必须与分数和硬性门槛一致，禁止自相矛盾）
- hard_gate.met = false → 「不建议投」
- 否则：overall_score ≥70 → 「可投」；55-70 → 「建议优化」；<55 → 「不建议投」

【逐段诊断】
- 针对实习 / 项目经历等关键段落，指出「这段为什么不够匹配」+ 一句可执行的改写建议

【输出要求】
- 只输出一个 JSON 对象，不要 markdown 代码块，不要任何多余文字
- 结构严格符合下方 Schema：
{
  "overall_score": 整数0-100,
  "verdict": "可投" 或 "建议优化" 或 "不建议投",
  "hard_gate": {"met": true或false, "reasons": ["不满足项说明"]},
  "dimensions": [
    {"name": "硬性门槛", "score": 整数0-100, "reason": "一句理由"},
    {"name": "技能匹配", "score": 整数0-100, "reason": "一句理由"},
    {"name": "经历相关性", "score": 整数0-100, "reason": "一句理由"}
  ],
  "jd_requirements": [
    {"category": "技能|职责|软性|加分项", "requirement": "要求原文", "matched": true或false,
     "evidence": "简历原文摘录(命中时)", "gap": "缺什么差在哪(未命中时)", "source": "resume|addable|missing"}
  ],
  "resume_diagnosis": [
    {"section": "段落名(如 实习经历-XX公司)", "issue": "为什么不够匹配", "suggestion": "一句可执行改写建议"}
  ]
}"""


def _build_user_message(jd_text: str, resume_text: str, algorithm: dict) -> str:
    """构造 user message：算法命中信号（客观锚点）在前，JD 与简历在后。"""
    matched = algorithm["matched_keywords"]
    missing = algorithm["missing_keywords"]
    return (
        "【算法核对信号】（仅供参考，用于交叉验证；发现误判可用你的语义理解修正）\n"
        f"关键词命中率: {algorithm['keyword_hit_rate']}"
        f"（命中 {len(matched)} / {len(matched) + len(missing)} 个 JD 高频词）\n"
        f"命中的关键词: {', '.join(matched) if matched else '无'}\n"
        f"疑似缺失关键词: {', '.join(missing) if missing else '无'}\n\n"
        f"【岗位 JD】\n{jd_text}\n\n"
        f"【求职简历】\n{resume_text}"
    )


def _extract_json(text: str) -> dict:
    """从 LLM 输出提取 JSON：剥 markdown 围栏 + 宽松花括号匹配（复用 classify 的健壮性）。"""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 搜索第一个完整的 { ... } 对象（处理 LLM 偶尔前后夹带文字）
    stack = []
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if start < 0:
                start = i
            stack.append("{")
        elif ch == "}":
            if stack:
                stack.pop()
                if not stack and start >= 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        pass
                    start = -1
    raise RuntimeError(f"LLM 返回无法解析的 JSON: {text[:300]}...")


def _call_llm(system_prompt: str, user_message: str) -> dict:
    """② LLM 一次调用，拿结构化评分报告。

    不走 LLMClient.classify()：其 max_tokens=2000 放不下完整评分报告
    （契约 §7.1）。直调 chat/completions，参数见 match-schema §4.2：
    temperature=0.1 / max_tokens=4000 / response_format json_object（失败降级重试）。
    """
    if not LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY 未配置")
    if "anthropic" in LLM_API_BASE:
        raise RuntimeError("匹配度引擎暂仅支持 OpenAI 兼容端点（如 DeepSeek）")

    import requests

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": 4000,
        "temperature": 0.1,
    }
    last_content = ""
    for attempt in range(2):
        body = dict(payload)
        if attempt == 0:
            body["response_format"] = {"type": "json_object"}
        resp = requests.post(
            f"{LLM_API_BASE.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60,
        )
        data = resp.json()
        if "error" in data:
            err_msg = str(data.get("error", {}))
            # response_format 不支持 → 降级重试一次（复用 classify 的策略）
            if attempt == 0 and (
                "response_format" in err_msg
                or "invalid" in err_msg.lower()
                or "not supported" in err_msg.lower()
            ):
                continue
            raise RuntimeError(f"LLM API 错误: {data['error']}")
        last_content = data["choices"][0]["message"]["content"]
        try:
            return _extract_json(last_content)
        except RuntimeError:
            if attempt == 0:
                continue
            raise
    raise RuntimeError(f"LLM 返回无法解析的 JSON: {last_content[:300]}...")


def _post_process(report: dict, algorithm: dict,
                  threshold: int = MATCH_THRESHOLD,
                  weights: dict = MATCH_WEIGHTS) -> dict:
    """③ 后处理（契约 §3）：总分按维度加权重算、verdict 强一致、字段钳制清洗。

    overall_score 用 LLM 给的维度分重算（Σ 分×权重），覆盖 LLM 直接输出的总分，
    保证总分与维度分严格一致（补 ResumeIQ"分数与结论打架"的坑）。
    """
    # 1. 钳制维度分 + 绑定权重
    dims = []
    for d in report.get("dimensions") or []:
        if not isinstance(d, dict):
            continue
        try:
            score = max(0, min(100, int(round(float(d.get("score", 0))))))
        except (TypeError, ValueError):
            score = 0
        name = str(d.get("name", ""))
        dims.append({
            "name": name,
            "weight": weights.get(name, 0),
            "score": score,
            "reason": str(d.get("reason", "")),
        })
    report["dimensions"] = dims

    # 2. 总分重算
    overall = round(sum(d["score"] * d["weight"] for d in dims))
    report["overall_score"] = max(0, min(100, overall))

    # 3. hard_gate 容错（LLM 漏输出时默认 met=true 宽容处理）
    hg = report.get("hard_gate") or {}
    met = bool(hg.get("met", True))
    report["hard_gate"] = {"met": met, "reasons": hg.get("reasons") or []}

    # 4. verdict 强一致（契约 §3）：硬性门槛最高优先，否则按分数档位
    if not met:
        verdict = "不建议投"
    elif overall >= threshold:
        verdict = "可投"
    elif overall >= 55:
        verdict = "建议优化"
    else:
        verdict = "不建议投"
    report["verdict"] = verdict

    # 5. jd_requirements 清洗 + source 合法化
    reqs = []
    for r in report.get("jd_requirements") or []:
        if not isinstance(r, dict) or not r.get("requirement"):
            continue
        matched = bool(r.get("matched"))
        source = str(r.get("source") or "")
        if source not in ("resume", "addable", "missing"):
            source = "resume" if matched else "missing"
        reqs.append({
            "category": str(r.get("category") or "技能"),
            "requirement": str(r["requirement"]),
            "matched": matched,
            "evidence": str(r.get("evidence") or ""),
            "gap": str(r.get("gap") or ""),
            "source": source,
        })
    report["jd_requirements"] = reqs

    # 6. resume_diagnosis 清洗
    report["resume_diagnosis"] = [
        {
            "section": str(d.get("section", "")),
            "issue": str(d.get("issue", "")),
            "suggestion": str(d.get("suggestion", "")),
        }
        for d in (report.get("resume_diagnosis") or [])
        if isinstance(d, dict) and d.get("issue")
    ]

    report["algorithm_check"] = algorithm
    return report


def evaluate(jd_text: str, resume_text: str, config: dict = None) -> dict:
    """JD + 简历 → 评分报告（契约 §1）。纯函数、无状态，任何入口可调。

    config 可选覆盖：{"threshold": 70, "weights": {...}}
    """
    jd_text = (jd_text or "").strip()[:MATCH_MAX_JD_CHARS]
    resume_text = (resume_text or "").strip()[:MATCH_MAX_RESUME_CHARS]

    if not jd_text or not resume_text:
        raise ValueError("JD 与简历文本不能为空")

    # ① 算法预核对层
    algorithm = keyword_check(jd_text, resume_text)

    # ② LLM 一次调用
    report = _call_llm(SYSTEM_PROMPT, _build_user_message(jd_text, resume_text, algorithm))

    # ③ 后处理（支持 config 覆盖阈值/权重）
    threshold = (config or {}).get("threshold", MATCH_THRESHOLD)
    weights = (config or {}).get("weights", MATCH_WEIGHTS)
    return _post_process(report, algorithm, threshold, weights)


if __name__ == "__main__":
    # 快速自测：python match_engine.py jd.txt resume.txt
    import sys

    if len(sys.argv) == 3:
        jd = open(sys.argv[1], encoding="utf-8").read()
        resume = open(sys.argv[2], encoding="utf-8").read()
        print(json.dumps(evaluate(jd, resume), ensure_ascii=False, indent=2))
    else:
        print("用法: python match_engine.py <jd.txt> <resume.txt>")
