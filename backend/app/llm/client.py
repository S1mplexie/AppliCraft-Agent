"""对任意 OpenAI 兼容 /chat/completions 端点的轻量异步封装。

不提供兜底或模拟模式：缺少 API Key 或端点调用失败时，错误会直接抛给调用方。
生成的文书绝不允许包含「看起来像真实模型输出」的伪造内容。
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from app.config import Settings


class LLMNotConfiguredError(RuntimeError):
    pass


class LLMCallError(RuntimeError):
    pass


def extract_json(text: str) -> Any:
    """宽容的 JSON 提取：兼容代码块包裹与前后多余文字。"""
    cleaned = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S | re.I)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMCallError("模型未返回可解析的 JSON")


class LLMClient:
    def __init__(self, settings: Settings, source: str = "system"):
        """source 标记这份配置来自「系统 .env」还是「用户自带 Key」，
        用于区分错误提示以及是否计入系统每日配额。"""
        self.settings = settings
        self.source = source
        if not settings.llm_configured:
            raise LLMNotConfiguredError(
                "尚未配置大模型 API Key。请在 .env 中设置 APPLICRAFT_LLM_API_KEY"
                "（以及 APPLICRAFT_LLM_BASE_URL / APPLICRAFT_LLM_MODEL），然后重启服务。"
            )
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - 仅在依赖缺失时触发
            raise LLMCallError("缺少 openai 依赖，请执行 pip install -r requirements.txt") from exc
        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout,
            max_retries=0,  # 重试在本类中统一处理，便于返回一致的错误信息
        )

    async def complete(
        self,
        *,
        task: str,
        system: str,
        user: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        system_prompt = system
        if json_mode:
            system_prompt += "\n\n请只返回一个合法的 JSON 对象，不要输出任何解释性文字，也不要使用代码块。"

        params: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user},
            ],
            "temperature": self.settings.llm_temperature if temperature is None else temperature,
            "max_tokens": self.settings.llm_max_tokens if max_tokens is None else max_tokens,
            # 刻意不传 response_format：部分 OpenAI 兼容服务会拒绝该参数。
            # 改为通过提示词约束 JSON，并用宽容解析兜底。
            "stream": False,
        }

        last_error: Exception | None = None
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                response = await self._client.chat.completions.create(**params)
                content = response.choices[0].message.content if response.choices else None
                if not content or not content.strip():
                    raise LLMCallError("模型返回了空内容")
                return content.strip()
            except Exception as exc:  # noqa: BLE001 - normalize every provider error
                last_error = exc
                if attempt < self.settings.llm_max_retries:
                    await asyncio.sleep(1.5 * (2**attempt))
        # 永不把 API Key 明文带进错误信息或前端日志；并让自带 Key 的用户知道该查自己那一侧。
        detail = str(last_error)
        key = (self.settings.llm_api_key or "").strip()
        if key and key in detail:
            detail = detail.replace(key, f"***{key[-4:]}")
        owner = "（你自带的 API Key，请检查余额、模型名与接口地址）" if self.source == "personal" else ""
        raise LLMCallError(f"模型调用失败{owner}（阶段：{task}）：{detail}")

    async def complete_json(self, **kwargs: Any) -> Any:
        kwargs["json_mode"] = True
        kwargs.setdefault("temperature", 0.0)
        return extract_json(await self.complete(**kwargs))

    async def aclose(self) -> None:
        if getattr(self, "_client", None) is not None:
            await self._client.close()
