"""段落结构识别器 —— 用 LLM 标注每个段落的学术论文语义角色。

职责：
- 将 LLM 返回的结构指令解析为结构化数据
- 提供 StructureFormatWorker（QThread）供 UI 层调用
- 上下文组装：±2 相邻卡片 + 已处理卡片的结构标签
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from .llm_client import LLMClient


# ============================================================
# 结构标签定义
# ============================================================

# 所有可能的段落角色标签
SECTION_LABELS = [
    "section_header",       # 章节标题（如 "1. Introduction", "Methods"）
    "abstract_header",      # "Abstract" / "摘要" 这个词本身
    "abstract_body",        # 摘要正文
    "body",                 # 普通正文段落
    "metadata",             # 作者、机构、DOI、日期、版权等元信息
    "keywords",             # 关键词列表
    "reference",            # 参考文献条目
    "figure_caption",       # 图表标题/说明
    "table_caption",        # 表格标题/说明
    "header_footer",        # 页眉/页脚/页码
    "acknowledgment",       # 致谢
    "appendix",             # 附录
    "unknown",              # 无法确定
]

# ============================================================
# LLM Prompt 模板
# ============================================================

STRUCTURE_SYSTEM_PROMPT = """你是一位学术论文结构分析专家。你的任务是分析论文文本片段，识别其语义角色并整理排版。

请返回一个 JSON 对象，包含以下字段：
- "label": 段落角色标签（从下列标签中选择最匹配的一个）
- "section_name": 如果 label 是 section_header，给出章节名（如 "Introduction", "Methods", "Results", "Discussion", "Conclusion" 等）；否则为 null
- "reformatted": 排版整理后的文本（修复断词、合并多余换行，不改变原文措辞）

可选标签：
  "section_header"  - 章节标题（如 "1. Introduction", "Methods", "Related Work"）
  "abstract_header" - "Abstract" / "摘要" 这个词本身
  "abstract_body"   - 摘要正文内容
  "body"            - 普通正文段落
  "metadata"        - 作者姓名、机构、邮箱、DOI、投稿日期、版权声明
  "keywords"        - 关键词列表
  "reference"       - 参考文献条目
  "figure_caption"  - 图片/图表标题说明
  "header_footer"   - 页眉、页脚、页码等重复信息
  "acknowledgment"  - 致谢
  "appendix"        - 附录
  "unknown"         - 无法确定

排版要求：
1. 将属于同一段落的行合并为连续文本
2. 修复因 PDF 提取造成的断词（如 "con-\\nclusion" → "conclusion"）
3. 压缩多余空格和空行
4. 不修改措辞、不翻译、不删减实质内容
5. 公式/数学符号原样保留

重要：只返回 JSON，不要加任何解释、Markdown 标记或代码块包裹。"""


def build_structure_user_prompt(
    current_text: str,
    prev_contexts: list[dict],
    next_contexts: list[dict],
) -> str:
    """构建发给 LLM 的用户提示词，包含上下文。

    Args:
        current_text: 当前卡片的文本（需要被分析的那张）
        prev_contexts: 前序卡片 [{index, text, label, section_name}, ...]
        next_contexts: 后序卡片 [{index, text, label, section_name}, ...]

    Returns:
        格式化的提示词字符串。
    """
    parts = []

    # 已识别的文档结构摘要
    all_known = [c for c in prev_contexts if c.get("label")]
    if all_known:
        parts.append("【已识别的文档结构】（供参考，帮助判断当前位置）")
        for c in all_known:
            label = c["label"]
            section = c.get("section_name", "")
            preview = c.get("text", "")[:100].replace("\n", " ")
            parts.append(f"  Card {c['index']}: {label}" + (f" ({section})" if section else "") + f" | {preview}...")
        parts.append("")

    # 上文
    if prev_contexts:
        parts.append("【上文卡片】（仅用于辅助判断当前卡片的角色）")
        for c in prev_contexts:
            label_str = f" [已识别: {c['label']}]" if c.get("label") else ""
            parts.append(f"--- Card {c['index']}{label_str} ---")
            parts.append(c["text"][:400])
        parts.append("")

    # 当前卡片
    parts.append("【当前卡片 —— 请分析并返回 JSON】")
    parts.append(current_text[:5000])
    parts.append("")

    # 下文
    if next_contexts:
        parts.append("【下文卡片】（仅用于辅助判断当前卡片的角色）")
        for c in next_contexts:
            parts.append(f"--- Card {c['index']} ---")
            parts.append(c["text"][:400])

    return "\n".join(parts)


def parse_structure_response(raw: str) -> dict:
    """解析 LLM 返回的结构分析结果。

    容错策略：
    1. 尝试直接 JSON 解析
    2. 尝试提取 ```json ... ``` 或 ``` ... ``` 代码块
    3. 尝试提取第一个 { 到最后一个 } 之间的内容
    4. 全部失败则降级为纯文本排版模式

    Returns:
        {
            "label": str,
            "section_name": str | None,
            "reformatted": str,
            "parse_error": str | None,   # 非空表示解析有问题但已尽力
        }
    """
    if not raw or not raw.strip():
        return _fallback_result(raw, "LLM 返回为空")

    text = raw.strip()

    # 尝试 1：直接解析
    try:
        obj = json.loads(text)
        return _validate_and_normalize(obj)
    except json.JSONDecodeError:
        pass

    # 尝试 2：提取 ```json ... ``` 或 ``` ... ```
    code_patterns = [
        r'```json\s*\n?(.*?)\n?```',
        r'```\s*\n?(.*?)\n?```',
    ]
    for pattern in code_patterns:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(1).strip())
                return _validate_and_normalize(obj)
            except json.JSONDecodeError:
                pass

    # 尝试 3：提取第一个 { 到最后一个 }
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace >= 0 and last_brace > first_brace:
        try:
            obj = json.loads(text[first_brace:last_brace + 1])
            return _validate_and_normalize(obj)
        except json.JSONDecodeError:
            pass

    # 全部失败：降级为纯文本排版模式
    return _fallback_result(raw, "无法解析 LLM 返回的 JSON，降级为纯文本排版")


def _validate_and_normalize(obj: dict) -> dict:
    """校验并规范化结构化结果。"""
    label = obj.get("label", "body")
    if label not in SECTION_LABELS:
        label = "body"

    section_name = obj.get("section_name")
    if section_name is not None and not isinstance(section_name, str):
        section_name = None
    if isinstance(section_name, str) and not section_name.strip():
        section_name = None

    reformatted = obj.get("reformatted", "")
    if not reformatted or not isinstance(reformatted, str):
        reformatted = obj.get("text", "")  # 兼容旧格式

    return {
        "label": label,
        "section_name": section_name,
        "reformatted": reformatted,
        "parse_error": None,
    }


def _fallback_result(raw: str, error: str) -> dict:
    """当 JSON 解析失败时，返回降级结果——把原文当作 body 处理。"""
    return {
        "label": "body",
        "section_name": None,
        "reformatted": raw,
        "parse_error": error,
    }


# ============================================================
# QThread Worker（供 UI 层调用）
# ============================================================

class StructureFormatWorker(QThread):
    """后台线程：调用 LLM 进行结构识别 + 排版整理。

    Signals:
        done(int, dict): 成功，携带卡片索引和结构化结果
        err(int, str): 失败，携带卡片索引和错误消息
    """

    done = Signal(int, dict)
    err = Signal(int, str)

    def __init__(
        self,
        client: LLMClient,
        idx: int,
        current_text: str,
        prev_contexts: list[dict],
        next_contexts: list[dict],
    ) -> None:
        super().__init__()
        self._client = client
        self._idx = idx
        self._current_text = current_text
        self._prev_contexts = prev_contexts
        self._next_contexts = next_contexts

    def run(self) -> None:
        try:
            user_prompt = build_structure_user_prompt(
                self._current_text,
                self._prev_contexts,
                self._next_contexts,
            )
            messages = [
                {"role": "system", "content": STRUCTURE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            response = self._client.chat_sync(messages)
            result = parse_structure_response(response)
            self.done.emit(self._idx, result)
        except Exception as e:
            self.err.emit(self._idx, str(e))


# ============================================================
# 段落合并工具 —— 将小段落拼成 ~5000 字大卡片
# ============================================================

# 英文和中文的句子结束标记
_SENTENCE_END_RE = re.compile(
    r'(?<=[.!?。！？])\s+(?=[A-Z\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])'
)

# 不应在之前断句的前缀（避免 "et al." "i.e." 等被误判为句尾）
_SENTENCE_SAFE_PREFIXES = (
    'al', 'e.g', 'i.e', 'etc', 'vs', 'fig', 'eq', 'ref',
    'vol', 'no', 'pp', 'dr', 'mr', 'ms', 'prof',
)


def _safe_split_sentences(text: str) -> list[str]:
    """按句子边界切分文本，避免在缩写处误断。

    策略：先用正则粗切，再检查切分点是否在缩写词后（回退合并）。
    """
    parts = _SENTENCE_END_RE.split(text)
    if len(parts) <= 1:
        return [text]

    result = []
    buffer = parts[0]
    for part in parts[1:]:
        # 检查 buffer 末尾是否为缩写词
        last_word = buffer.rstrip().split()[-1].rstrip('.').lower() if buffer.rstrip().split() else ''
        if last_word in _SENTENCE_SAFE_PREFIXES:
            # 缩写，合并回去
            # 找到原始分隔符并还原
            m = _SENTENCE_END_RE.search(text)
            if m:
                sep = m.group(0)
                buffer = buffer + sep + part
            else:
                buffer = buffer + ' ' + part
        else:
            result.append(buffer)
            buffer = part
    if buffer:
        result.append(buffer)
    return result


def chunk_text_by_sentences(
    text: str,
    target_size: int = 5000,
    tolerance: int = 800,
) -> list[str]:
    """将文本按目标字数切分为卡片，保证不在句子中间切断。

    算法：
    1. 按句子边界切分全文
    2. 贪心累加句子，达到 target_size 时尝试在句子边界处切分
    3. 在 tolerance 范围内允许略超 target_size 以包含完整句子

    Args:
        text: 输入全文
        target_size: 目标每卡字符数（默认 5000）
        tolerance: 容差范围（超出 target_size 不超过此值则合并当前句子）

    Returns:
        字符串列表，每个约 target_size 字，在句子边界处断开。
    """
    if not text or not text.strip():
        return []

    sentences = _safe_split_sentences(text)
    if not sentences:
        return [text]

    chunks: list[str] = []
    buffer_parts: list[str] = []
    buffer_len = 0

    for sent in sentences:
        s = sent.strip()
        if not s:
            continue

        sent_len = len(s)

        if buffer_len > 0 and buffer_len >= target_size:
            # 已达标，检查能否再容纳当前句子（在容差内）
            if buffer_len + sent_len <= target_size + tolerance:
                buffer_parts.append(s)
                buffer_len += sent_len + 1
            else:
                # 切分
                chunks.append(' '.join(buffer_parts))
                buffer_parts = [s]
                buffer_len = sent_len
        else:
            buffer_parts.append(s)
            buffer_len += sent_len + 1  # +1 for joining space

    if buffer_parts:
        chunks.append(' '.join(buffer_parts))

    return chunks


def merge_paragraphs_into_chunks(
    paragraphs: list[dict],
    target_size: int = 5000,
) -> list[dict]:
    """将段落列表合并为 ~target_size 字的大卡片。

    策略（激进合并，完全交给 LLM 重新分类）：
    - 图片占位段保持独立
    - 其余所有文本段落（标题、正文、元信息、参考文献等）全部合并
    - 在句子边界处切开

    原因：regex 对标题/元信息的判断在参考文献区误判率极高，
    不如全部合并后由 LLM 统一识别，反而更准确。

    Args:
        paragraphs: 来自 PDFParser.extract_structured_paragraphs() 的段落列表
        target_size: 目标卡片大小（字符数）

    Returns:
        新的段落列表，文本段落被合并为大块。
    """
    if not paragraphs:
        return []

    result: list[dict] = []
    buffer_texts: list[str] = []
    buffer_page: int = 0
    buffer_bbox: tuple | None = None
    buffer_len = 0

    def _flush_buffer():
        nonlocal buffer_texts, buffer_page, buffer_bbox, buffer_len
        if not buffer_texts:
            return
        merged = '\n\n'.join(buffer_texts)
        sub_chunks = chunk_text_by_sentences(merged, target_size)
        for chunk in sub_chunks:
            result.append({
                'text': chunk,
                'page': buffer_page,
                'is_heading': False,
                'is_meta': False,
                'bbox': buffer_bbox or (0, 0, 0, 0),
            })
        buffer_texts = []
        buffer_page = 0
        buffer_bbox = None
        buffer_len = 0

    for para in paragraphs:
        # 图片占位 → 单独成卡
        if para.get('image_path'):
            _flush_buffer()
            result.append(para)
            continue

        text = para.get('text', '').strip()
        if not text:
            continue

        # 所有文本段落 → 累积到 buffer（不信任 regex 的 is_heading/is_meta 标签）
        buffer_texts.append(text)
        buffer_page = para.get('page', buffer_page)
        if buffer_bbox is None:
            buffer_bbox = para.get('bbox', (0, 0, 0, 0))
        else:
            b = para.get('bbox', (0, 0, 0, 0))
            buffer_bbox = (
                min(buffer_bbox[0], b[0]),
                min(buffer_bbox[1], b[1]),
                max(buffer_bbox[2], b[2]),
                max(buffer_bbox[3], b[3]),
            )
        buffer_len += len(text)

        # 达到目标大小 → 句子边界处切分输出
        if buffer_len >= target_size:
            merged = '\n\n'.join(buffer_texts)
            sub_chunks = chunk_text_by_sentences(merged, target_size)
            for chunk in sub_chunks:
                result.append({
                    'text': chunk,
                    'page': buffer_page,
                    'is_heading': False,
                    'is_meta': False,
                    'bbox': buffer_bbox or (0, 0, 0, 0),
                })
            buffer_texts = []
            buffer_page = 0
            buffer_bbox = None
            buffer_len = 0

    _flush_buffer()
    return result


# ============================================================
# 第三步：DeepSeek 整合 —— PyMuPDF全文 + Mimo结构 → 工整文档
# ============================================================

INTEGRATION_SYSTEM_PROMPT = """你是学术论文排版助手。给你两样材料，请整合成方便阅读的干净论文:

【材料A】PyMuPDF提取的论文原文(逐页, [第X页]标记)
【材料B】Mimo看图分析的每页视觉结构(JSON, 含每个区域的type、开头s、结尾e)

你的任务——让这篇论文"读起来舒服":
1. 段落边界要准: 材料B的s和e是每个区域的精确头尾锚点。在材料A中找到s开头的句子作为段落起点, 找到e结尾的句子作为段落终点, 中间所有文字属于同一段落。不要跨锚点合并或切断。
2. 修复断词和多余换行(con-\\nclusion→conclusion), 但保留段落间的分隔。
3. 去掉干扰: 材料B的note字段标注了页眉页脚内容(如"页眉有Cell Reports"), 从材料A中删除这些重复文字。
4. 标题醒目: 材料B type=heading的区域独占一行, 前后留空行。
5. 图表处理: 材料B page=image的整页图输出为 [图表页: 描述], 正文中的图表说明保留在原位。
6. 参考文献集中: 材料B type=ref的区域归拢到文末。

输出格式——在原文基础上调整, 每段前加极简标记:
  # 标题或章节名(type=heading)
  正文段落直接输出(type=body)
  -- 参考文献条目(type=ref)
  ;; 元信息(type=meta, 小字显示)

重要: 保留原文, 不概括不翻译不删减。只调整排版和段落归属。
输出即最终文本, 不要任何前言后记。"""


def build_integration_prompt(
    page_texts: dict[int, str],
    page_structures: dict[int, dict],
) -> str:
    """构建 DeepSeek 整合的 user prompt。

    Args:
        page_texts: {页码: PyMuPDF提取的全文}
        page_structures: {页码: Mimo返回的结构JSON}

    Returns:
        完整 user prompt 字符串。
    """
    parts = []

    # 材料A: PyMuPDF 全文
    parts.append("=" * 40)
    parts.append("【材料A】PyMuPDF 逐页提取的论文全文")
    parts.append("=" * 40)
    for pg in sorted(page_texts.keys()):
        parts.append(f"\n[第{pg}页]\n{page_texts[pg]}")

    # 材料B: Mimo 结构描述
    parts.append("\n\n" + "=" * 40)
    parts.append("【材料B】Mimo 视觉结构描述（每页JSON）")
    parts.append("=" * 40)
    for pg in sorted(page_structures.keys()):
        result = page_structures[pg]
        page_type = result.get("page") or result.get("role") or result.get("page_role") or "?"
        layout = result.get("layout") or "?"
        note = result.get("note") or result.get("special_notes") or ""
        parts.append(f"\n--- 第{pg}页 ---")
        parts.append(f"类型:{page_type} 布局:{layout}")
        if note:
            parts.append(f"备注:{note}")
        regions = result.get("regions") or result.get("elements") or []
        if regions:
            parts.append("区域(含头尾锚点):")
            for i, reg in enumerate(regions):
                rtype = reg.get("type") or reg.get("t") or "?"
                start = (reg.get("s") or reg.get("hint") or reg.get("h") or reg.get("text") or "")[:30]
                end = (reg.get("e") or "")[:30]
                end_str = f" → {end}" if end else ""
                parts.append(f"  [{i}] {rtype}: {start}{end_str}")

    return "\n".join(parts)


class TextIntegrationWorker(QThread):
    """后台线程：将 PyMuPDF 全文 + Mimo 结构发给 DeepSeek 做最终整合。

    Signals:
        done(str): 成功，携带整合后的论文全文
        err(str): 失败，携带错误消息
    """

    done = Signal(str)
    err = Signal(str)

    def __init__(
        self,
        client: LLMClient,
        page_texts: dict[int, str],
        page_structures: dict[int, dict],
    ) -> None:
        super().__init__()
        self._client = client
        self._page_texts = page_texts
        self._page_structures = page_structures

    def run(self) -> None:
        try:
            user_prompt = build_integration_prompt(
                self._page_texts, self._page_structures
            )
            messages = [
                {"role": "system", "content": INTEGRATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            # 整合任务输出较长，给 300s 超时
            response = self._client.chat_sync(messages, timeout=300.0)
            self.done.emit(response)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.err.emit(str(e))


# ============================================================
# 图像模式 —— 页面截图交给多模态模型识别结构
# ============================================================

IMAGE_STRUCTURE_PROMPT = """分析这张论文页面，返回JSON(只返回JSON):

{
  "page": "front/body/refs/image/blank",
  "layout": "single/double",
  "regions": [
    {"type": "heading/meta/body/ref", "s": "开头文字", "e": "结尾文字"}
  ],
  "note": "备注"
}

字段说明:
- page: front=标题作者摘要页, body=正文页, refs=参考文献页, image=整页图, blank=空白
- layout: 单栏还是双栏
- regions: 按从上到下阅读顺序列出每个视觉区域
  - type: heading(标题/章节名), meta(作者/单位/DOI), body(正文段落), ref(参考文献条目)
  - s: 该区域的前8个字; 标题写标题名; 图表描述内容(如"电镜照片")
  - e: 该区域的后8个字; 标题可省略; 正文必填
- note: 标注页眉页脚文字(供过滤用), 及异常(如"上半页文字下半页大图"); 无异常填null"""


def parse_image_structure_response(raw: str) -> dict:
    """解析多模态模型返回的 JSON 结构，容错处理。

    兼容两种格式：
    A. {page_role, elements: [...], reading_order: [...]}（标准格式）
    B. [{type, text, section}, ...]（简化数组格式）

    Returns:
        {
            "page_role": str,
            "elements": list[dict],
            "reading_order": list[int],
            "parse_error": str | None,
        }
    """
    if not raw or not raw.strip():
        return _empty_image_result("模型返回为空")

    text = raw.strip()

    # 收集所有可能的 JSON 提取结果
    candidates = [text]

    # 提取 ```json ... ``` 代码块
    for pat in [r'```json\s*\n?(.*?)\n?```', r'```\s*\n?(.*?)\n?```']:
        m = re.search(pat, text, re.DOTALL)
        if m:
            candidates.append(m.group(1).strip())

    # 提取最外层 JSON（第一个 { 到最后一个 } 或 第一个 [ 到最后一个 ]）
    for bracket_pair in [('{', '}'), ('[', ']')]:
        first = text.find(bracket_pair[0])
        last = text.rfind(bracket_pair[1])
        if first >= 0 and last > first:
            candidates.append(text[first:last + 1])

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue

        # 格式 A: {role/page_role/page, elements/regions, ...}
        if isinstance(obj, dict) and ("elements" in obj or "regions" in obj or "role" in obj or "page" in obj):
            elements_raw = obj.get("elements") or obj.get("regions") or []
            elements = []
            for item in elements_raw:
                if isinstance(item, dict):
                    etype = item.get("type") or item.get("t") or "body"
                    text = item.get("text") or item.get("hint") or item.get("h") or item.get("s") or ""
                    elem = {"type": etype, "text": text}
                    if "idx" in item:
                        elem["idx"] = item["idx"]
                    if "s" in item:
                        elem["s"] = item["s"]
                    if "e" in item:
                        elem["e"] = item["e"]
                    elements.append(elem)
            return {
                "page_role": obj.get("page_role") or obj.get("role") or obj.get("page") or "body",
                "elements": elements,
                "reading_order": obj.get("reading_order", []),
                "parse_error": None,
            }

        # 格式 B: [{type, text/hint/h/s, ...}, ...] 数组
        if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
            elements = []
            for item in obj:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("hint") or item.get("h") or item.get("s") or ""
                    etype = item.get("type") or item.get("t") or "body"
                    idx = item.get("idx")
                    elem = {"type": etype, "text": text, "section": item.get("section")}
                    if idx is not None:
                        elem["idx"] = idx
                    if "s" in item:
                        elem["s"] = item["s"]
                    if "e" in item:
                        elem["e"] = item["e"]
                    elements.append(elem)
            if elements:
                return {
                    "page_role": "body",
                    "elements": elements,
                    "reading_order": list(range(len(elements))),
                    "parse_error": None,
                }

        # 格式 C: {xxx} 但没有 elements 键（可能是单页简单结构）
        if isinstance(obj, dict) and len(obj) > 0:
            # 尝试把每个键值对当作一个元素
            elements = []
            for key, val in obj.items():
                if isinstance(val, str) and val.strip():
                    elements.append({"type": key, "text": val, "section": None})
            if elements:
                return {
                    "page_role": "body",
                    "elements": elements,
                    "reading_order": list(range(len(elements))),
                    "parse_error": None,
                }

    return _empty_image_result(f"无法解析 JSON: {text[:200]}...")


def _empty_image_result(error: str) -> dict:
    return {
        "page_role": "body",
        "elements": [],
        "reading_order": [],
        "parse_error": error,
    }


class ImageStructureWorker(QThread):
    """后台线程：将页面图片发送给多模态 LLM，返回结构化分析结果。

    Signals:
        done(int, dict): 成功，携带页码和结构化结果
        err(int, str): 失败，携带页码和错误消息
    """

    done = Signal(int, dict)
    err = Signal(int, str)

    def __init__(self, client: LLMClient, page_num: int, image_b64: str,
                 prompt: str = "") -> None:
        super().__init__()
        self._client = client
        self._page = page_num
        self._image_b64 = image_b64
        self._prompt = prompt or IMAGE_STRUCTURE_PROMPT

    def run(self) -> None:
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._prompt},
                        {"type": "image_url", "image_url": {"url": self._image_b64}},
                    ],
                }
            ]
            response = self._client.chat_sync(messages, timeout=120.0)
            if not response or not response.strip():
                print(f"[ImageWorker] 第{self._page}页空返回")
                self.err.emit(self._page, "Mimo 返回空内容")
                return
            result = parse_image_structure_response(response)
            if result.get("parse_error"):
                print(f"[ImageWorker] 第{self._page}页解析失败，原始返回(前300字): {response[:300]}")
            self.done.emit(self._page, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.err.emit(self._page, str(e))
