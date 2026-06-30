"""上下文管理器 —— 长文本分块与对话上下文，token 超限时自动截断"""


class ContextManager:
    """管理 PDF 文本和对话上下文"""

    CHARS_PER_TOKEN = 2  # 保守估算：2 字符 ≈ 1 token

    def __init__(self, max_tokens: int = 1_000_000):
        self.max_tokens = max_tokens
        self._pdf_text: str = ""
        self._chat_history: list[dict] = []

    # ---- 公共 API ----

    def load_pdf_text(self, text: str):
        self._pdf_text = text
        self._chat_history = []

    def load_history(self, history: list[dict]):
        self._chat_history = history.copy()

    def get_history(self) -> list[dict]:
        return self._chat_history

    @property
    def has_pdf(self) -> bool:
        return bool(self._pdf_text)

    def get_full_context_for_estimation(self) -> str:
        return self._pdf_text + "".join(m["content"] for m in self._chat_history)

    def estimate_tokens(self, text: str) -> int:
        return len(text) // self.CHARS_PER_TOKEN

    def add_to_history(self, role: str, content: str):
        self._chat_history.append({"role": role, "content": content})

    def clear_history(self):
        self._chat_history = []

    def build_messages(self, user_query: str) -> list[dict]:
        """构建发送给 LLM 的完整消息列表，按 token 预算自动截断"""
        system_prompt = self._build_system_prompt()
        messages = [{"role": "system", "content": system_prompt}]

        used_tokens = self.estimate_tokens(system_prompt) + self.estimate_tokens(user_query)
        budget_tokens = self.max_tokens - used_tokens - 4000  # 预留回复空间

        pdf_section = self._truncate_text(self._pdf_text, budget_tokens)
        messages.append({"role": "user", "content": pdf_section})

        history_budget = budget_tokens - self.estimate_tokens(pdf_section)
        messages.extend(self._get_recent_history(history_budget))
        messages.append({"role": "user", "content": user_query})

        return messages

    # ---- 内部 ----

    def _build_system_prompt(self) -> str:
        return (
            "你是一位专业的科研文献分析助手。你的任务是帮助用户理解和分析学术论文。\n\n"
            "要求：\n"
            "1. 基于提供的论文原文内容回答问题，不要编造信息\n"
            "2. 回答要准确、专业、有条理\n"
            "3. 如果引用原文，注明所在页码\n"
            "4. 如果问题超出论文范围，诚实说明\n"
            "5. 使用中文回答，专业术语可保留英文并附中文解释"
        )

    def _truncate_text(self, text: str, token_budget: int) -> str:
        char_budget = token_budget * self.CHARS_PER_TOKEN
        if len(text) <= char_budget:
            return text
        head_size = int(char_budget * 0.7)
        tail_size = int(char_budget * 0.3)
        return (
            text[:head_size]
            + f"\n\n...（中间部分已省略，约 {len(text) - head_size - tail_size} 字符）...\n\n"
            + text[-tail_size:]
        )

    def _get_recent_history(self, token_budget: int) -> list[dict]:
        if not self._chat_history:
            return []
        result = []
        used = 0
        for msg in reversed(self._chat_history):
            msg_tokens = self.estimate_tokens(msg["content"])
            if used + msg_tokens > token_budget:
                break
            result.insert(0, msg)
            used += msg_tokens
        return result
