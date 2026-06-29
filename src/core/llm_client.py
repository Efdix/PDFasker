"""
LLM API 客户端 —— 支持所有 OpenAI 兼容接口
（DeepSeek V4、MiniMax、通义千问、智谱 等）
"""

from openai import OpenAI
from typing import Generator


class LLMClient:
    """统一的 LLM API 客户端，支持 OpenAI 兼容接口"""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(self, messages: list[dict], stream: bool = True) -> Generator[str, None, None] | str:
        """
        发送对话请求。

        参数:
            messages: 标准 OpenAI 格式的消息列表
            stream: 是否流式输出

        返回:
            流式模式: 生成器，逐块 yield 文本（自动跳过思考过程）
            非流式模式: 返回完整回复字符串
        """
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=stream,
            temperature=0.3,  # 解读文献用较低温度，更严谨
        )

        if stream:
            for chunk in response:
                delta = chunk.choices[0].delta
                # DeepSeek V4 thinking 模式会返回 reasoning_content（思考过程）
                # 我们只取真正的回复内容 content
                if delta.content:
                    yield delta.content
        else:
            return response.choices[0].message.content

    def chat_sync(self, messages: list[dict]) -> str:
        """同步聊天（非流式），返回完整回复"""
        return self.chat(messages, stream=False)


# 预设的 API 提供商配置
PROVIDERS = {
    "DeepSeek": {
        "base_url": "https://api.deepseek.com",
        "models": [
            "deepseek-v4-flash",    # ⭐ 推荐：快 + 便宜，1M 上下文
            "deepseek-v4-pro",      # 最强：深度推理，1M 上下文
            "deepseek-chat",        # 旧版（2026/7/24 停用）→ 同 v4-flash 非思考模式
            "deepseek-reasoner",    # 旧版（2026/7/24 停用）→ 同 v4-flash 思考模式
        ],
        "description": "DeepSeek V4 系列（1M 上下文 | Flash 实惠 / Pro 最强 | 支持思考模式）",
    },
    "MiniMax": {
        "base_url": "https://api.minimax.chat/v1",
        "models": ["MiniMax-Text-01", "abab6.5s-chat"],
        "description": "MiniMax 大模型",
    },
    "自定义": {
        "base_url": "",
        "models": [],
        "description": "自定义 OpenAI 兼容接口",
    },
}
