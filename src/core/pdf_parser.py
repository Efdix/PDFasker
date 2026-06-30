"""PDF 解析器 —— 列感知智能段落分割。

列检测 → 阅读顺序排序 → 多维度段落合并 → 标题/元信息识别 → 页眉页脚过滤。
"""

from __future__ import annotations

import io
import os
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import fitz  # PyMuPDF

if TYPE_CHECKING:
    from typing import Optional


# ============================================================
# 数据结构
# ============================================================

@dataclass
class TextSpan:
    """单个文本片段（PDF 中的 span）。"""
    text: str
    font: str = ""
    size: float = 10.0
    bold: bool = False
    italic: bool = False
    color: int = 0
    bbox: tuple = (0, 0, 0, 0)


@dataclass
class TextLine:
    """单行文本（由多个 span 组成）。"""
    text: str
    bbox: tuple          # (x0, y0, x1, y1)
    spans: list = field(default_factory=list)
    font_size: float = 10.0
    is_bold: bool = False
    page: int = 0


@dataclass
class Paragraph:
    """段落对象。"""
    text: str
    page: int
    is_heading: bool = False
    is_meta: bool = False
    image_path: str = ""
    font_size: float = 10.0
    is_bold: bool = False
    bbox: tuple = (0, 0, 0, 0)


# ============================================================
# 工具函数
# ============================================================

def _clean_text(text: str) -> str:
    """修复 PDF 提取造成的断词和多余空白。"""
    # 连字符跨行断词 → 合并
    text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)
    # 连字符 + 空白断词 → 合并
    text = re.sub(r'(\w+)-[ \t]*\n[ \t]*(\w+)', r'\1\2', text)
    # 压缩空格
    text = re.sub(r'[ \t]+', ' ', text)
    # 压缩连续空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 去除每行首尾空白
    return '\n'.join(line.strip() for line in text.split('\n')).strip()


def _bbox_center_x(bbox: tuple) -> float:
    """计算 bbox 的水平中心坐标。"""
    return (bbox[0] + bbox[2]) / 2


# ============================================================
# 列检测器
# ============================================================

class ColumnDetector:
    """基于 x 坐标聚类检测文本列布局。"""

    def __init__(self, x_tolerance: float = 30) -> None:
        self.x_tolerance = x_tolerance

    def detect(self, lines: list[TextLine]) -> list[list[TextLine]]:
        """按 x 中心聚类分列，返回阅读顺序的列列表。"""
        if not lines:
            return []

        centers = [_bbox_center_x(line.bbox) for line in lines]
        if len(centers) <= 1:
            return [lines]

        # x 中心排序后贪心聚类
        sorted_centers = sorted(centers)
        clusters: list[list[float]] = []
        current = [sorted_centers[0]]

        for c in sorted_centers[1:]:
            if c - current[-1] <= self.x_tolerance:
                current.append(c)
            else:
                if len(current) >= 2:
                    clusters.append(current)
                current = [c]
        if len(current) >= 2:
            clusters.append(current)

        if len(clusters) <= 1:
            return [lines]

        # 为每个聚类计算 x 范围
        col_ranges = [(min(c), max(c)) for c in clusters]
        col_ranges.sort(key=lambda r: r[0])

        # 将每行分配到最近的列
        columns: dict[int, list[TextLine]] = defaultdict(list)
        for line in lines:
            cx = _bbox_center_x(line.bbox)
            best_col = 0
            best_dist = float('inf')
            for i, (lo, hi) in enumerate(col_ranges):
                mid = (lo + hi) / 2
                dist = abs(cx - mid)
                if dist < best_dist:
                    best_dist = dist
                    best_col = i
            columns[best_col].append(line)

        # 每列内按 y 坐标排序
        result = []
        for i in sorted(columns.keys()):
            result.append(sorted(columns[i], key=lambda line: line.bbox[1]))

        return result


# ============================================================
# 主解析器
# ============================================================

class PDFParser:
    """列感知智能段落分割器。

    特性：
    - 自动检测多列排版并按阅读顺序重组
    - 识别标题、元信息（作者/单位）
    - 过滤页眉页脚重复内容
    - 提取嵌入图片并保持原位
    """

    HEADER_RATIO = 0.08      # 页面顶部视为页眉的比例
    FOOTER_RATIO = 0.08      # 页面底部视为页脚的比例
    PARA_GAP_RATIO = 1.8     # 行间距大于行高此倍数视为段间距
    SENTENCE_SPLIT_THRESHOLD = 500
    HEADING_MAX_LEN = 150    # 标题的最大字符数
    META_MAX_LEN = 500       # 元信息段落的最大字符数

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self._doc = fitz.open(file_path)
        self._full_text: str | None = None
        self._image_dir: str = ""
        self._all_lines: list[TextLine] | None = None
        self._images: list[dict] | None = None   # 图片提取缓存
        self._blocks: list[dict] | None = None   # 块提取缓存（兼容旧 API）

    # ---- 公共 API ----

    @property
    def page_count(self) -> int:
        return len(self._doc)

    @property
    def metadata(self) -> dict:
        return self._doc.metadata

    def get_toc(self) -> list[dict]:
        """提取 PDF 目录/大纲"""
        toc = self._doc.get_toc(simple=False)
        if not toc:
            return []
        result = []
        for item in toc:
            level, title, page = item[0], item[1], item[2]
            if title.strip():
                result.append({"level": level, "title": title.strip(), "page": page})
        return result

    def set_image_output_dir(self, directory: str):
        self._image_dir = directory
        os.makedirs(directory, exist_ok=True)

    def close(self):
        self._doc.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ========== 页面渲染（供多模态识别用） ==========

    def render_page_to_base64(self, page_num: int, dpi: int = 150) -> str:
        """将指定页面渲染为 PNG 图片的 base64 编码字符串。

        Args:
            page_num: 页码（1-based，与 PDF 页码一致）
            dpi: 渲染分辨率（默认 150 DPI，平衡清晰度与文件大小）

        Returns:
            data:image/png;base64,... 格式的字符串，可直接嵌入 API 请求。
        """
        import base64
        page = self._doc[page_num - 1]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        b64 = base64.b64encode(img_bytes).decode("ascii")
        return f"data:image/png;base64,{b64}"

    def render_all_pages_to_base64(self, dpi: int = 150) -> list[str]:
        """渲染所有页面为 base64 PNG 列表（批量调用用）。"""
        return [self.render_page_to_base64(i + 1, dpi) for i in range(len(self._doc))]

    def extract_text_by_page(self) -> dict[int, str]:
        """按页提取纯文本，返回 {页码: 文本} 字典。

        与 extract_full_text 不同，此方法不添加页码标记，
        适合作为原始素材传给 DeepSeek 做整合。
        """
        result: dict[int, str] = {}
        for i, page in enumerate(self._doc, 1):
            text = page.get_text()
            if text.strip():
                result[i] = text.strip()
        return result

    # ========== 文本提取 ==========

    def extract_full_text(self) -> str:
        if self._full_text is not None:
            return self._full_text
        parts = []
        for i, page in enumerate(self._doc, 1):
            text = page.get_text()
            if text.strip():
                parts.append(f"[第 {i} 页]\n{text.strip()}")
        self._full_text = "\n\n".join(parts)
        return self._full_text

    # ---- 行级提取 ----

    def _extract_all_lines(self) -> list[TextLine]:
        if self._all_lines is not None:
            return self._all_lines

        lines = []
        for page_num, page in enumerate(self._doc, 1):
            blocks_data = page.get_text("dict")["blocks"]
            for block in blocks_data:
                if block["type"] != 0:
                    continue
                for line_data in block.get("lines", []):
                    spans = []
                    full_text_parts = []
                    max_font = 0
                    is_bold = False

                    for span_data in line_data.get("spans", []):
                        text = span_data.get("text", "")
                        size = span_data.get("size", 10.0)
                        flags = span_data.get("flags", 0)

                        full_text_parts.append(text)
                        max_font = max(max_font, size)
                        if flags & 2:
                            is_bold = True

                        spans.append(TextSpan(
                            text=text,
                            font=span_data.get("font", ""),
                            size=size,
                            bold=bool(flags & 2),
                            italic=bool(flags & 1),
                            color=span_data.get("color", 0),
                            bbox=tuple(span_data.get("bbox", (0, 0, 0, 0)))
                        ))

                    full_text = "".join(full_text_parts).strip()
                    if full_text:
                        lines.append(TextLine(
                            text=full_text,
                            bbox=tuple(line_data["bbox"]),
                            spans=spans,
                            font_size=max_font,
                            is_bold=is_bold,
                            page=page_num,
                        ))

        self._all_lines = lines
        return lines

    # ---- 结构化段落 ----

    def extract_structured_paragraphs(self, skip_images: bool = False) -> list[dict]:
        """列感知智能分段 → [{text, page, is_heading, is_meta, image_path, bbox}]"""
        all_lines = self._extract_all_lines()
        if not all_lines:
            return []

        # 按页分组
        pages = defaultdict(list)
        for line in all_lines:
            pages[line.page].append(line)

        # 收集图片信息
        images_by_page = {}
        if not skip_images:
            for img in self.extract_images():
                page = img["page"]
                if page not in images_by_page:
                    images_by_page[page] = []
                images_by_page[page].append(img)

        # 逐页处理
        all_paragraphs: list[Paragraph] = []
        column_detector = ColumnDetector()

        for page_num in sorted(pages.keys()):
            page_lines = pages[page_num]
            page_obj = self._doc[page_num - 1]
            page_height = page_obj.rect.height

            # 页眉/页脚区域
            header_limit = page_height * self.HEADER_RATIO
            footer_start = page_height * (1 - self.FOOTER_RATIO)

            # 分离正文行与页眉/页脚行
            body_lines = []
            header_texts = []
            footer_texts = []

            for line in page_lines:
                y = line.bbox[1]
                if y < header_limit:
                    header_texts.append(line.text.strip().lower())
                elif y > footer_start:
                    footer_texts.append(line.text.strip().lower())
                else:
                    body_lines.append(line)

            # 检测列
            columns = column_detector.detect(body_lines)

            # 逐列处理
            page_paras = []
            for col_lines in columns:
                if not col_lines:
                    continue
                col_paras = self._lines_to_paragraphs(col_lines, page_num)
                page_paras.extend(col_paras)

            # 过滤页眉/页脚重复文本
            page_paras = self._filter_repeating_headers(
                page_paras, header_texts, footer_texts
            )

            # 插入图片
            if page_num in images_by_page:
                for img_info in images_by_page[page_num]:
                    img_para = Paragraph(
                        text="", page=page_num,
                        image_path=img_info.get("path", ""),
                        bbox=img_info.get("bbox", (0, 0, 0, 0))
                    )
                    # 找到最接近图片 y 位置的插入点
                    img_y = img_info.get("bbox", (0, 0, 0, 0))[1]
                    insert_idx = len(page_paras)
                    for idx, p in enumerate(page_paras):
                        if p.bbox[1] > img_y:
                            insert_idx = idx
                            break
                    page_paras.insert(insert_idx, img_para)

            all_paragraphs.extend(page_paras)

        # 后处理
        all_paragraphs = self._post_process_split(all_paragraphs)
        all_paragraphs = self._post_process_section_split(all_paragraphs)
        all_paragraphs = [
            p for p in all_paragraphs
            if p.text.strip() or p.image_path
        ]

        # 转回 dict 格式
        return [
            {
                "text": _clean_text(p.text),
                "page": p.page,
                "is_heading": p.is_heading,
                "is_meta": p.is_meta,
                "image_path": p.image_path,
                "bbox": p.bbox,
            }
            for p in all_paragraphs
        ]

    def _lines_to_paragraphs(
        self, lines: list[TextLine], page_num: int
    ) -> list[Paragraph]:
        """将一列中的文本行智能合并为段落"""
        if not lines:
            return []

        paragraphs = []
        current_lines = []
        current_fonts = []
        current_bbox = None

        for i, line in enumerate(lines):
            text = line.text.strip()
            if not text:
                continue

            should_break = False

            if current_lines:
                prev_line = lines[i - 1]
                gap = line.bbox[1] - prev_line.bbox[3]
                avg_font = statistics.mean(current_fonts) if current_fonts else line.font_size
                line_h = line.bbox[3] - line.bbox[1]

                # 信号1：行间距显著大于行高
                if gap > max(line_h, avg_font) * self.PARA_GAP_RATIO:
                    should_break = True

                # 信号2：字号突变（增大 → 新段落/标题）
                if line.font_size > avg_font * 1.3 and line.font_size > 11:
                    should_break = True

                # 信号3：左侧缩进突变（首行缩进 → 新段落）
                if line.bbox[0] - prev_line.bbox[0] > avg_font * 1.5:
                    should_break = True

                # 信号4：上一行以句号结束且当前行以大写字母/数字开头
                prev_ends = prev_line.text.strip()[-1:] if prev_line.text.strip() else ''
                curr_starts = text[0] if text else ''
                if prev_ends in '.!?。！？' and (curr_starts.isupper() or curr_starts.isdigit()):
                    prev_words = prev_line.text.strip().split()
                    if prev_words and not any(
                        prev_words[-1].lower().startswith(w)
                        for w in ('et', 'e.g', 'i.e', 'etc', 'al', 'vs')
                    ):
                        should_break = True

                # 信号5：编号模式开头（新段落）
                if re.match(r'^\s*(?:\d+[\.\)]\s+|[A-Z][\.\)]\s+|[IVX]+[\.\)]\s+)', text):
                    if len(text) > 20:
                        should_break = True

            if should_break and current_lines:
                para = self._build_paragraph(current_lines, current_fonts, current_bbox, page_num)
                if para:
                    paragraphs.append(para)
                current_lines = []
                current_fonts = []
                current_bbox = None

            current_lines.append(line)
            current_fonts.append(line.font_size)
            if current_bbox is None:
                current_bbox = line.bbox
            else:
                current_bbox = (
                    min(current_bbox[0], line.bbox[0]),
                    min(current_bbox[1], line.bbox[1]),
                    max(current_bbox[2], line.bbox[2]),
                    max(current_bbox[3], line.bbox[3]),
                )

        # 最后一组
        if current_lines:
            para = self._build_paragraph(current_lines, current_fonts, current_bbox, page_num)
            if para:
                paragraphs.append(para)

        return paragraphs

    def _build_paragraph(
        self, lines: list[TextLine], fonts: list[float],
        bbox: tuple, page_num: int
    ) -> Paragraph | None:
        """从一组行构建段落对象，返回 None 表示空段落。"""
        text = "\n".join(l.text.strip() for l in lines)
        if not text.strip():
            return None

        avg_font = statistics.mean(fonts) if fonts else 10.0
        max_font = max(fonts) if fonts else 10.0
        is_bold = any(l.is_bold for l in lines)

        is_heading = self._detect_heading(text, fonts, is_bold)
        is_meta = self._detect_metadata(text)

        return Paragraph(
            text=text, page=page_num,
            is_heading=is_heading, is_meta=is_meta,
            font_size=max_font, is_bold=is_bold,
            bbox=bbox,
        )

    # ---- 标题检测（评分制） ----

    def _detect_heading(self, text: str, fonts: list[float], is_bold: bool) -> bool:
        t = text.strip()
        if not t or len(t) > self.HEADING_MAX_LEN:
            return False

        max_font = max(fonts) if fonts else 10
        avg_font = statistics.mean(fonts) if fonts else 10

        score = 0

        # 字号显著大于正文（正文通常 9-11pt）
        if max_font >= 15:
            score += 3
        elif max_font >= 13:
            score += 2
        elif max_font >= 11.5 and len(t) < 80:
            score += 1

        # 粗体
        if is_bold and len(t) < 120:
            score += 2

        # 全大写（英文标题常见）
        if t.isupper() and len(t) < 100:
            score += 2

        # 编号模式
        if re.match(
            r'^\s*(?:\d+[\.\)]\s+|[A-Z][\.\)]\s+|[IVX]+[\.\)]\s+|[①②③④⑤⑥⑦⑧⑨⑩]\s*)',
            t
        ):
            score += 2

        # 短文本
        if len(t) < 60:
            score += 1
        elif len(t) < 40:
            score += 2

        # 章节名匹配
        if self._is_section_header(t):
            score += 3

        # 不含完整句子结构
        if not re.search(r'[.!?。！？]', t):
            score += 1

        # 首字母大写或数字开头
        if t[0].isupper() or t[0].isdigit():
            score += 1

        return score >= 4

    # ---- 元信息检测（评分制） ----

    def _detect_metadata(self, text: str) -> bool:
        t = text.strip()
        if not t or len(t) > self.META_MAX_LEN:
            return False

        score = 0

        # 邮箱
        if re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', t):
            score += 3
        # DOI
        if re.search(r'10\.\d{4,}/', t):
            score += 3
        # 日期/投稿信息
        if re.match(
            r'^(Received|Accepted|Published|Submitted|Date|Posted|Revised)',
            t, re.IGNORECASE
        ):
            score += 3
        # 版权/会议/出版社
        if re.search(
            r'(©|Copyright|All\s+rights\s+reserved|IEEE|ACM|Proceedings|'
            r'Conference|Workshop|Symposium|Springer|Elsevier|arXiv|Preprint)',
            t
        ):
            score += 3
        # 通讯作者标注
        if re.search(
            r'(corresponding\s+author|email:|E-mail:|✉|†|‡|⊛|⍟)',
            t, re.IGNORECASE
        ):
            score += 2
        # Keywords / Index Terms
        if re.match(
            r'^(Keywords|Index\s+Terms|Key\s+words|MSC|PACS|JEL|ACM\s+Reference)',
            t, re.IGNORECASE
        ):
            score += 3
        # 作者列表模式
        if re.search(r'^[\w\-\s,;．·•\d†‡*⊛⍟]+$', t) and len(t) < 300 and t.count(',') >= 2:
            score += 2
        # 纯数字逗号列表（上标机构编号）
        if re.match(r'^[\d,\s]+$', t) and len(t) < 50:
            score += 1
        # URL
        if re.search(r'https?://', t):
            score += 2
        # 许可证
        if re.search(r'(CC\s*BY|Creative\s+Commons|Open\s+Access|License)', t, re.IGNORECASE):
            score += 2
        # 孤立页码
        if re.match(r'^\d{1,4}$', t) and len(t) <= 4:
            score += 1

        return score >= 3

    # ---- 章节标题匹配 ----

    # 常见章节标题关键词（独立成行时）
    _SECTION_KEYWORDS = [
        "Abstract", "Introduction", "Related Work", "Literature Review",
        "Background", "Motivation", "Problem Statement", "Problem Formulation",
        "Method", "Methods", "Methodology", "Approach",
        "Proposed Method", "Proposed Approach", "Proposed Framework", "Proposed Model",
        "Experiment", "Experiments", "Experimental Setup", "Experimental Design",
        "Experimental Results", "Experimental Evaluation", "Implementation",
        "Result", "Results", "Results and Discussion", "Results and Analysis",
        "Evaluation", "Findings", "Performance",
        "Discussion", "Analysis", "Ablation Study", "Ablation Studies", "Case Study",
        "Conclusion", "Conclusions", "Summary", "Future Work", "Outlook", "Limitations",
        "References", "Bibliography", "Acknowledgments", "Acknowledgement",
        "Appendix", "Appendices", "Supplementary", "Supplemental",
        "Data Availability", "Code Availability", "Author Contributions",
        "Conflict of Interest", "Declaration",
        "摘要", "引言", "绪论", "前言", "背景", "相关工作", "文献综述", "问题描述", "研究动机",
        "方法", "方法论", "实验", "实验设计", "实验方法", "实验设置", "实验分析", "模型", "框架",
        "结果", "结果与讨论", "结果分析", "评估", "发现", "主要发现", "性能评估",
        "讨论", "结论", "总结", "展望", "未来工作", "不足与展望", "消融实验", "案例分析",
        "参考文献", "致谢", "附录", "补充材料",
        "数据可用性", "代码可用性", "作者贡献", "利益冲突",
    ]

    @staticmethod
    def _extract_section_keyword(text: str) -> tuple[str, str]:
        """若文本以章节关键词开头后跟 : . 空格，返回 (关键词, 剩余文本)，否则 ('', '')"""
        t = text.strip()
        for kw in PDFParser._SECTION_KEYWORDS:
            m = re.match(r'(' + re.escape(kw) + r')\s*[:：.\s]\s*(.+)', t, re.IGNORECASE)
            if m:
                return m.group(1), m.group(2)
        return "", ""

    @staticmethod
    def _is_section_header(text: str) -> bool:
        """检测纯标题行 或 以标题关键词开头后跟 : . 空格 的长文本"""
        t = text.strip()
        if not t:
            return False

        # 短文本（≤120 字符）：精确匹配或编号章节
        if len(t) <= 120:
            for kw in PDFParser._SECTION_KEYWORDS:
                if t.lower() == kw.lower():
                    return True
            # 编号章节：如 "1. Introduction", "第三章 方法"
            if re.match(
                r'^\s*(?:\d+\.?\s*|[IVX]+\.\s*|第[一二三四五六七八九十\d]+[章节])\s*\w+', t
            ):
                return True

        # 长文本（>120 字符）：检测是否以章节标题关键词开头（后跟 : . 空格）
        for kw in PDFParser._SECTION_KEYWORDS:
            pattern = r'^(' + re.escape(kw) + r')\s*[:：.\s]'
            if re.match(pattern, t, re.IGNORECASE):
                return True

        return False

    # ---- 页眉/页脚过滤 ----

    def _filter_repeating_headers(
        self, paragraphs: list[Paragraph],
        header_texts: list[str], footer_texts: list[str],
    ) -> list[Paragraph]:
        """过滤跨页重复的页眉/页脚文本"""
        if not paragraphs:
            return paragraphs

        header_set = set(header_texts)
        footer_set = set(footer_texts)

        # 统计短文本跨页出现次数
        text_counter = defaultdict(int)
        for p in paragraphs:
            t = p.text.strip().lower()
            if t and len(t) < 100:
                text_counter[t] += 1

        result = []
        for p in paragraphs:
            t_lower = p.text.strip().lower()
            # 多页重复出现的短文本 → 标记为元信息
            if text_counter.get(t_lower, 0) >= 3 and len(p.text.strip()) < 80:
                p.is_meta = True
                if re.match(r'^\d{1,4}$', p.text.strip()):
                    continue  # 纯页码直接丢弃
            # 在页眉/页脚集合中
            if t_lower in header_set or t_lower in footer_set:
                if len(p.text.strip()) < 60:
                    p.is_meta = True
            result.append(p)

        return result

    # ---- 后处理 ----

    def _post_process_split(self, paragraphs: list[Paragraph]) -> list[Paragraph]:
        result = []
        for para in paragraphs:
            if para.image_path or para.is_heading or para.is_meta:
                result.append(para)
                continue
            if len(para.text) < self.SENTENCE_SPLIT_THRESHOLD:
                result.append(para)
                continue

            sentences = re.split(
                r'(?<=[.!?])\s+(?=[A-Z])|(?<=[。！？])\s*|(?<=[.!?])\s+(?=[\u4e00-\u9fff])',
                para.text
            )

            buffer = ""
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                if len(buffer) + len(s) < self.SENTENCE_SPLIT_THRESHOLD:
                    buffer = (buffer + " " + s).strip() if buffer else s
                else:
                    if buffer:
                        result.append(Paragraph(
                            text=buffer, page=para.page,
                            bbox=para.bbox, font_size=para.font_size,
                        ))
                    buffer = s
            if buffer:
                result.append(Paragraph(
                    text=buffer, page=para.page,
                    bbox=para.bbox, font_size=para.font_size,
                ))
        return result

    def _post_process_section_split(self, paragraphs: list[Paragraph]) -> list[Paragraph]:
        result = []
        for para in paragraphs:
            if para.image_path or para.is_heading or para.is_meta:
                result.append(para)
                continue

            lines = para.text.split('\n')
            buffer_lines = []
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    buffer_lines.append(line)
                    continue

                # 优先检查：该行是否以章节关键词开头后跟正文
                kw, rest = PDFParser._extract_section_keyword(stripped)
                if kw:
                    if buffer_lines:
                        result.append(Paragraph(
                            text='\n'.join(buffer_lines), page=para.page,
                            bbox=para.bbox, font_size=para.font_size,
                        ))
                        buffer_lines = []
                    result.append(Paragraph(
                        text=kw, page=para.page,
                        is_heading=True, bbox=para.bbox, font_size=para.font_size,
                    ))
                    if rest:
                        buffer_lines.append(rest)
                    continue

                # 短行精确匹配标题
                if self._is_section_header(stripped) and len(stripped) <= 120:
                    if buffer_lines:
                        result.append(Paragraph(
                            text='\n'.join(buffer_lines), page=para.page,
                            bbox=para.bbox, font_size=para.font_size,
                        ))
                        buffer_lines = []
                    result.append(Paragraph(
                        text=stripped, page=para.page,
                        is_heading=True, bbox=para.bbox, font_size=para.font_size,
                    ))
                else:
                    buffer_lines.append(line)
            if buffer_lines:
                result.append(Paragraph(
                    text='\n'.join(buffer_lines), page=para.page,
                    bbox=para.bbox, font_size=para.font_size,
                ))
        return result

    # ---- 图片提取 ----

    def extract_images(self) -> list[dict]:
        if self._images is not None:
            return self._images

        self._images = []
        for page_num, page in enumerate(self._doc, 1):
            image_list = page.get_images(full=True)
            for img_idx, img_info in enumerate(image_list):
                xref = img_info[0]
                try:
                    base_image = self._doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    ext = base_image["ext"]

                    # 获取图片在页面上的位置
                    img_rects = page.get_image_rects(xref)
                    bbox = (0, 0, 0, 0)
                    if img_rects:
                        r = img_rects[0]
                        bbox = (r.x0, r.y0, r.x1, r.y1)

                    img_path = ""
                    if self._image_dir:
                        img_filename = f"page{page_num}_img{img_idx}.{ext}"
                        img_path = os.path.join(self._image_dir, img_filename)
                        with open(img_path, "wb") as f:
                            f.write(image_bytes)

                    self._images.append({
                        "page": page_num,
                        "index": img_idx,
                        "path": img_path,
                        "width": base_image["width"],
                        "height": base_image["height"],
                        "ext": ext,
                        "bbox": bbox,
                    })
                except Exception:
                    continue

        return self._images

    # ---- 兼容旧 API ----

    def extract_blocks(self) -> list[dict]:
        if self._blocks is not None:
            return self._blocks

        self._blocks = []
        for page_num, page in enumerate(self._doc, 1):
            blocks_data = page.get_text("dict")["blocks"]
            for block in blocks_data:
                if block["type"] == 0:
                    for line in block.get("lines", []):
                        text_parts = []
                        max_font = 0
                        for span in line.get("spans", []):
                            text_parts.append(span["text"])
                            max_font = max(max_font, span.get("size", 10))
                        full_text = "".join(text_parts).strip()
                        if full_text:
                            bbox = line["bbox"]
                            self._blocks.append({
                                "page": page_num,
                                "type": "text",
                                "text": full_text,
                                "bbox": bbox,
                                "font_size": max_font,
                                "x": bbox[0],
                                "y": bbox[1],
                            })
                elif block["type"] == 1:
                    bbox = block["bbox"]
                    self._blocks.append({
                        "page": page_num,
                        "type": "image_placeholder",
                        "text": "[图片]",
                        "bbox": bbox,
                        "font_size": 0,
                        "x": bbox[0],
                        "y": bbox[1],
                    })
        return self._blocks

    # 兼容旧方法名
    def _is_heading(self, text: str, fonts: list[float]) -> bool:
        return self._detect_heading(text, fonts, bool(fonts and max(fonts) > 12))

    def _is_metadata(self, text: str) -> bool:
        return self._detect_metadata(text)
