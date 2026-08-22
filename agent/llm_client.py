"""LLM API 客户端（兼容 OpenAI / Claude 格式）"""

import json

from config import LLM_API_KEY, LLM_API_BASE, LLM_MODEL


class LLMClient:
    def __init__(self):
        self.api_key = LLM_API_KEY
        self.api_base = LLM_API_BASE.rstrip("/")
        self.model = LLM_MODEL

    def chat(self, prompt: str) -> dict:
        """调用 LLM 生成分析结果，返回 {"summary": str, "insights": [str]}"""
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY 未配置")

        # 兼容 OpenAI 格式的 API（OpenAI / Claude via Anthropic SDK / 国产大模型）
        import requests

        # 检测是否 Anthropic API
        if "anthropic" in self.api_base:
            return self._chat_anthropic(prompt)
        return self._chat_openai(prompt)

    def chat_with_tools(self, messages, tools, executor=None,
                        max_tool_calls=8, temperature=0.7, timeout=60) -> str:
        """完整 tool-use 循环：LLM 自主决定调用工具，返回最终自然语言回复。

        messages: [{"role": "system", ...}, ...历史..., {"role": "user", "content": 当前消息}]
        tools:    OpenAI 函数 schema 列表
        executor: callable(tool_name, args_dict) -> dict，返回 {"ok": bool, ...}
        """
        if "anthropic" in self.api_base:
            raise RuntimeError("当前 LLM_API_BASE 不支持 function calling，请使用 OpenAI 兼容端点（如 DeepSeek）")

        import copy
        import requests

        if executor is None:
            def executor(name, args):
                return {"ok": False, "error": "未提供工具执行器"}

        history = copy.deepcopy(messages)

        for _ in range(max_tool_calls + 1):
            payload = {
                "model": self.model,
                "messages": history,
                "tools": tools,
                "tool_choice": "auto",
                "temperature": temperature,
            }
            resp = requests.post(
                f"{self.api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=timeout,
            )
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"LLM API 错误: {data['error']}")

            msg = data["choices"][0]["message"]

            # 原样回传 assistant 消息（含 tool_calls），供下一轮请求使用
            assistant_msg = {"role": "assistant", "content": msg.get("content")}
            if msg.get("tool_calls"):
                assistant_msg["tool_calls"] = msg["tool_calls"]
            history.append(assistant_msg)

            if not msg.get("tool_calls"):
                # 无工具调用，即最终回复
                return (msg.get("content") or "").strip()

            # 执行模型要求的所有工具调用
            for tc in msg["tool_calls"]:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except (json.JSONDecodeError, TypeError):
                    args = {}  # 参数解析失败，交给工具缺参提示
                try:
                    result_payload = executor(name, args)
                except Exception as e:
                    result_payload = {"ok": False, "error": f"executor 异常: {e}"}
                tool_content = json.dumps(result_payload, ensure_ascii=False)[:2000]
                history.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": tool_content,
                })

        raise RuntimeError(f"工具调用超过 {max_tool_calls} 轮上限，已停止")

    def _chat_openai(self, prompt: str) -> dict:
        import requests

        resp = requests.post(
            f"{self.api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是一个求职复盘教练。请基于投递数据给出结构化分析。"
                        "返回格式：先一段总结摘要，然后用要点列出洞察。",
                    },
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 2000,
                "temperature": 0.7,
            },
            timeout=60,
        )
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"LLM API 错误: {data['error']}")

        content = data["choices"][0]["message"]["content"]
        return self._parse_response(content)

    def _chat_anthropic(self, prompt: str) -> dict:
        import requests

        resp = requests.post(
            f"{self.api_base}/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 2000,
                "system": "你是一个求职复盘教练。请基于投递数据给出结构化分析。"
                "返回格式：先一段总结摘要，然后用要点列出洞察。",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Anthropic API 错误: {data['error']}")
        content = data["content"][0]["text"]
        return self._parse_response(content)

    def _parse_response(self, content: str) -> dict:
        """解析 LLM 输出为结构化数据"""
        lines = content.strip().split("\n")
        summary = ""
        insights = []
        in_summary = True
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if in_summary:
                summary += line + " "
                if any(c in line for c in ["。", "！", "？"]) and len(summary) > 30:
                    in_summary = False
            else:
                clean = line.lstrip("•-*0123456789.、 ")
                if clean and len(clean) > 5:
                    insights.append(clean)

        if not insights:
            insights = [content[:500]]

        return {"summary": summary.strip(), "insights": insights[:10]}

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from LLM response, checking code fences and loose braces."""
        text = text.strip()
        # Remove markdown code fences (```json ... ``` or ``` ... ```)
        if text.startswith("```"):
            text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
        text = text.strip()

        # Try parsing directly
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Search for JSON object in text (first { to matching })
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

    def classify(self, system_prompt: str, user_message: str) -> dict:
        """Call LLM for structured JSON output (intent classification).
        Uses low temperature for consistent results."""
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY 未配置")

        import requests

        if "anthropic" in self.api_base:
            return self._classify_anthropic(system_prompt, user_message)
        return self._classify_openai(system_prompt, user_message)

    def _classify_anthropic(self, system_prompt: str, user_message: str) -> dict:
        import requests

        resp = requests.post(
            f"{self.api_base}/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 2000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}],
            },
            timeout=15,
        )
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"LLM API 错误: {data['error']}")
        content = data["content"][0]["text"]
        return self._extract_json(content)

    def _classify_openai(self, system_prompt: str, user_message: str) -> dict:
        import requests

        # Try with response_format first (OpenAI / DeepSeek compatible)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": 2000,
            "temperature": 0.1,
        }

        for attempt in range(2):
            body = dict(payload)
            if attempt == 0:
                body["response_format"] = {"type": "json_object"}

            resp = requests.post(
                f"{self.api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=15,
            )
            data = resp.json()
            if "error" in data:
                err_msg = str(data.get("error", {}))
                # If response_format is not supported, fall through to retry without it
                if attempt == 0 and ("response_format" in err_msg or "invalid" in err_msg.lower() or "not supported" in err_msg.lower()):
                    continue
                raise RuntimeError(f"LLM API 错误: {data['error']}")

            content = data["choices"][0]["message"]["content"]
            try:
                return self._extract_json(content)
            except RuntimeError:
                if attempt == 0:
                    continue
                raise
        raise RuntimeError(f"LLM 返回无法解析的 JSON: {content[:300]}...")
