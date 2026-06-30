"""LLM API 客户端 —— OpenAI 兼容接口"""

from openai import OpenAI
from typing import Generator


class LLMClient:
    """统一的 LLM API 客户端"""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat_stream(self, messages: list[dict]) -> Generator[str, None, None]:
        """流式对话，自动跳过 reasoning_content"""
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            temperature=0.3,
        )
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    def chat_sync(self, messages: list[dict]) -> str:
        """同步对话"""
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=False,
            temperature=0.3,
        )
        return response.choices[0].message.content


PROVIDERS = {
    "DeepSeek": {
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "description": "DeepSeek V4 系列（1M 上下文 | Flash 实惠 / Pro 最强）",
    },
    "Mimo": {
        "base_url": "https://api.xiaomimimo.com/v1",
        "models": ["mimo-v2.5", "mimo-v2.5-pro"],
        "description": "Mimo 大模型系列",
    },
    "自定义": {
        "base_url": "",
        "models": [],
        "description": "自定义 OpenAI 兼容接口",
    },
}
