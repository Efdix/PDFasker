"""综述写作辅助引擎 —— 根据引文匹配真实文献，对照原文给出改写建议。"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from collections.abc import Callable

from .llm_client import LLMClient
from .pdf_parser import PDFParser
from .zotero_parser import ZoteroItem, ZoteroLibrary


@dataclass
class CitationClaim:
    """综述中的一条引文声明及其分析结果。"""
    claim_id: int
    claim_text: str                 # 综述原文
    citation_marker: str            # 引文标记，如 "[1]"、"(Wang, 2020)"
    matched_item: ZoteroItem | None = None
    parsed_title: str = ""
    parsed_authors: str = ""
    parsed_year: str = ""
    topic_keywords: str = ""
    source_context: str = ""        # 从 PDF 检索到的原文段落
    ai_feedback: str = ""           # AI 反馈
    rewrite_suggestion: str = ""    # AI 建议的改写版本
    status: str = ""                # 引用恰当 / 建议补充 / 表述可优化 / 需核实 / 文献未匹配


@dataclass
class ReviewCheckResult:
    """综述辅助分析结果。"""
    claims: list[CitationClaim] = field(default_factory=list)
    overall_assessment: str = ""     # 整体修改建议
    structure_suggestions: str = ""  # 结构建议


class ReviewChecker:
    """综述写作辅助器。

    流程：LLM 提取引文声明 → Zotero 匹配文献 → 对照原文逐条建议 → 整体修改方案。
    """

    # 提取引文声明
    EXTRACT_PROMPT = """你是一位学术写作分析专家。请分析以下综述文本，提取其中所有带引用的声明。

对每个引用声明，请提取：
1. 声明内容（即综述作者写的观点/结论，保留完整原文）
2. 引文标记（如 [1], [3,5], (Smith et al., 2020), "Smith等人发现..."）
3. 尝试推断该引文对应的文献信息：标题关键词、第一作者姓氏、发表年份
4. 该声明涉及的研究主题关键词（如"寄生蜂"、"神经网络"、"气候变化"等）

请以 JSON 数组格式输出，每个元素包含：
- "claim_text": 声明原文
- "citation_marker": 引文标记
- "title_hint": 从上下文中能推断的文献标题关键词（没有则为空字符串）
- "author_hint": 从上下文中能推断的第一作者姓氏（没有则为空字符串）
- "year_hint": 四位年份（没有则为空字符串）
- "topic_keywords": 该声明涉及的研究主题词，逗号分隔

只输出 JSON 数组，不要其他内容。如果没有找到带引用的声明，输出空数组 []。

综述文本：
{review_text}"""

    # 对照原文给出改写建议（核心 prompt）
    REWRITE_PROMPT = """你是一位资深的学术写作导师。你的任务是对照原始论文，帮助作者改进综述中的这一段文字。

【原始论文相关内容】
{source_context}

【综述中的当前写法】
{claim_text}

请从以下角度给出具体可操作的修改建议：

1. **内容完整性**：综述是否遗漏了原文中的重要发现、关键数据或核心结论？如果有，请指出应补充什么。
2. **表述精准度**：综述的表述是否准确反映了原文的意思？有没有可以更精确的措辞？
3. **引用增强**：这段综述是否充分利用了这篇文献的价值？原文中还有哪些观点可以用来丰富这一段？
4. **逻辑衔接**：如果这段前后文有逻辑跳跃，请建议如何添加过渡句。

请按以下格式回答：
**诊断**：[用 1-2 句概括这段综述与原文的关系]
**可补充的内容**：[原文中有但综述未提及的重要信息，用列表]
**建议改写的版本**：[给出一个改写后的段落示例，保持学术风格，字数与原文相当。如果原文已经很好，写"原文已较好，无需大幅修改"即可]
**关键词提示**：[列出原文中的 3-5 个关键技术术语/概念，作者可考虑在综述中使用]"""

    # 整体修改与改写
    OVERALL_PROMPT = """你是一位学术论文润色专家。请对以下综述草稿进行整体改写和优化。

【综述全文】
{review_text}

【各引文逐条分析汇总】
{verification_summary}

## 改写要求

### 1. 语言风格
- 专业、简练、平实、客观，避免夸张和口语化表达
- 使用学术论文的标准行文方式，术语准确、句式严谨
- 删除冗余表述，但保留必要的限定词（如"可能""在大多数情况下"等体现学术严谨性的措辞）

### 2. 引用核查与补充
- 每条分析中标记为「建议补充」「表述可优化」的引用声明，对照原文反馈修正表述
- 标记为「文献未匹配」的，如所述内容为学术界共识可保留，否则标注为待核实
- 根据综述涉及的研究主题，判断现有引用是否覆盖了关键文献；如发现明显遗漏的重要研究方向或经典文献，在文末以注释形式列出建议补充的文献（格式：作者, 年份, 标题关键词, 建议引用理由, 一句话）

### 3. 过渡与衔接
- 检查句子之间的逻辑关系，必要时添加连接词或过渡句
- 确保段落之间有清晰的逻辑推进（如：问题→方法→进展→不足→展望）
- 小节之间如有跳跃，补写 1-2 句承上启下的过渡语句

## 输出格式

请直接输出改写后的完整综述全文，不要输出修改说明或评价。字数与原文大致相当或略增。

在改写稿末尾，另起一行用 `---` 分隔，然后以列表形式给出「建议补充引用」和「主要修改说明」（各不超过 5 条，每条一句话）。"""

    # 常见停用词
    _STOP_WORDS: frozenset[str] = frozenset({
        'the', 'and', 'that', 'this', 'for', 'with', 'are', 'was',
        'were', 'have', 'has', 'been', 'from', 'their', 'which',
        '等', '了', '的', '是', '在', '和', '与', '或',
    })

    def __init__(self, llm_client: LLMClient, zotero_lib: ZoteroLibrary) -> None:
        self._llm = llm_client
        self._zotero = zotero_lib

    @property
    def library_available(self) -> bool:
        return self._zotero.is_available

    def check_review(
        self, review_text: str,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> ReviewCheckResult:
        """对综述文本进行完整的引文分析和写作辅助。

        Args:
            review_text: 综述全文。
            progress_callback: 可选的进度回调 (step_message, current, total)。
        """
        result = ReviewCheckResult()

        # Step 1: 提取引文声明
        if progress_callback:
            progress_callback("正在分析引文...", 0, 100)
        claims_data = self._extract_claims(review_text)

        if not claims_data:
            result.overall_assessment = "未检测到带引用的声明。请确保综述中包含规范的引用格式（如 [1]、Smith et al., 2020 等）。"
            return result

        # Step 2: 匹配文献
        if progress_callback:
            progress_callback(f"正在文献库中匹配 {len(claims_data)} 条引文...", 10, 100)
        claims = self._match_citations(claims_data)

        # Step 3: 逐条阅读原文并生成建议
        total = len(claims)
        for i, claim in enumerate(claims):
            if progress_callback:
                progress_callback(
                    f"正在阅读第 {i+1}/{total} 篇文献并生成修改建议...",
                    20 + int(60 * i / max(total, 1)),
                    100
                )
            self._analyze_claim(claim)

        result.claims = claims

        # Step 4: 整体修改方案
        if progress_callback:
            progress_callback("正在生成整体修改方案...", 85, 100)
        result.overall_assessment = self._generate_overall(review_text, claims)

        if progress_callback:
            progress_callback("分析完成", 100, 100)

        return result

    def _extract_claims(self, review_text: str) -> list[dict]:
        """用 LLM 从综述中提取引文声明"""
        try:
            response = self._llm.chat_sync([
                {"role": "user", "content": self.EXTRACT_PROMPT.format(review_text=review_text)}
            ])
            # 尝试从回复中提取 JSON
            json_str = self._extract_json(response)
            return json.loads(json_str)
        except (json.JSONDecodeError, Exception) as e:
            print(f"[ReviewChecker] 提取声明失败: {e}")
            return []

    def _extract_json(self, text: str) -> str:
        """从 LLM 回复中提取 JSON 部分"""
        text = text.strip()
        # 尝试找到 JSON 数组
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            return text[start:end + 1]
        return text

    def _match_citations(self, claims_data: list[dict]) -> list[CitationClaim]:
        """将提取的声明与 Zotero 库匹配，利用主题关键词消歧。"""
        claims = []
        for i, cd in enumerate(claims_data):
            claim = CitationClaim(
                claim_id=i + 1,
                claim_text=cd.get("claim_text", ""),
                citation_marker=cd.get("citation_marker", ""),
                parsed_title=cd.get("title_hint", ""),
                parsed_authors=cd.get("author_hint", ""),
                parsed_year=cd.get("year_hint", ""),
            )

            # 构建主题文本用于消歧：声明文本 + 标题提示 + LLM提取的主题词
            topic_text = f"{claim.claim_text} {claim.parsed_title} {claim.topic_keywords}"

            matched = None
            candidates = []

            # 策略1: 作者+年份 → 返回所有匹配的候选
            if claim.parsed_authors and claim.parsed_year:
                candidates = self._zotero.find_by_citation(
                    claim.parsed_authors,
                    claim.parsed_year,
                    claim.parsed_title
                )
                # 如果只有一个候选，直接匹配
                if len(candidates) == 1:
                    matched = candidates[0]
                elif len(candidates) > 1:
                    # 多个候选，按主题相关性排序
                    ranked = self._zotero.rank_by_topic(candidates, topic_text)
                    matched = ranked[0] if ranked else candidates[0]

            # 策略2: 标题关键词搜索
            if not matched and claim.parsed_title:
                results = self._zotero.search(claim.parsed_title, max_results=5)
                if results:
                    if len(results) == 1:
                        matched = results[0]
                    else:
                        ranked = self._zotero.rank_by_topic(results, topic_text)
                        matched = ranked[0]

            # 策略3: 用引文标记 + 全文搜索
            if not matched:
                keywords = claim.citation_marker.strip("[]()").strip()
                if keywords:
                    results = self._zotero.search(keywords, max_results=5)
                    if results:
                        matched = results[0]

            claim.matched_item = matched
            claims.append(claim)

        return claims

    def _analyze_claim(self, claim: CitationClaim) -> None:
        """对照原文，为一条引文生成修改建议。"""
        if not claim.matched_item:
            claim.status = "文献未匹配"
            claim.ai_feedback = "未在文献库中找到匹配的论文。请确认文献已导入 Zotero 且 PDF 附件可用。"
            claim.rewrite_suggestion = "建议在 Zotero 中检查该文献是否已附加 PDF，然后重新运行分析。"
            return

        item = claim.matched_item
        if not item.pdf_path or not os.path.isfile(item.pdf_path):
            claim.status = "文献未匹配"
            claim.ai_feedback = f"已匹配到文献「{item.title[:80]}」，但 PDF 文件缺失。"
            claim.rewrite_suggestion = "请在 Zotero 中为该文献附加 PDF 后重试。"
            return

        # 提取 PDF 文本
        try:
            with PDFParser(item.pdf_path) as parser:
                full_text = parser.extract_full_text()
                claim.source_context = self._find_relevant_context(full_text, claim.claim_text)

                prompt = self.REWRITE_PROMPT.format(
                    source_context=claim.source_context,
                    claim_text=claim.claim_text,
                )
                response = self._llm.chat_sync([{"role": "user", "content": prompt}])
                claim.ai_feedback = response

                # 提取诊断
                diag_match = re.search(r'\*\*诊断\*\*\s*[：:]\s*(.+?)(?:\n\n|\n\*\*)', response, re.DOTALL)
                diagnosis = diag_match.group(1).strip() if diag_match else ""

                # 根据诊断内容推断状态
                diag_lower = diagnosis.lower()
                if any(w in diag_lower for w in ['遗漏', '未提及', '缺少', '补充', '还应']):
                    claim.status = "建议补充"
                elif any(w in diag_lower for w in ['不够准确', '可优化', '可改进', '调整', '措辞']):
                    claim.status = "表述可优化"
                elif any(w in diag_lower for w in ['基本准确', '较好', '一致', '原文已较好']):
                    claim.status = "引用恰当"
                else:
                    claim.status = "引用恰当"  # 默认

                # 提取改写建议
                sug_match = re.search(
                    r'\*\*建议改写的版本\*\*\s*[：:]\s*(.+?)(?:\n\n\*\*|\Z)',
                    response, re.DOTALL
                )
                if sug_match:
                    claim.rewrite_suggestion = sug_match.group(1).strip()

        except Exception as e:
            claim.status = "需核实"
            claim.ai_feedback = f"读取 PDF 时出错：{e}"
            claim.rewrite_suggestion = "请检查 PDF 文件是否损坏。"

    def _find_relevant_context(
        self, full_text: str, claim_text: str, max_chars: int = 8000,
    ) -> str:
        """在 PDF 全文中寻找与声明最相关的段落。

        策略：提取关键词 → 段落评分 → 按相关度拼接至字符上限。
        """
        keywords = [
            w.lower() for w in re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', claim_text)
            if w.lower() not in self._STOP_WORDS
        ]

        if not keywords:
            return self._fallback_context(full_text, max_chars)

        paragraphs = re.split(r'\n\s*\n', full_text)
        scored: list[tuple[int, str]] = []
        for para in paragraphs:
            if len(para.strip()) < 20:
                continue
            para_lower = para.lower()
            score = sum(1 for kw in keywords if kw in para_lower)
            if score > 0:
                scored.append((score, para))

        if not scored:
            return self._fallback_context(full_text, max_chars)

        scored.sort(key=lambda x: x[0], reverse=True)
        parts: list[str] = []
        total_chars = 0
        for _, para in scored:
            if total_chars + len(para) > max_chars:
                remaining = max_chars - total_chars
                if remaining > 200:
                    parts.append(para[:remaining] + "...")
                break
            parts.append(para)
            total_chars += len(para)

        return "\n\n".join(parts)

    @staticmethod
    def _fallback_context(full_text: str, max_chars: int) -> str:
        """无法匹配关键词时返回文本头尾。"""
        half = max_chars // 2
        return full_text[:half] + "\n\n...\n\n" + full_text[-half:]

    def _generate_overall(self, review_text: str, claims: list[CitationClaim]) -> str:
        """生成整体改写稿"""
        summary_parts = []
        for claim in claims:
            icon = {
                "引用恰当": "✅", "建议补充": "📝", "表述可优化": "💡",
                "需核实": "⚠️", "文献未匹配": "❓"
            }.get(claim.status, "❓")
            matched_title = claim.matched_item.title[:60] if claim.matched_item else "未匹配"
            # 截取 AI 反馈中关键部分（诊断 + 可补充内容）
            feedback_brief = claim.ai_feedback
            if len(feedback_brief) > 300:
                # 尝试取诊断行
                diag_match = re.search(r'\*\*诊断\*\*[：:]\s*(.+?)(?:\n|$)', feedback_brief)
                feedback_brief = (diag_match.group(1) if diag_match else feedback_brief[:300]) + "..."
            summary_parts.append(
                f"{icon} [{claim.status}] {claim.citation_marker} → {matched_title}\n"
                f"   综述原文：{claim.claim_text[:200]}...\n"
                f"   诊断：{feedback_brief}\n"
            )

        verification_summary = "\n".join(summary_parts)

        # 计算 token 预算：综述全文 + 分析汇总，保留足够空间给改写输出
        review_chars = len(review_text)
        summary_chars = len(verification_summary)
        # 如果原文较长，适当截断分析汇总以留空间给改写输出
        max_input = 12000  # 输入总字符上限
        if review_chars + summary_chars > max_input:
            budget_for_summary = max(2000, max_input - review_chars)
            if len(verification_summary) > budget_for_summary:
                verification_summary = verification_summary[:budget_for_summary] + "\n...(汇总已截断)"

        try:
            response = self._llm.chat_sync([
                {"role": "user", "content": self.OVERALL_PROMPT.format(
                    review_text=review_text,
                    verification_summary=verification_summary,
                )}
            ])
            return response
        except Exception as e:
            return f"生成整体评价时出错：{e}"

    def search_library_for_topic(self, topic: str, max_results: int = 10) -> list[ZoteroItem]:
        """根据主题搜索文献库，帮助用户找到应引用的文献"""
        if not self._zotero.is_available:
            return []
        return self._zotero.search(topic, max_results)
