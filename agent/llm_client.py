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

    def classify(self, system_prompt: str, user_message: str) -> dict:
        """Call LLM for structured JSON output (intent classification).
        Uses low temperature for consistent results."""
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY 未配置")

        import requests

        if "anthropic" in self.api_base:
            resp = requests.post(
                f"{self.api_base}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 500,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_message}],
                },
                timeout=15,
            )
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"LLM API 错误: {data['error']}")
            content = data["content"][0]["text"]
        else:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "max_tokens": 500,
                "temperature": 0.1,
            }
            payload["response_format"] = {"type": "json_object"}

            resp = requests.post(
                f"{self.api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=15,
            )
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"LLM API 错误: {data['error']}")
            content = data["choices"][0]["message"]["content"]

        # Parse JSON, handling possible markdown fences
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
        content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"LLM 返回无法解析的 JSON: {content[:200]}... ({e})")
