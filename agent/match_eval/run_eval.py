"""评测脚本 — 一键跑岗位匹配度引擎 vs 人工标注集

用法（在 agent/ 目录下）：
  python match_eval/run_eval.py                # 跑全部标注集（会调 LLM）
  python match_eval/run_eval.py --refresh      # 强制重跑引擎（不读结果缓存）
  python match_eval/run_eval.py --keyword-only # 只跑算法核对层（不调 LLM，秒级）

输出指标见 docs/match-schema.md §6.3：
  总分 MAE / max error、verdict 一致率、硬性门槛一致率、命中表 Precision/Recall

可复现要求（契约 §6.3）：README/文档里出现的任何指标数字，必须能从
`python match_eval/run_eval.py --refresh` 一条命令重算出同一结果。
"""

import argparse
import json
import os
import sys

# 让脚本能 import agent/ 下的模块（match_engine / config）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
EVAL_SET = os.path.join(EVAL_DIR, "eval_set.json")
CACHE_FILE = os.path.join(EVAL_DIR, "eval_output.json")


# ── 加载与跑引擎 ─────────────────────────────────────────

def load_eval_set(path: str) -> list:
    """读取标注集，返回 cases 列表；空集给出友好提示。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    cases = data.get("cases", [])
    if not cases:
        raise SystemExit(f"⚠️ {path} 的 cases 为空，请先添加标注案例（格式参考 eval_set.example.json）")
    return cases


def run_engine(cases: list, refresh: bool = False, keyword_only: bool = False) -> list:
    """对每个 case 跑引擎，返回 [{id, ai_report, human}]。

    AI 报告缓存到 eval_output.json（key=case id）——缓存**只存 ai_report**，
    human 永远从当前标注集实时读取（用户标注会变，不能用缓存里的旧值）。
    --refresh 强制重跑引擎。
    keyword_only 模式不缓存（它只是快速看算法核对层）。
    """
    cached = {}
    if not refresh and not keyword_only and os.path.exists(CACHE_FILE):
        try:
            cached = {c["id"]: c.get("ai_report") for c in json.load(open(CACHE_FILE, encoding="utf-8"))}
        except (json.JSONDecodeError, OSError):
            cached = {}

    results = []
    for case in cases:
        cid = case["id"]
        if cid in cached:
            results.append({"id": cid, "ai_report": cached[cid], "human": case.get("human", {})})
            print(f"  [{cid}] 命中缓存，跳过 LLM")
            continue

        if keyword_only:
            from match_engine import keyword_check
            ai_report = {"algorithm_check": keyword_check(case["jd_text"], case["resume_excerpt"])}
        else:
            from match_engine import evaluate
            ai_report = evaluate(case["jd_text"], case["resume_excerpt"])

        results.append({"id": cid, "ai_report": ai_report, "human": case.get("human", {})})

    if not keyword_only:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump([{"id": r["id"], "ai_report": r["ai_report"]} for r in results],
                      f, ensure_ascii=False, indent=2)
    return results


# ── 指标计算 ─────────────────────────────────────────

def compute_metrics(results: list) -> dict:
    """分层指标（match-schema §6.3）：各指标只在有对应 human 标注的 case 上计算。"""
    # 1. 总分 MAE（需 human.overall_score）
    score_diffs = []
    for r in results:
        human_score = r["human"].get("overall_score")
        ai_score = r["ai_report"].get("overall_score")
        if human_score is None or ai_score is None:
            continue
        score_diffs.append(abs(ai_score - human_score))

    # 2. verdict 一致率（需 human.verdict）
    verdict_hits, verdict_total = 0, 0
    for r in results:
        hv = r["human"].get("verdict")
        av = r["ai_report"].get("verdict")
        if not hv or not av:
            continue
        verdict_total += 1
        if hv == av:
            verdict_hits += 1

    # 3. 硬性门槛一致率（需 human.hard_gate_met 与 ai hard_gate）
    gate_hits, gate_total = 0, 0
    for r in results:
        hg = r["human"].get("hard_gate_met")
        ag = r["ai_report"].get("hard_gate", {}).get("met")
        if hg is None or ag is None:
            continue
        gate_total += 1
        if bool(hg) == bool(ag):
            gate_hits += 1

    # 4. 命中表 Precision / Recall（需 human.jd_requirements 非空）
    tp = fp = fn = 0  # 判命中且标命中 / 判命中但未标中 / 标命中但未判
    labeled_cases = 0
    for r in results:
        human_reqs = r["human"].get("jd_requirements") or []
        if not human_reqs:
            continue
        labeled_cases += 1
        human_map = {x.get("requirement", "").strip(): x for x in human_reqs if x.get("requirement")}

        def find_human(req):
            # 精确匹配优先，其次互相包含（容忍标注时文本微调）
            if req in human_map:
                return human_map[req]
            for hreq, hr in human_map.items():
                if req in hreq or hreq in req:
                    return hr
            return None

        for ar in r["ai_report"].get("jd_requirements", []):
            req = ar.get("requirement", "").strip()
            hr = find_human(req)
            if hr is None:
                continue  # 用户没标这条要求，不计入
            if ar.get("matched") and hr.get("matched"):
                tp += 1
            elif ar.get("matched") and not hr.get("matched"):
                fp += 1
            elif not ar.get("matched") and hr.get("matched"):
                fn += 1

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None

    return {
        "mae": (sum(score_diffs) / len(score_diffs)) if score_diffs else None,
        "max_error": max(score_diffs) if score_diffs else None,
        "score_n": len(score_diffs),
        "verdict_accuracy": (verdict_hits / verdict_total) if verdict_total else None,
        "verdict_n": verdict_total,
        "gate_accuracy": (gate_hits / gate_total) if gate_total else None,
        "gate_n": gate_total,
        "hit_precision": round(precision, 3) if precision is not None else None,
        "hit_recall": round(recall, 3) if recall is not None else None,
        "hit_labeled_cases": labeled_cases,
    }


def print_report(results: list, metrics: dict):
    """逐条打印 + 汇总指标。"""
    print("\n━━ 逐条对比 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    for r in results:
        ai = r["ai_report"]
        hu = r["human"]
        human_score = hu.get("overall_score")
        ai_score = ai.get("overall_score")
        diff = f"{abs(ai_score - human_score):>3}" if (ai_score is not None and human_score is not None) else "  -"
        v = f"{ai.get('verdict', '')}({'✓' if ai.get('verdict') == hu.get('verdict') else '✗'})" if hu.get("verdict") else ai.get("verdict", "")
        g = "✓" if ai.get("hard_gate", {}).get("met") == bool(hu.get("hard_gate_met")) else "✗"
        algo = ai.get("algorithm_check", {})
        hit = f"{algo.get('keyword_hit_rate', '-')}"
        print(f"  [{r['id']}] AI {ai_score} vs Human {human_score} | diff {diff} | verdict {v} | 门槛{g} | 算法命中 {hit}")

    print("\n━━ 汇总指标 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    def fmt(v, suffix=""):
        return f"{v:.2f}{suffix}" if v is not None else "N/A（标注缺失）"

    print(f"  总分 MAE: {fmt(metrics['mae'])}  (max {fmt(metrics['max_error'])}，{metrics['score_n']} 组)")
    print(f"  verdict 一致率: {fmt(metrics['verdict_accuracy'], '%')}  ({metrics['verdict_n']} 组)")
    print(f"  硬性门槛一致率: {fmt(metrics['gate_accuracy'], '%')}  ({metrics['gate_n']} 组)")
    print(f"  命中表 Precision: {fmt(metrics['hit_precision'])}  Recall: {fmt(metrics['hit_recall'])}  ({metrics['hit_labeled_cases']} 组有标注)")
    print("\n  校准循环（契约 §6.4）：调 prompt/锚点/停用词 → --refresh 重跑对比")


def make_template(eval_set_path: str, cache_path: str):
    """生成待标注模板：以 AI 命中表的 requirement 文本为准，保证标注粒度对齐。

    用法：先跑一次完整评测（生成 AI 缓存）→ --make-template →
    在模板上填 human 字段（overall_score / verdict / hard_gate_met），
    并逐条确认 jd_requirements 的 matched（AI 判错的改掉）→ 改名为 eval_set.json 评测。
    """
    if not os.path.exists(cache_path):
        raise SystemExit(f"⚠️ 无缓存 {cache_path}，请先跑一次完整评测生成 AI 报告")
    cache = {c["id"]: c for c in json.load(open(cache_path, encoding="utf-8"))}
    cases = load_eval_set(eval_set_path)

    template_cases = []
    for case in cases:
        ai = cache.get(case["id"], {}).get("ai_report", {})
        human = case.get("human", {})
        template_cases.append({
            "id": case["id"],
            "resume_excerpt": case.get("resume_excerpt", ""),
            "jd_text": case.get("jd_text", ""),
            "human": {
                "overall_score": human.get("overall_score"),
                "verdict": human.get("verdict", ""),
                "hard_gate_met": human.get("hard_gate_met"),
                # 以 AI requirement 文本为基准，用户只需确认/纠正 matched
                "jd_requirements": [
                    {"requirement": r.get("requirement", ""), "matched": r.get("matched", False)}
                    for r in ai.get("jd_requirements", [])
                ],
                "notes": "审阅 AI 命中表：把判错的 matched 改过来；overall_score/verdict/hard_gate_met 按你的判断填",
            },
        })

    out = os.path.join(EVAL_DIR, "eval_set.template.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"cases": template_cases}, f, ensure_ascii=False, indent=2)
    print(f"✅ 已生成待标注模板 {out}\n   填写 human 字段后改名为 eval_set.json 即可评测")


def main():
    parser = argparse.ArgumentParser(description="匹配度引擎评测（match-schema §6）")
    parser.add_argument("--eval-file", default=EVAL_SET, help="标注集路径（默认 match_eval/eval_set.json）")
    parser.add_argument("--refresh", action="store_true", help="强制重跑引擎，不读结果缓存")
    parser.add_argument("--keyword-only", action="store_true", help="只跑算法核对层（不调 LLM）")
    parser.add_argument("--make-template", action="store_true", help="从缓存 AI 报告生成待标注模板")
    args = parser.parse_args()

    if args.make_template:
        make_template(args.eval_file, CACHE_FILE)
        return

    cases = load_eval_set(args.eval_file)
    print(f"📊 标注集: {len(cases)} 组 → 跑引擎...")

    results = run_engine(cases, refresh=args.refresh, keyword_only=args.keyword_only)
    metrics = compute_metrics(results)
    print_report(results, metrics)


if __name__ == "__main__":
    main()
