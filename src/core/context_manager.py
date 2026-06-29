"""
上下文管理器 —— 管理长文本的分块与对话上下文
"""


class ContextManager:
    """管理 PDF 文本和对话上下文，在 token 超限时自动截断"""

    # 粗略估算：中文约 1.5 字符/token，英文约 4 字符/token
    # 取保守值：2 字符/token
    CHARS_PER_TOKEN = 2

    def __init__(self, max_tokens: int = 1_000_000):
        """
        参数:
            max_tokens: 模型最大上下文窗口（DeepSeek V4 支持 1M）
        """
        self.max_tokens = max_tokens
        self.max_chars = max_tokens * self.CHARS_PER_TOKEN
        self._pdf_text: str = ""
        self._chat_history: list[dict] = []

    def load_pdf_text(self, text: str):
        """加载 PDF 全文"""
        self._pdf_text = text
        self._chat_history = []

    def estimate_tokens(self, text: str) -> int:
        """粗略估算 token 数"""
        return len(text) // self.CHARS_PER_TOKEN

    def build_messages(self, user_query: str) -> list[dict]:
        """
        构建发送给 LLM 的完整消息列表。
        自动根据 token 预算截断上下文。
        """
        system_prompt = self._build_system_prompt()
        messages = [{"role": "system", "content": system_prompt}]

        # 计算已有消息的 token 占用
        used_tokens = self.estimate_tokens(system_prompt) + self.estimate_tokens(user_query)

        # 预留回复空间（约 4000 tokens）
        budget_tokens = self.max_tokens - used_tokens - 4000

        # 截取 PDF 文本
        pdf_section = self._truncate_text(self._pdf_text, budget_tokens)
        messages.append({"role": "user", "content": pdf_section})

        # 添加最近对话历史
        history_budget = budget_tokens - self.estimate_tokens(pdf_section)
        recent_history = self._get_recent_history(history_budget)
        messages.extend(recent_history)

        # 添加当前问题
        messages.append({"role": "user", "content": user_query})

        return messages

    def add_to_history(self, role: str, content: str):
        """添加一条消息到历史记录"""
        self._chat_history.append({"role": role, "content": content})

    def clear_history(self):
        """清除对话历史（保留 PDF 文本）"""
        self._chat_history = []

    def reset(self):
        """完全重置"""
        self._pdf_text = ""
        self._chat_history = []

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
        """按 token 预算截断文本（保留开头和结尾）"""
        char_budget = token_budget * self.CHARS_PER_TOKEN
        if len(text) <= char_budget:
            return text

        # 保留前 70% + 后 30%
        head_size = int(char_budget * 0.7)
        tail_size = int(char_budget * 0.3)
        return (
            text[:head_size]
            + f"\n\n...（中间部分已省略以适配上下文窗口，共省略约 {len(text) - head_size - tail_size} 字符）...\n\n"
            + text[-tail_size:]
        )

    def _get_recent_history(self, token_budget: int) -> list[dict]:
        """获取最近的对话历史，控制在 token 预算内"""
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
