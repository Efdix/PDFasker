"""PDF 阅读器面板 —— 段落卡片 / 图片展示 / 中英对照 / 追问"""

import os, base64, re, time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QPushButton,
    QLabel, QFrame, QFileDialog, QTextEdit, QSizePolicy,
    QCheckBox, QApplication, QLineEdit, QMenu, QInputDialog,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QEvent, QSize
from PySide6.QtGui import QFont, QPixmap, QTextDocument

from ..core.section_splitter import StructureFormatWorker, ImageStructureWorker, IMAGE_STRUCTURE_PROMPT, TextIntegrationWorker
from ..utils.layout import calc_layout_height

# ---- 常量 ----

PLACEHOLDER_TEXT = (
    "📄 从左侧论文库选择或拖拽 PDF 开始阅读\n\n"
    "• 段落式排版，清晰可读\n"
    "• 图片自动提取展示\n"
    "• 英文段落一键中英对照\n"
    "• 章节标题自动识别高亮\n"
    "• 作者/单位等元信息自动淡化"
)

CHECKBOX_STYLE = (
    "QCheckBox { color: #8a8ea6; font-size: 12px; font-weight: 600; spacing: 8px; }"
    "QCheckBox::indicator { width: 18px; height: 18px; }"
    "QCheckBox::indicator:unchecked { border: 2px solid #515479; border-radius: 4px; background: #1e2030; }"
    "QCheckBox::indicator:unchecked:hover { border-color: #7aa2f7; background: #252740; }"
    "QCheckBox::indicator:checked { border: 2px solid #7aa2f7; border-radius: 4px; background: #7aa2f7; }"
)


# ---- 后台工作线程 ----

class ImageExplainWorker(QThread):
    done = Signal(str)
    err = Signal(str)

    def __init__(self, client, image_path: str):
        super().__init__()
        self._c = client
        self._p = image_path

    def run(self):
        try:
            with open(self._p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            r = self._c.chat_sync([{
                "role": "user",
                "content": [
                    {"type": "text", "text": "请详细解读这张学术论文中的图片/图表。说明它展示的内容、关键数据趋势、以及它在论文中的作用。请用中文回答。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ]
            }])
            self.done.emit(r)
        except Exception as e:
            self.err.emit(str(e))


class TranslationWorker(QThread):
    finished = Signal(int, str)
    error = Signal(int, str)

    def __init__(self, client, idx: int, text: str):
        super().__init__()
        self._c = client; self._idx = idx; self._text = text

    def run(self):
        try:
            r = self._c.chat_sync([
                {"role": "system", "content": "你是学术论文翻译助手。将以下段落译成中文。要求：术语准确，首次出现保留英文括号注中文；保持段落结构；自然流畅；只输出译文。"},
                {"role": "user", "content": self._text},
            ])
            self.finished.emit(self._idx, r)
        except Exception as e:
            self.error.emit(self._idx, str(e))


FORMAT_PROMPT = """你是学术论文排版助手。请对以下从 PDF 提取的原始文本进行整理。

要求：
1. 修复因 PDF 提取造成的多余换行——将属于同一段落的行合并为连续文本
2. 删除行内多余的连字符断词（如 "con-\nclusion" → "conclusion"）
3. 判断内容类型，在开头添加对应标记（只添加标记，不删除原文）：
   - 作者姓名列表/通讯地址/邮箱 → 添加前缀 [作者信息]
   - 出版信息/版权声明/投稿日期/DOI/网址 → 添加前缀 [出版信息]
   - 关键词列表/分类号 → 保留原样
4. 正文内容只调整换行和断词，不修改措辞、不翻译、不删减
5. 公式/数学符号原样保留
6. 直接输出整理后的文本，不要加任何解释或前言

原始文本：
{text}"""


class FormatWorker(QThread):
    done = Signal(int, str)
    err = Signal(int, str)

    def __init__(self, client, idx: int, text: str):
        super().__init__()
        self._c = client
        self._idx = idx
        self._text = text

    def run(self):
        try:
            r = self._c.chat_sync([
                {"role": "user", "content": FORMAT_PROMPT.format(text=self._text)}
            ])
            self.done.emit(self._idx, r)
        except Exception as e:
            self.err.emit(self._idx, str(e))


# 合并排版提示词
MERGE_FORMAT_PROMPT = """你是学术论文排版助手。以下是从 PDF 提取的几段文本，它们原本属于同一个段落，但因 PDF 排版问题被切断了。请将它们合并整理为一段完整、连贯的文本。

要求：
1. 将各段内容按逻辑顺序融合为一段连续文本，消除断裂感
2. 修复因 PDF 提取造成的多余换行和断词（如 "con-\nclusion" → "conclusion"）
3. 如果合并后发现连续有重复的句子或短语（PDF 跨页重复），只保留一次
4. 判断内容类型，在开头添加对应标记（只添加标记，不删除原文）：
   - 作者姓名列表/通讯地址/邮箱 → 添加前缀 [作者信息]
   - 出版信息/版权声明/投稿日期/DOI/网址 → 添加前缀 [出版信息]
5. 不修改措辞、不翻译、不删减实质内容
6. 直接输出合并整理后的完整段落，不要加任何解释

各段文本（按顺序）：
{merged_text}"""


class MergeWorker(QThread):
    done = Signal(str)
    err = Signal(str)

    def __init__(self, client, texts: list[str]):
        super().__init__()
        self._c = client
        self._texts = texts

    def run(self):
        try:
            merged_input = "\n\n---[分段符]---\n\n".join(
                f"[段{i+1}] {t}" for i, t in enumerate(self._texts)
            )
            r = self._c.chat_sync([
                {"role": "user", "content": MERGE_FORMAT_PROMPT.format(merged_text=merged_input)}
            ])
            self.done.emit(r)
        except Exception as e:
            self.err.emit(str(e))


class ImageLoadWorker(QThread):
    images_ready = Signal(list)

    def __init__(self, parser):
        super().__init__()
        self._parser = parser

    def run(self):
        try:
            imgs = self._parser.extract_images()
            self.images_ready.emit(imgs)
        except Exception:
            self.images_ready.emit([])


# ---- 段落卡片 ----

STRUCTURE_KEYWORDS = [
    # 英文
    "Abstract", "Introduction", "Related Work", "Background",
    "Method", "Methods", "Methodology", "Experimental", "Experiment",
    "Results", "Result", "Discussion", "Conclusion", "Conclusions",
    "References", "Acknowledgments", "Acknowledgement", "Appendix",
    "Supplementary", "Data Availability", "Code Availability",
    "Author Contributions", "Conflict of Interest",
    # 中文
    "摘要", "引言", "绪论", "前言", "背景", "相关工作", "文献综述",
    "方法", "方法论", "实验", "实验方法", "实验设计",
    "结果", "结果与讨论", "讨论", "结论", "总结", "展望",
    "参考文献", "致谢", "附录", "补充材料",
    "数据可用性", "代码可用性", "作者贡献", "利益冲突",
]

def _highlight_keywords(text: str) -> str:
    """对学术结构关键词加 HTML 加粗高亮，\\n → <br>"""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for kw in STRUCTURE_KEYWORDS:
        text = re.sub(
            r'(^|\n|\.\s+)(\s*)(' + re.escape(kw) + r')(\s*[\n:：\.])',
            r'\1\2<b><span style="font-size:16px; color:#7aa2f7;">\3</span></b>\4',
            text, flags=re.IGNORECASE
        )
    text = text.replace("\n", "<br>")
    return f'<div style="white-space: normal; word-wrap: break-word; overflow-wrap: break-word;">{text}</div>'


class ParagraphCard(QFrame):
    translate_requested = Signal(int, str)

    def __init__(self, para: dict, index: int, parent=None):
        super().__init__(parent)
        self._index = index
        self._text = para.get("text", "")
        self._is_heading = para.get("is_heading", False)
        self._is_meta = para.get("is_meta", False)
        self._is_english = self._detect_en(self._text)
        self._translated = False
        self._selected = False
        self._setup_ui()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        """根据给定宽度计算所需高度，使文字折行后卡片能正确撑高"""
        marg = self.contentsMargins()
        inner_w = max(w - marg.left() - marg.right(), 50)
        lay = self.layout()
        if lay is None:
            return 40
        h = marg.top() + marg.bottom() + calc_layout_height(lay, inner_w)
        return max(h, 40)

    def sizeHint(self):
        """确保 sizeHint 与 heightForWidth 一致"""
        base = super().sizeHint()
        return QSize(base.width(), self.heightForWidth(base.width()))

    def _detect_en(self, text: str) -> bool:
        if not text: return False
        ascii_chars = sum(1 for c in text if c.isascii())
        return (ascii_chars / max(len(text), 1)) > 0.4

    def _setup_ui(self):
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setStyleSheet(
            "ParagraphCard { background-color: #1a1b26; border: 1px solid #2a2c3d; border-radius: 10px; margin: 4px 0px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(8)

        # 选择框行（始终存在，供合并功能使用）
        self._select_row = QHBoxLayout()
        self._select_row.setContentsMargins(0, 0, 0, 2)
        self._checkbox = QCheckBox()
        self._checkbox.setToolTip("勾选以合并或删除")
        self._checkbox.setStyleSheet(CHECKBOX_STYLE)
        self._checkbox.stateChanged.connect(self._on_select_changed)
        self._select_row.addWidget(self._checkbox)
        self._select_row.addStretch()
        layout.addLayout(self._select_row)

        if self._is_meta:
            f = QFont("Microsoft YaHei UI", 10)
            self.text_label = QLabel(self._text); self.text_label.setFont(f)
            self.text_label.setStyleSheet("color: #636688; line-height: 1.5; padding: 2px 0;")
        elif self._is_heading:
            f = QFont("Microsoft YaHei UI", 15); f.setBold(True)
            self.text_label = QLabel(self._text); self.text_label.setFont(f)
            self.text_label.setStyleSheet("color: #7aa2f7; padding: 6px 0; letter-spacing: 0.5px;")
        else:
            base_size = 13
            f = QFont("Segoe UI" if self._is_english else "Microsoft YaHei UI", base_size)
            if self._is_english:
                f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.3)
            # 应用结构关键词高亮
            highlighted = _highlight_keywords(self._text)
            self.text_label = QLabel(highlighted); self.text_label.setFont(f)
            self.text_label.setTextFormat(Qt.TextFormat.RichText)
            self.text_label.setStyleSheet(
                "color: #cfd2e3; line-height: 1.9; padding: 4px 0; "
                "background-color: transparent;"
            )
        self.text_label.setWordWrap(True)
        self.text_label.setMinimumWidth(0)
        self.text_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text_label.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        layout.addWidget(self.text_label)

        # 翻译按钮：非标题、非元信息、有内容就显示
        if not self._is_heading and not self._is_meta and len(self._text.strip()) > 20:
            sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet("background-color: #2a2c3d; max-height: 1px;")
            self.trans_sep = sep; layout.addWidget(self.trans_sep)

            self.zh_label = QLabel(); self.zh_label.setWordWrap(True)
            self.zh_label.setFont(QFont("Microsoft YaHei UI", 12))
            self.zh_label.setStyleSheet("color: #9ece6a; line-height: 1.7; padding: 4px 0;")
            self.zh_label.setVisible(False)
            self.zh_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(self.zh_label)

            btn_row = QHBoxLayout()
            self.trans_btn = QPushButton("🌐 翻译" if self._is_english else "🔄 翻译本段")
            self.trans_btn.setFixedWidth(110); self.trans_btn.clicked.connect(self._request)
            btn_row.addWidget(self.trans_btn)

            self.format_btn = QPushButton("📝 排版")
            self.format_btn.setFixedWidth(80)
            self.format_btn.setToolTip("提交本段给 AI 排版整理")
            self.format_btn.clicked.connect(self._on_re_format)
            self.format_btn.setVisible(False)  # 初始隐藏，由 _apply_auto_format_visibility 控制
            btn_row.addWidget(self.format_btn)

            self.re_trans_btn = QPushButton("🔄 重新翻译")
            self.re_trans_btn.setFixedWidth(100)
            self.re_trans_btn.clicked.connect(self._on_re_translate)
            self.re_trans_btn.setVisible(False)
            self.re_trans_btn.setStyleSheet(
                "QPushButton { background-color: #2a2c3d; color: #e0af68; border: 1px solid #3b3d54; "
                "border-radius: 4px; padding: 4px 10px; font-size: 12px; }"
                "QPushButton:hover { background-color: #3b3d54; }"
            )
            btn_row.addWidget(self.re_trans_btn)

            self.re_format_btn = QPushButton("📝 重新排版")
            self.re_format_btn.setFixedWidth(100)
            self.re_format_btn.setToolTip("重新提交本段给 AI 排版整理")
            self.re_format_btn.clicked.connect(self._on_re_format)
            self.re_format_btn.setVisible(False)
            self.re_format_btn.setStyleSheet(
                "QPushButton { background-color: #2a2c3d; color: #a9b1d6; border: 1px solid #3b3d54; "
                "border-radius: 4px; padding: 4px 10px; font-size: 12px; }"
                "QPushButton:hover { background-color: #3b3d54; }"
            )
            btn_row.addWidget(self.re_format_btn)
            btn_row.addStretch()
            layout.addLayout(btn_row)

    def _request(self):
        if not self._translated and hasattr(self, 'trans_btn'):
            self.trans_btn.setText("⏳"); self.trans_btn.setEnabled(False)
            self.translate_requested.emit(self._index, self._text)

    def show_translation(self, zh: str, defer_layout: bool = True):
        self._translated = True; self._trans_text = zh
        if hasattr(self, 'zh_label'):
            self.zh_label.setText(zh); self.zh_label.setVisible(True)
        if hasattr(self, 'trans_btn'):
            self.trans_btn.setVisible(False)
        if hasattr(self, 're_trans_btn'):
            self.re_trans_btn.setVisible(True)
        if hasattr(self, 're_format_btn'):
            self.re_format_btn.setVisible(True)
        if defer_layout and hasattr(self, 'zh_label'):
            QTimer.singleShot(0, self._adjust_card_size)

    def _adjust_card_size(self):
        if hasattr(self, 'zh_label'):
            self.zh_label.updateGeometry()
        self.updateGeometry()

    def show_error(self, err: str):
        self.trans_btn.setText("❌ 失败"); self.trans_btn.setEnabled(True); self.trans_btn.setToolTip(err)

    def _on_re_translate(self):
        hint, ok = QInputDialog.getText(
            self, "重新翻译",
            "请输入重新翻译的要求或原因（可选）：",
            text=""
        )
        if ok:
            self._translated = False
            self.zh_label.setVisible(False)
            self.re_trans_btn.setVisible(False)
            self.trans_btn.setVisible(True)
            self.trans_btn.setText("⏳"); self.trans_btn.setEnabled(False)
            # 拼接自定义指令
            text = self._text
            if hint.strip():
                text = f"【重新翻译要求：{hint.strip()}】\n\n{text}"
            self.translate_requested.emit(self._index, text)

    def _on_re_format(self):
        """重新排版——发出重排信号给 PDFViewerPanel"""
        if hasattr(self, 're_format_btn'):
            self.re_format_btn.setText("⏳")
            self.re_format_btn.setEnabled(False)
        if hasattr(self, 'format_btn'):
            self.format_btn.setText("⏳")
            self.format_btn.setEnabled(False)
        self.translate_requested.emit(self._index, f"__REFORMAT__{self._text}")

    def _on_select_changed(self, state):
        self._selected = (state == Qt.CheckState.Checked.value)
        if self._selected:
            self.setStyleSheet(self.styleSheet().replace(
                "border: 1px solid #2a2c3d;", "border: 2px solid #7aa2f7;"))
        else:
            self.setStyleSheet(self.styleSheet().replace(
                "border: 2px solid #7aa2f7;", "border: 1px solid #2a2c3d;"))

    def set_selected(self, selected: bool):
        self._selected = selected
        self._checkbox.blockSignals(True)
        self._checkbox.setChecked(selected)
        self._checkbox.blockSignals(False)

    def is_selected(self) -> bool:
        return self._selected

    def contextMenuEvent(self, event):
        """右键菜单：全选 / 复制 / 拆分"""
        selected = self.text_label.selectedText()
        has_sel = bool(selected.strip())

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #24253a; color: #cfd2e3; border: 1px solid #3b3d54; }"
            "QMenu::item:selected { background: #3b3d54; }"
            "QMenu::item:disabled { color: #636688; }"
        )

        select_all = menu.addAction("📄 全选")
        menu.addSeparator()

        copy_action = menu.addAction("📋 复制")
        copy_action.setEnabled(has_sel)
        if not has_sel:
            copy_action.setToolTip("请先选中文字")

        split_action = menu.addAction("✂️ 拆分")
        split_action.setEnabled(has_sel)
        if not has_sel:
            split_action.setToolTip("请先选中文字")

        action = menu.exec(event.globalPos())
        if action == select_all:
            doc = QTextDocument()
            doc.setHtml(self.text_label.text())
            self.text_label.setFocus()
            self.text_label.setSelection(0, len(doc.toPlainText()))
        elif action == copy_action:
            QApplication.clipboard().setText(selected)
        elif action == split_action:
            full = self._text
            pos = -1
            for candidate in [selected, selected.replace('\u2028', '\n'),
                              selected.replace('\u2028', ' '), ' '.join(selected.split())]:
                pos = full.find(candidate)
                if pos >= 0:
                    break
            if pos >= 0:
                p = self.parent()
                while p:
                    if hasattr(p, '_on_split_card_by_range'):
                        p._on_split_card_by_range(self, pos, pos + len(candidate))
                        return
                    p = p.parent()


# ---- 图片卡片 ----

class ImageCard(QFrame):

    explain_requested = Signal(str)
    follow_up = Signal(str, str)

    def __init__(self, image_path: str, page: int, parent=None):
        super().__init__(parent)
        self._image_path = image_path
        self._page = page
        self._explained = False
        self._selected = False
        self.setStyleSheet(
            "ImageCard { background-color: #1a1b26; border: 1px solid #2a2c3d; border-radius: 10px; margin: 6px 12px; }"
        )
        self._setup_ui()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        """根据给定宽度计算所需高度"""
        marg = self.contentsMargins()
        inner_w = max(w - marg.left() - marg.right(), 50)
        lay = self.layout()
        if lay is None:
            return 40
        h = marg.top() + marg.bottom() + calc_layout_height(lay, inner_w)
        return max(h, 40)

    def sizeHint(self):
        """确保 sizeHint 与 heightForWidth 一致"""
        base = super().sizeHint()
        return QSize(base.width(), self.heightForWidth(base.width()))

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12); layout.setSpacing(8)

        # 选择框
        self._checkbox = QCheckBox()
        self._checkbox.setToolTip("勾选以删除")
        self._checkbox.setStyleSheet(CHECKBOX_STYLE)
        self._checkbox.stateChanged.connect(self._on_select_changed)
        layout.addWidget(self._checkbox)

        page_label = QLabel(f"📷 第 {self._page} 页插图")
        page_label.setStyleSheet("color: #9599b5; font-size: 11px;")
        page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(page_label)

        if self._image_path and os.path.exists(self._image_path):
            pixmap = QPixmap(self._image_path)
            if not pixmap.isNull():
                if pixmap.width() > 500:
                    pixmap = pixmap.scaledToWidth(500, Qt.TransformationMode.SmoothTransformation)
                img_label = QLabel(); img_label.setPixmap(pixmap)
                img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(img_label)

        self.explain_btn = QPushButton("🔍 AI 解读此图")
        self.explain_btn.clicked.connect(self._request)
        layout.addWidget(self.explain_btn)

        self.explain_label = QLabel(); self.explain_label.setWordWrap(True)
        self.explain_label.setFont(QFont("Microsoft YaHei UI", 12))
        self.explain_label.setStyleSheet("color: #e0af68; line-height: 1.7; padding: 8px 0;")
        self.explain_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.explain_label.setVisible(False)
        layout.addWidget(self.explain_label)

        # 追问区
        self.follow_frame = QFrame()
        fl = QHBoxLayout(self.follow_frame); fl.setContentsMargins(0, 0, 0, 0); fl.setSpacing(6)
        self.follow_input = QTextEdit(); self.follow_input.setPlaceholderText("对图片解读追问...")
        self.follow_input.setMaximumHeight(50); self.follow_input.setMinimumHeight(36)
        fl.addWidget(self.follow_input, 1)
        ask_btn = QPushButton("发送"); ask_btn.setObjectName("primaryBtn"); ask_btn.setFixedWidth(60)
        ask_btn.clicked.connect(self._send_follow)
        fl.addWidget(ask_btn)
        self.follow_frame.setVisible(False)
        layout.addWidget(self.follow_frame)

    def _request(self):
        if not self._explained:
            self.explain_btn.setText("⏳ 分析中..."); self.explain_btn.setEnabled(False)
            self.explain_requested.emit(self._image_path)

    def show_explanation(self, text: str):
        self._explained = True; self._explain_text = text
        self.explain_label.setText(text); self.explain_label.setVisible(True)
        self.explain_btn.setText("✅ 已解读"); self.explain_btn.setStyleSheet("color: #9ece6a;")
        self.follow_frame.setVisible(True)

    def show_explain_error(self, err: str):
        self.explain_btn.setText("❌ 失败"); self.explain_btn.setEnabled(True); self.explain_btn.setToolTip(err)

    def _send_follow(self):
        q = self.follow_input.toPlainText().strip()
        if q:
            ctx = f"图片解读结果：{getattr(self, '_explain_text', '')}\n\n追问：{q}"
            self.follow_up.emit(ctx, q)
            self.follow_input.clear()

    def _on_select_changed(self, state):
        self._selected = (state == Qt.CheckState.Checked.value)
        if self._selected:
            self.setStyleSheet(self.styleSheet().replace(
                "border: 1px solid #2a2c3d;", "border: 2px solid #7aa2f7;"))
        else:
            self.setStyleSheet(self.styleSheet().replace(
                "border: 2px solid #7aa2f7;", "border: 1px solid #2a2c3d;"))

    def set_selected(self, selected: bool):
        self._selected = selected
        self._checkbox.blockSignals(True)
        self._checkbox.setChecked(selected)
        self._checkbox.blockSignals(False)

    def is_selected(self) -> bool:
        return self._selected


# ---- PDF 阅读器面板 ----

class PDFViewerPanel(QWidget):
    pdf_loaded = Signal(str)
    pdf_path_changed = Signal(str)
    follow_up_question = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path: str = ""
        self._llm_trans = None
        self._llm_image = None
        self._llm_format = None
        self._trans_worker: TranslationWorker | None = None
        self._format_worker: StructureFormatWorker | FormatWorker | None = None
        self._merge_worker: MergeWorker | None = None
        self._img_load_worker: ImageLoadWorker | None = None
        self._pending: dict[int, str] = {}
        self._image_dir = ""
        self._auto_translate: bool = False
        self._auto_format: bool = False
        self._search_index: int = -1
        self._search_matches: list = []
        self._merged_hidden: list[ParagraphCard] = []
        self._deleted_images: set[str] = set()  # 已删除图片路径，持久化后跳过渲染
        self._deleted_paragraphs: set[int] = set()  # 已删除段落索引，持久化后跳过渲染
        self._cards: list = []
        self._pdf_text: str = ""
        self._paragraphs: list[dict] = []
        self._original_paragraphs: list[dict] = []  # 合并前的原始段落（图像模式匹配用）
        self._formatted: set[int] = set()
        self._format_pending: dict[int, str] = {}
        self._format_enabled: bool = False
        self._structure_map: dict[int, dict] = {}  # idx -> {label, section_name, ...}
        self._image_worker: ImageStructureWorker | None = None
        self._image_result_cache: dict[int, dict] = {}  # page_num -> structured result
        self._image_enabled: bool = False
        self._integration_worker: TextIntegrationWorker | None = None
        self._llm_chat_client = None  # DeepSeek 聊天客户端（整合用）
        self._integrated_text: str = ""
        self._parser = None
        self._setup_ui()

    def set_translation_client(self, client):
        self._llm_trans = client

    def set_image_client(self, client):
        self._llm_image = client

    def set_format_client(self, client):
        """设置 AI 排版客户端，有则启用滚动触发排版"""
        self._llm_format = client
        self._format_enabled = client is not None

    def set_chat_client(self, client):
        """设置聊天客户端（供 DeepSeek 整合步骤使用）"""
        self._llm_chat_client = client

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(12, 8, 12, 8)
        title = QLabel("📖 论文阅读")
        title.setObjectName("titleLabel")
        toolbar.addWidget(title)
        toolbar.addStretch()

        self.merge_btn = QPushButton("🔗 合并选中")
        self.merge_btn.setToolTip("勾选段落左侧复选框，然后点击此按钮将选中的段落合并为一段")
        self.merge_btn.clicked.connect(self._on_merge_selected)
        self.merge_btn.setEnabled(False)
        self.merge_btn.setVisible(False)
        toolbar.addWidget(self.merge_btn)

        self.delete_btn = QPushButton("🗑️ 删除选中")
        self.delete_btn.setToolTip("删除勾选的卡片（如无关的图标、页码等）")
        self.delete_btn.clicked.connect(self._on_delete_selected)
        self.delete_btn.setEnabled(False)
        self.delete_btn.setVisible(False)
        toolbar.addWidget(self.delete_btn)

        self.undo_merge_btn = QPushButton("↩️ 撤销合并")
        self.undo_merge_btn.setToolTip("撤销上一次合并操作，恢复被隐藏的段落")
        self.undo_merge_btn.clicked.connect(self._on_undo_merge)
        self.undo_merge_btn.setEnabled(False)
        self.undo_merge_btn.setVisible(False)
        toolbar.addWidget(self.undo_merge_btn)

        # 自动翻译开关
        self.auto_trans_btn = QPushButton("🔄 自动翻译：关")
        self.auto_trans_btn.setToolTip("开启后，AI 排版完成时自动翻译；关闭则手动点击翻译")
        self.auto_trans_btn.clicked.connect(self._on_toggle_auto_translate)
        self.auto_trans_btn.setEnabled(False)
        toolbar.addWidget(self.auto_trans_btn)

        self.auto_format_btn = QPushButton("📝 自动排版：关")
        self.auto_format_btn.setToolTip("开启后滚动时自动 AI 排版；关闭则手动点击排版按钮")
        self.auto_format_btn.clicked.connect(self._on_toggle_auto_format)
        self.auto_format_btn.setEnabled(False)
        toolbar.addWidget(self.auto_format_btn)

        self.image_btn = QPushButton("🖼️ 图像识别全文")
        self.image_btn.setToolTip("将每页渲染为图片，发送给多模态模型进行高精度结构识别（需配置排版或图析 API 支持多模态）")
        self.image_btn.clicked.connect(self._on_start_image_analysis)
        self.image_btn.setEnabled(False)
        toolbar.addWidget(self.image_btn)
        layout.addLayout(toolbar)

        # 搜索栏（默认隐藏，Ctrl+F 切换）
        self.search_bar = QHBoxLayout()
        self.search_bar.setContentsMargins(12, 4, 12, 4)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索论文内容... (Enter 下一个, Esc 关闭)")
        self.search_input.setStyleSheet(
            "QLineEdit { background-color: #24253a; color: #e2e5f2; border: 1px solid #7aa2f7; "
            "border-radius: 6px; padding: 5px 10px; font-size: 13px; }"
        )
        self.search_input.returnPressed.connect(self._on_search_next)
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_bar.addWidget(self.search_input)
        self.search_count = QLabel("")
        self.search_count.setStyleSheet("color: #8a8ea6; font-size: 12px; min-width: 60px;")
        self.search_bar.addWidget(self.search_count)
        # 初始隐藏
        self._search_bar_widget = QWidget()
        self._search_bar_widget.setLayout(self.search_bar)
        self._search_bar_widget.setVisible(False)
        layout.addWidget(self._search_bar_widget)

        # 信息栏
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #2a2c3d; max-height: 1px;")
        layout.addWidget(sep)

        info = QHBoxLayout()
        info.setContentsMargins(12, 4, 12, 4)
        self.info_label = QLabel("尚未加载 PDF — 从左侧论文库选择或点击「打开 PDF」")
        self.info_label.setObjectName("subtitleLabel")
        info.addWidget(self.info_label)
        info.addStretch()
        layout.addLayout(info)

        # 阅读区
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: #1a1b26; }")

        # 始终使用 container 作为 scroll 的 widget，不再切换
        self.container = QWidget()
        self.container.setMinimumWidth(0)
        self.container.setStyleSheet("background: #1a1b26;")
        self.container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.card_layout = QVBoxLayout(self.container)
        self.card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.card_layout.setSpacing(0)
        self.card_layout.setContentsMargins(0, 10, 0, 20)

        # 初始占位提示
        self.placeholder = QLabel(PLACEHOLDER_TEXT)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet("color: #636688; padding: 80px 40px; font-size: 15px;")
        self.card_layout.addWidget(self.placeholder)

        self.scroll_area.setWidget(self.container)
        layout.addWidget(self.scroll_area, 1)

        # 滚动时触发懒排版
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll)
        # 视口大小变化时更新卡片布局
        self.scroll_area.viewport().installEventFilter(self)

        # 安装键盘事件过滤器
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_F and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._toggle_search()
                return True
            if event.key() == Qt.Key.Key_Escape and self._search_bar_widget.isVisible():
                self._search_bar_widget.setVisible(False)
                self._clear_search_highlights()
                return True
        # 视口大小变化
        if obj is self.scroll_area.viewport() and event.type() == QEvent.Type.Resize:
            if self.container:
                self.container.updateGeometry()
        return super().eventFilter(obj, event)

    # ---- PDF 加载 ----

    def _open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 PDF", "", "PDF (*.pdf);;All (*.*)")
        if path:
            self.load_pdf(path)

    def load_pdf(self, file_path: str):
        self._flush_save_state()

        try:
            from ..core.pdf_parser import PDFParser
            from ..utils.config import get_image_cache_dir, load_paragraph_cache, save_paragraph_cache

            self._cards.clear()
            self._formatted.clear()
            self._format_pending.clear()
            self._paragraphs = []
            self._pdf_text = ""

            # 提前加载已删除图片/段落记录（_render_content 需要用到）
            from ..utils.config import load_doc_state
            saved = load_doc_state(file_path)
            self._deleted_images = set(saved.get("deleted_images", [])) if saved else set()
            self._deleted_paragraphs = set(saved.get("deleted_paragraphs", [])) if saved else set()

            while self.card_layout.count():
                item = self.card_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            self._image_dir = str(get_image_cache_dir())

            cached = load_paragraph_cache(file_path)
            if cached:
                self._paragraphs, self._pdf_text = cached
                page_count = max((p.get("page", 0) for p in self._paragraphs), default=0)
                self.info_label.setText("📖 从缓存加载...")
                self.info_label.setStyleSheet("color: #9ece6a;")
                QApplication.processEvents()
                self._parser = PDFParser(file_path)
                self._parser.set_image_output_dir(self._image_dir)
            else:
                self.info_label.setText("⏳ 正在打开 PDF...")
                self.info_label.setStyleSheet("color: #e0af68;")
                QApplication.processEvents()
                self._parser = PDFParser(file_path)
                self._parser.set_image_output_dir(self._image_dir)
                self.info_label.setText("⏳ 正在提取全文...")
                QApplication.processEvents()
                self._pdf_text = self._parser.extract_full_text()
                page_count = self._parser.page_count
                self.info_label.setText("⏳ 正在智能分段...")
                QApplication.processEvents()
                self._paragraphs = self._parser.extract_structured_paragraphs(skip_images=True)
                save_paragraph_cache(file_path, self._paragraphs, self._pdf_text)

            # ====== 合并小段落为 ~5000 字大卡片（句子边界安全切分） ======
            from ..core.section_splitter import merge_paragraphs_into_chunks
            self._original_paragraphs = [dict(p) for p in self._paragraphs]  # 保存副本供图像模式匹配
            self._paragraphs = merge_paragraphs_into_chunks(self._paragraphs)
            # 合并后原删除记录失效（索引已变），清空之
            self._deleted_paragraphs = set()

            text_paras = [p for p in self._paragraphs if p.get("text", "").strip()]
            heading_count = sum(1 for p in self._paragraphs if p.get("is_heading"))
            meta_count = sum(1 for p in self._paragraphs if p.get("is_meta"))
            img_count = sum(1 for p in self._paragraphs if p.get("image_path"))

            self._render_content()
            self._current_path = file_path
            self.pdf_path_changed.emit(file_path)
            self.info_label.setText(
                f"📖 已加载 · {page_count} 页 · {len(text_paras)} 卡"
                + (f" · {heading_count} 标题" if heading_count else "")
                + (f" · {meta_count} 元信息" if meta_count else "")
                + (f" · {img_count} 图" if img_count else "")
            )
            self.info_label.setStyleSheet("color: #9ece6a;")
            self.auto_trans_btn.setEnabled(True)
            self.auto_format_btn.setEnabled(True)
            self.image_btn.setEnabled(True)
            self.pdf_loaded.emit(self._pdf_text)
            QTimer.singleShot(200, lambda: self._restore_state(file_path))
            QTimer.singleShot(100, self._start_image_loading)
            QTimer.singleShot(500, self._update_action_buttons)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.info_label.setText(f"❌ 加载失败：{e}")
            self.info_label.setStyleSheet("color: #f7768e;")

    def _start_image_loading(self):
        if not hasattr(self, '_parser') or not self._parser:
            return
        if self._img_load_worker and self._img_load_worker.isRunning():
            self._img_load_worker.wait()
        self._img_load_worker = ImageLoadWorker(self._parser)
        self._img_load_worker.images_ready.connect(self._on_images_loaded)
        self._img_load_worker.start()

    def _reset_view(self):
        self._current_path = ""
        self._cards = []
        self._formatted = set()
        self._format_pending = {}
        self._structure_map.clear()
        self._pdf_text = ""
        self._paragraphs = []
        self._original_paragraphs = []
        self._deleted_images = set()
        self._deleted_paragraphs = set()
        self._image_result_cache.clear()
        self._image_enabled = False

        # 清空容器内所有内容
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 重新显示占位提示
        self.placeholder = QLabel(PLACEHOLDER_TEXT)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet("color: #636688; padding: 80px 40px; font-size: 15px;")
        self.card_layout.addWidget(self.placeholder)

        self.info_label.setText("尚未加载 PDF")
        self.info_label.setStyleSheet("")
        self.auto_trans_btn.setEnabled(False)
        self.auto_format_btn.setEnabled(False)

    def _on_images_loaded(self, images: list[dict]):
        if not images:
            return
        # 过滤有效图片并按页分组
        imgs_by_page: dict[int, list[dict]] = {}
        for img in images:
            if not img.get("path"):
                continue
            page = img["page"]
            imgs_by_page.setdefault(page, []).append(img)

        if not imgs_by_page:
            return

        inserted = 0
        for page_num in sorted(imgs_by_page.keys()):
            for img_info in imgs_by_page[page_num]:
                if img_info["path"] in self._deleted_images:
                    continue
                img_card = ImageCard(img_info["path"], page_num)
                img_card.explain_requested.connect(self._on_image_explain)
                img_card.follow_up.connect(self._on_follow_up)
                if hasattr(img_card, '_checkbox'):
                    img_card._checkbox.stateChanged.connect(self._update_action_buttons)

                # 找到该页面第一个段落卡片的位置，图片插在它前面
                img_y = img_info.get("bbox", (0, 0, 0, 0))[1]
                insert_at = self.card_layout.count()  # 默认末尾
                for idx, card in enumerate(self._cards):
                    if isinstance(card, ParagraphCard):
                        # 用 paragraph 数据找对应页面
                        if card._index < len(self._paragraphs):
                            p = self._paragraphs[card._index]
                            if p.get("page") == page_num and p.get("bbox", (0, 0, 0, 0))[1] > img_y:
                                insert_at = idx
                                break
                            if p.get("page") == page_num:
                                insert_at = idx + 1  # 在该页最后一段之后

                self._cards.insert(insert_at, img_card)
                self.card_layout.insertWidget(insert_at, img_card)
                inserted += 1

        if inserted > 0:
            current = self.info_label.text()
            if "张图" not in current:
                self.info_label.setText(current + f" · 🖼️ {inserted} 张图")

    def _render_content(self):
        """渲染结构化段落为卡片（container 始终是 scroll 的 widget）"""
        self._cards.clear()
        self._formatted.clear()
        self._format_pending.clear()
        self._structure_map.clear()

        # 清空容器内所有旧内容（包括 placeholder）
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        card_count = 0
        for i, para in enumerate(self._paragraphs):
            if para.get("image_path"):
                if para["image_path"] in self._deleted_images:
                    continue  # 用户删除过的图片，跳过
                card = ImageCard(para["image_path"], para.get("page", 0))
                card.explain_requested.connect(self._on_image_explain)
                card.follow_up.connect(self._on_follow_up)
                if hasattr(card, '_checkbox'):
                    card._checkbox.stateChanged.connect(self._update_action_buttons)
                self.card_layout.addWidget(card)
                self._cards.append(card)
                card_count += 1
            elif para.get("text", "").strip():
                if i in self._deleted_paragraphs:
                    continue  # 用户删除过的段落，跳过
                card = ParagraphCard(para, i)
                card.translate_requested.connect(self._on_translate)
                if hasattr(card, '_checkbox'):
                    card._checkbox.stateChanged.connect(self._update_action_buttons)
                self.card_layout.addWidget(card)
                self._cards.append(card)
                card_count += 1

        # 空内容时显示提示
        if card_count == 0:
            empty_label = QLabel(
                "📄 此 PDF 未提取到文本内容。\n\n"
                "可能原因：\n"
                "• PDF 为扫描版（图片格式）\n"
                "• PDF 内容为矢量图形而非文字\n"
                "• 文件已加密或损坏"
            )
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet("color: #636688; padding: 60px 40px; font-size: 14px;")
            empty_label.setWordWrap(True)
            self.card_layout.addWidget(empty_label)

        self._apply_auto_visibility()
        self.card_layout.addStretch()

        # 强制布局更新并滚回顶部
        self.container.updateGeometry()
        self.container.adjustSize()
        self.scroll_area.verticalScrollBar().setValue(0)

        # 不在此调度自动排版——等 _restore_state 恢复已保存状态后再触发

    # ---- 翻译 ----

    def _on_translate(self, idx: int, text: str):
        # 检查是否为重排请求
        if text.startswith("__REFORMAT__"):
            real_text = text[len("__REFORMAT__"):]
            if self._llm_format:
                # 从 _formatted 中移除以允许重排
                self._formatted.discard(idx)
                self._format_pending[idx] = real_text
                self._start_next_format()
            return
        # 正常翻译流程
        if not self._llm_trans:
            return
        if self._trans_worker and self._trans_worker.isRunning():
            self._pending[idx] = text
            return
        self._start_trans(idx, text)

    def _start_trans(self, idx: int, text: str):
        self._trans_worker = TranslationWorker(self._llm_trans, idx, text)
        self._trans_worker.finished.connect(self._on_done)
        self._trans_worker.error.connect(self._on_err)
        self._trans_worker.start()

    def _on_done(self, idx: int, zh: str):
        for card in self._cards:
            if isinstance(card, ParagraphCard) and card._index == idx:
                card.show_translation(zh)
                break
        self._save_state()  # 翻译完成后保存状态
        self._next()

    def _on_err(self, idx: int, err: str):
        for card in self._cards:
            if isinstance(card, ParagraphCard) and card._index == idx:
                card.show_error(err)
                break
        self._next()

    def _next(self):
        if self._pending:
            idx, text = next(iter(self._pending.items()))
            del self._pending[idx]
            self._start_trans(idx, text)

    # ---- 图片解释 ----

    def _on_image_explain(self, image_path: str):
        if not self._llm_image or not image_path:
            return
        # 找到发起请求的卡片
        for card in self._cards:
            if isinstance(card, ImageCard) and card._image_path == image_path and not card._explained:
                self._explain_image(card, image_path)
                break

    def _explain_image(self, card: ImageCard, image_path: str):
        if hasattr(self, '_img_worker') and self._img_worker and self._img_worker.isRunning():
            return  # 上一张图还在分析中
        self._img_worker = ImageExplainWorker(self._llm_image, image_path)
        self._img_worker.done.connect(lambda t: (card.show_explanation(t), setattr(self, '_img_worker', None)))
        self._img_worker.err.connect(lambda e: (card.show_explain_error(e), setattr(self, '_img_worker', None)))
        self._img_worker.start()

    def _on_follow_up(self, context: str, question: str):
        self.follow_up_question.emit(context)

    # ---- 懒排版 ----

    def _on_scroll(self):
        """滚动时触发懒排版检测（150ms 防抖）"""
        if not self._format_enabled:
            return
        if not hasattr(self, '_scroll_timer'):
            self._scroll_timer = QTimer(self)
            self._scroll_timer.setSingleShot(True)
            self._scroll_timer.timeout.connect(self._check_visible_and_format)
        self._scroll_timer.start(150)

    def _check_visible_and_format(self):
        """检测视口内可见但未排版的段落卡片，加入队列"""
        if not self._format_enabled or not self._cards or not self._auto_format:
            return

        viewport_rect = self.scroll_area.viewport().rect()
        margin = int(viewport_rect.height() * 1.0)
        extended_rect = viewport_rect.adjusted(0, 0, 0, margin)

        for card in self._cards:
            if not isinstance(card, ParagraphCard):
                continue
            idx = card._index
            if idx in self._formatted or idx in self._format_pending:
                continue
            # 卡片在视口内的快速判断
            card_top = card.mapTo(self.scroll_area.viewport(), card.rect().topLeft()).y()
            if card_top > extended_rect.bottom():
                break  # 已超出可视区域，后续卡片无需检查
            if card_top + card.height() < extended_rect.top():
                continue  # 在可视区域上方，跳过
            text = card._text
            if not text.strip():
                continue
            self._format_pending[idx] = text

        self._start_next_format()

    def _build_card_context(self, idx: int) -> tuple[list[dict], list[dict]]:
        """构建当前卡片的前后上下文，用于 LLM 结构识别。

        Returns:
            (prev_contexts, next_contexts): 各包含 {index, text, label?, section_name?}
        """
        prev_contexts: list[dict] = []
        next_contexts: list[dict] = []

        # 构建 (列表位置, 卡片) 的映射
        card_entries = [(i, c) for i, c in enumerate(self._cards) if isinstance(c, ParagraphCard)]
        current_pos = next((i for i, (_, c) in enumerate(card_entries) if c._index == idx), -1)
        if current_pos < 0:
            return [], []

        # 前 2 张卡片
        for i in range(max(0, current_pos - 2), current_pos):
            _, card = card_entries[i]
            ctx: dict = {
                "index": card._index,
                "text": card._text,
            }
            if card._index in self._structure_map:
                sm = self._structure_map[card._index]
                ctx["label"] = sm.get("label", "")
                ctx["section_name"] = sm.get("section_name", "")
            prev_contexts.append(ctx)

        # 后 2 张卡片
        for i in range(current_pos + 1, min(len(card_entries), current_pos + 3)):
            _, card = card_entries[i]
            ctx: dict = {
                "index": card._index,
                "text": card._text,
            }
            if card._index in self._structure_map:
                sm = self._structure_map[card._index]
                ctx["label"] = sm.get("label", "")
                ctx["section_name"] = sm.get("section_name", "")
            next_contexts.append(ctx)

        return prev_contexts, next_contexts

    def _apply_structure_style(self, card: ParagraphCard, result: dict) -> None:
        """根据 LLM 返回的结构标签，更新卡片的字体、字号、颜色等样式。

        Args:
            card: 目标 ParagraphCard
            result: LLM 返回的结构化结果 {label, section_name, reformatted, ...}
        """
        label = result.get("label", "body")

        if label == "section_header":
            f = QFont("Microsoft YaHei UI", 16)
            f.setBold(True)
            card.text_label.setFont(f)
            card.text_label.setStyleSheet(
                "color: #7aa2f7; padding: 8px 0 4px 0; letter-spacing: 0.5px;"
            )
            card._is_heading = True
            card._is_meta = False
        elif label == "abstract_header":
            f = QFont("Microsoft YaHei UI", 15)
            f.setBold(True)
            card.text_label.setFont(f)
            card.text_label.setStyleSheet("color: #bb9af7; padding: 6px 0 4px 0;")
            card._is_heading = True
            card._is_meta = False
        elif label == "abstract_body":
            card.text_label.setStyleSheet(
                "color: #cfd2e3; line-height: 1.9; padding: 4px 12px; "
                "background-color: #1e2035; border-left: 3px solid #bb9af7;"
            )
            card._is_heading = False
            card._is_meta = False
        elif label == "metadata":
            f = QFont("Microsoft YaHei UI", 10)
            card.text_label.setFont(f)
            card.text_label.setStyleSheet("color: #636688; line-height: 1.5; padding: 2px 0;")
            card._is_heading = False
            card._is_meta = True
        elif label in ("header_footer", "reference"):
            f = QFont("Microsoft YaHei UI", 10)
            card.text_label.setFont(f)
            card.text_label.setStyleSheet("color: #565a7a; line-height: 1.4; padding: 2px 0;")
            card._is_heading = False
            card._is_meta = True
        elif label == "keywords":
            card.text_label.setStyleSheet(
                "color: #a9b1d6; line-height: 1.6; padding: 4px 0; font-style: italic;"
            )
            card._is_heading = False
            card._is_meta = False
        elif label == "acknowledgment":
            card.text_label.setStyleSheet(
                "color: #9599b5; line-height: 1.6; padding: 4px 0; font-style: italic;"
            )
            card._is_heading = False
            card._is_meta = False
        elif label in ("figure_caption", "table_caption"):
            f = QFont("Microsoft YaHei UI", 11)
            card.text_label.setFont(f)
            card.text_label.setStyleSheet(
                "color: #8a8ea6; line-height: 1.5; padding: 4px 0; font-style: italic;"
            )
            card._is_heading = False
            card._is_meta = False
        # "body", "appendix", "unknown" → 保留默认样式，不做特殊处理

    def _start_next_format(self):
        """从队列取下一个段落提交排版"""
        if self._format_worker and self._format_worker.isRunning():
            return
        if not self._format_pending:
            return
        idx, text = next(iter(self._format_pending.items()))
        del self._format_pending[idx]
        self._start_format(idx, text)

    def _start_format(self, idx: int, text: str):
        """提交单个段落到 AI 进行结构识别 + 排版整理。"""
        if not self._llm_format:
            self._format_pending.clear()
            return
        prev_ctx, next_ctx = self._build_card_context(idx)
        self._format_worker = StructureFormatWorker(
            self._llm_format, idx, text, prev_ctx, next_ctx,
        )
        self._format_worker.done.connect(self._on_structure_done)
        self._format_worker.err.connect(self._on_structure_err)
        self._format_worker.finished.connect(self._start_next_format)
        self._format_worker.start()

    def _on_structure_done(self, idx: int, result: dict):
        """结构识别完成 —— 更新卡片样式 + 排版文本。"""
        self._formatted.add(idx)

        # 存储结构信息
        self._structure_map[idx] = {
            "label": result.get("label", "body"),
            "section_name": result.get("section_name"),
        }

        reformatted = result.get("reformatted", "")
        parse_error = result.get("parse_error")

        for card in self._cards:
            if isinstance(card, ParagraphCard) and card._index == idx:
                # 应用结构样式
                self._apply_structure_style(card, result)

                # 更新文本（优先用排版后的，解析失败则保留原文）
                if reformatted and not parse_error:
                    card._text = reformatted
                    card.text_label.setText(reformatted)
                elif reformatted and parse_error:
                    # JSON 解析失败但 LLM 返回了文本 → 当作纯排版结果
                    card._text = reformatted
                    highlighted = _highlight_keywords(reformatted)
                    card.text_label.setTextFormat(Qt.TextFormat.RichText)
                    card.text_label.setText(highlighted)
                # 如果 reformatted 为空，保留原文不变

                # 自动翻译（如果开启且非元信息/页眉页脚）
                if self._auto_translate and not card._is_meta:
                    self._auto_translate_card(card)

                # 重置排版按钮
                if hasattr(card, 're_format_btn'):
                    card.re_format_btn.setText("📝 重新排版")
                    card.re_format_btn.setEnabled(True)
                    card.re_format_btn.setVisible(True)
                if hasattr(card, 'format_btn'):
                    card.format_btn.setVisible(False)
                break

        self._save_state()

    def _on_structure_err(self, idx: int, err: str):
        """结构识别失败 —— 静默跳过，保留原文。"""
        self._formatted.add(idx)
        for card in self._cards:
            if isinstance(card, ParagraphCard) and card._index == idx:
                if hasattr(card, 're_format_btn'):
                    card.re_format_btn.setText("📝 重新排版")
                    card.re_format_btn.setEnabled(True)
                if hasattr(card, 'format_btn') and not self._auto_format:
                    card.format_btn.setVisible(True)
                break
        print(f"[PDFViewer] 结构识别失败 idx={idx}: {err}")

    # ---- 手动合并 ----

    def _on_merge_selected(self):
        if not self._llm_format:
            return
        if self._merge_worker and self._merge_worker.isRunning():
            return

        # 收集选中的段落卡片（按顺序）
        selected_cards: list[ParagraphCard] = []
        for card in self._cards:
            if isinstance(card, ParagraphCard) and card.is_selected():
                selected_cards.append(card)

        if len(selected_cards) < 2:
            # 不足2段，不需要合并
            return

        # 收集原文
        texts = [c._text for c in selected_cards]
        self.merge_btn.setText("⏳ 合并中...")
        self.merge_btn.setEnabled(False)

        self._merge_worker = MergeWorker(self._llm_format, texts)
        self._merge_worker.done.connect(lambda t: self._on_merge_done(selected_cards, t))
        self._merge_worker.err.connect(self._on_merge_err)
        self._merge_worker.start()

    def _on_merge_done(self, selected_cards: list[ParagraphCard], merged_text: str):
        if not selected_cards:
            self._on_merge_reset()
            return

        first = selected_cards[0]
        clean = merged_text
        is_meta = False
        for prefix in ["[作者信息]", "[出版信息]"]:
            if clean.startswith(prefix):
                clean = clean[len(prefix):].strip()
                first._is_meta = True
                is_meta = True
                first.text_label.setStyleSheet("color: #636688; line-height: 1.5; padding: 2px 0;")
                first.text_label.setFont(QFont("Microsoft YaHei UI", 10))
                break
        if is_meta:
            first.text_label.setText(clean)
        else:
            highlighted = _highlight_keywords(clean)
            first.text_label.setTextFormat(Qt.TextFormat.RichText)
            first.text_label.setText(highlighted)
        first._text = clean
        self._formatted.add(first._index)
        first.set_selected(False)
        if hasattr(first, 're_format_btn'):
            first.re_format_btn.setVisible(True)
        if hasattr(first, 'format_btn'):
            first.format_btn.setVisible(False)

        # 自动翻译合并后的段落
        if self._auto_translate:
            first._translated = False  # 重置翻译状态
            self._auto_translate_card(first)

        # 记录被隐藏的卡片（用于撤销）
        self._merged_hidden = list(selected_cards[1:])

        # 隐藏其余选中的卡片，并标记为已排版防止重复处理
        for card in selected_cards[1:]:
            card.setVisible(False)
            card.set_selected(False)
            self._formatted.add(card._index)

        self.undo_merge_btn.setVisible(True)
        self.undo_merge_btn.setEnabled(True)
        self._update_action_buttons()
        self._save_state()
        self._on_merge_reset()

    def _on_merge_err(self, err_msg: str):
        self.merge_btn.setText("❌ 失败")
        self.merge_btn.setToolTip(err_msg)
        self.merge_btn.setEnabled(True)
        self._merge_worker = None
        QTimer.singleShot(3000, lambda: self.merge_btn.setText("🔗 合并选中"))

    def _on_merge_reset(self):
        self.merge_btn.setText("🔗 合并选中")
        self.merge_btn.setEnabled(True)
        self._merge_worker = None
    # ---- 状态持久化 ----

    def _restore_state(self, file_path: str):
        from ..utils.config import load_doc_state
        state = load_doc_state(file_path)
        if not state:
            return

        # 如果段落数量不匹配（段落合并导致索引变化），跳过旧状态
        if state.get("paragraph_count", -1) != len(self._paragraphs):
            return

        # 恢复已删除图片记录和段落索引
        self._deleted_images = set(state.get("deleted_images", []))
        self._deleted_paragraphs = set(state.get("deleted_paragraphs", []))

        # 恢复自动翻译/排版开关
        if state.get("auto_translate", False) != self._auto_translate:
            self._on_toggle_auto_translate()
        if state.get("auto_format", False) != self._auto_format:
            self._on_toggle_auto_format()

        # 恢复结构信息并重新应用样式
        structure_dict = state.get("structure", {})
        for card in self._cards:
            if not isinstance(card, ParagraphCard):
                continue
            idx_str = str(card._index)
            if idx_str in structure_dict:
                struct_info = structure_dict[idx_str]
                self._structure_map[card._index] = struct_info
                # 重新应用结构样式
                self._apply_structure_style(card, struct_info)

        # 恢复已排版段落（文本内容 + 对无结构信息的老数据做样式降级）
        formatted_dict = state.get("formatted", {})
        for card in self._cards:
            if not isinstance(card, ParagraphCard):
                continue
            idx_str = str(card._index)
            if idx_str in formatted_dict:
                fmt_text = formatted_dict[idx_str]
                self._formatted.add(card._index)
                if not fmt_text:
                    continue

                # 如果已有结构信息（新版），样式已由 _apply_structure_style 处理，
                # 这里只需恢复文本，不重复设置样式
                has_structure = idx_str in structure_dict

                if not has_structure and (fmt_text.startswith("[作者信息]") or fmt_text.startswith("[出版信息]")):
                    # 旧版兼容：根据前缀标记设置元信息样式
                    card._is_meta = True
                    card.text_label.setStyleSheet("color: #636688; line-height: 1.5; padding: 2px 0;")
                    card.text_label.setFont(QFont("Microsoft YaHei UI", 10))
                    clean = fmt_text
                    for prefix in ["[作者信息]", "[出版信息]"]:
                        if clean.startswith(prefix):
                            clean = clean[len(prefix):].strip()
                            break
                    card.text_label.setText(clean)
                    card._text = clean
                elif not has_structure:
                    # 旧版兼容：无结构信息的普通排版文本
                    highlighted = _highlight_keywords(fmt_text)
                    card.text_label.setTextFormat(Qt.TextFormat.RichText)
                    card.text_label.setText(highlighted)
                    card._text = fmt_text
                    if hasattr(card, 're_format_btn'):
                        card.re_format_btn.setVisible(True)
                    if hasattr(card, 'format_btn'):
                        card.format_btn.setVisible(False)
                else:
                    # 新版：样式已应用，只恢复文本
                    card._text = fmt_text
                    card.text_label.setText(fmt_text)
                    if hasattr(card, 're_format_btn'):
                        card.re_format_btn.setVisible(True)
                    if hasattr(card, 'format_btn'):
                        card.format_btn.setVisible(False)

        # 恢复已翻译（不触发逐个布局更新）
        translated = state.get("translated", {})
        for card in self._cards:
            if isinstance(card, ParagraphCard):
                idx_str = str(card._index)
                if idx_str in translated:
                    card.show_translation(translated[idx_str], defer_layout=False)

        # 批量调整布局（一次搞定，避免 N 个 QTimer 洪水）
        if translated:
            QTimer.singleShot(300, self._batch_adjust_layout)

        # 恢复滚动位置
        if "scroll_pos" in state:
            QTimer.singleShot(200, lambda: self.scroll_area.verticalScrollBar().setValue(
                state["scroll_pos"]))

        # 应用自动翻译/排版可见性
        self._apply_auto_visibility()

        # 状态恢复完成后再触发自动排版（避免 auto-format 覆盖已保存状态）
        if self._format_enabled and self._auto_format and self._cards:
            QTimer.singleShot(300, self._check_visible_and_format)

    def _save_state(self):
        """防抖保存（2s）"""
        path = self._current_path
        if not path:
            return
        if not hasattr(self, '_save_timer'):
            self._save_timer = QTimer(self)
            self._save_timer.setSingleShot(True)
        else:
            self._save_timer.stop()
            try:
                self._save_timer.timeout.disconnect()
            except RuntimeError:
                pass  # 首次调用时尚未连接，忽略
        self._save_timer.timeout.connect(lambda p=path: self._do_save_state_for(p))
        self._save_timer.start(2000)

    def _flush_save_state(self):
        """立即保存当前状态并停止定时器"""
        if hasattr(self, '_save_timer') and self._save_timer.isActive():
            self._save_timer.stop()
        if self._current_path:
            self._do_save_state_for(self._current_path)

    def _do_save_state_for(self, path: str):
        from ..utils.config import save_doc_state

        formatted_dict = {}
        for card in self._cards:
            if isinstance(card, ParagraphCard) and card._index in self._formatted:
                formatted_dict[str(card._index)] = card._text

        translated = {}
        for card in self._cards:
            if isinstance(card, ParagraphCard) and card._translated:
                translated[str(card._index)] = getattr(card, '_trans_text', '')

        state = {
            "formatted": formatted_dict,
            "translated": translated,
            "scroll_pos": self.scroll_area.verticalScrollBar().value(),
            "auto_translate": self._auto_translate,
            "auto_format": self._auto_format,
            "deleted_images": list(self._deleted_images),
            "deleted_paragraphs": sorted(self._deleted_paragraphs),
            "structure": dict(self._structure_map),  # {idx: {label, section_name}}
            "paragraph_count": len(self._paragraphs),  # 用于检测段落合并导致的索引变化
        }
        save_doc_state(path, state)

    def _batch_adjust_layout(self):
        self.container.updateGeometry()
        self.container.adjustSize()
        self.scroll_area.updateGeometry()

    def get_current_path(self) -> str:
        return self._current_path

    def save_state_now(self):
        self._flush_save_state()

    def shutdown(self):
        """关闭前清理所有后台线程，避免 QThread 销毁警告"""
        workers = [
            getattr(self, '_img_worker', None),
            getattr(self, '_img_load_worker', None),
            getattr(self, '_trans_worker', None),
            getattr(self, '_format_worker', None),
            getattr(self, '_merge_worker', None),
            getattr(self, '_image_worker', None),
            getattr(self, '_integration_worker', None),
        ]
        for w in workers:
            if w is not None and w.isRunning():
                w.quit()
                if not w.wait(3000):
                    w.terminate()
                    w.wait()

    def get_pdf_text(self) -> str:
        return self._pdf_text

    # ---- 搜索 ----

    def _toggle_search(self):
        vis = not self._search_bar_widget.isVisible()
        self._search_bar_widget.setVisible(vis)
        if vis:
            self.search_input.setFocus()
            self.search_input.selectAll()
        else:
            self._clear_search_highlights()
            self.search_input.clear()
            self.search_count.clear()

    def _on_search_changed(self, text: str):
        if not text.strip():
            self._clear_search_highlights()
            self.search_count.clear()
            return
        self._do_search(text.strip())

    def _on_search_next(self):
        text = self.search_input.text().strip()
        if not text:
            return
        if not self._search_matches:
            self._do_search(text)
        if self._search_matches:
            self._search_index = (self._search_index + 1) % len(self._search_matches)
            self._highlight_current()

    def _do_search(self, query: str):
        self._clear_search_highlights()
        self._search_matches = []
        query_lower = query.lower()
        for card in self._cards:
            if isinstance(card, ParagraphCard) and query_lower in card._text.lower():
                self._search_matches.append(card)

        self.search_count.setText(f"{len(self._search_matches)} 处匹配")
        if self._search_matches:
            self._search_index = 0
            self._highlight_current()

    def _highlight_current(self):
        if not self._search_matches or self._search_index < 0:
            return
        card = self._search_matches[self._search_index]
        # 高亮当前匹配卡片
        for c in self._cards:
            if isinstance(c, ParagraphCard):
                c.setStyleSheet(c.styleSheet().replace(
                    "border: 2px solid #e0af68;", "border: 1px solid #2a2c3d;"))
        card.setStyleSheet(card.styleSheet().replace(
            "border: 1px solid #2a2c3d;", "border: 2px solid #e0af68;"))
        self.scroll_area.ensureWidgetVisible(card, 0, 50)
        self.search_count.setText(f"{self._search_index + 1}/{len(self._search_matches)} 处匹配")

    def _clear_search_highlights(self):
        for card in self._cards:
            if isinstance(card, ParagraphCard):
                card.setStyleSheet(card.styleSheet().replace(
                    "border: 2px solid #e0af68;", "border: 1px solid #2a2c3d;"))
        self._search_matches = []
        self._search_index = -1

    # ---- 撤销 / 删除 / 拆分 ----

    def _on_undo_merge(self):
        for card in self._merged_hidden:
            card.setVisible(True)
            self._formatted.discard(card._index)
        self._merged_hidden.clear()
        self.undo_merge_btn.setVisible(False)
        self._apply_auto_visibility()
        self._save_state()

    def _on_delete_selected(self):
        to_remove = []
        for card in self._cards:
            if hasattr(card, 'is_selected') and card.is_selected():
                to_remove.append(card)
        if not to_remove:
            return
        for card in to_remove:
            self._formatted.discard(getattr(card, '_index', -1))
            # 记录被删图片路径/段落索引，下次打开不再渲染
            if isinstance(card, ImageCard):
                self._deleted_images.add(card._image_path)
            elif isinstance(card, ParagraphCard):
                self._deleted_paragraphs.add(card._index)
            self.card_layout.removeWidget(card)
            card.deleteLater()
            if card in self._cards:
                self._cards.remove(card)
        self._update_action_buttons()
        self._save_state()

    def _update_action_buttons(self):
        count = sum(1 for c in self._cards if hasattr(c, 'is_selected') and c.is_selected())
        self.merge_btn.setVisible(count >= 2)
        self.merge_btn.setEnabled(count >= 2)
        self.delete_btn.setVisible(count >= 1)
        self.delete_btn.setEnabled(count >= 1)

    def _on_split_card_by_range(self, card: ParagraphCard, sel_start: int, sel_end: int):
        text = card._text
        if sel_end <= sel_start or sel_start < 0 or sel_end > len(text):
            return
        parts = []
        if sel_start > 0:
            parts.append(text[:sel_start])
        parts.append(text[sel_start:sel_end])
        if sel_end < len(text):
            parts.append(text[sel_end:])
        parts = [p for p in parts if p]
        if len(parts) < 2:
            return
        card._text = parts[0]
        highlighted = _highlight_keywords(parts[0])
        card.text_label.setTextFormat(Qt.TextFormat.RichText)
        card.text_label.setText(highlighted)
        if card._index in self._formatted:
            self._formatted.discard(card._index)
        insert_after = card
        for part in parts[1:]:
            new_idx = max((c._index for c in self._cards if isinstance(c, ParagraphCard)), default=0) + 1
            new_card = ParagraphCard({"text": part, "is_heading": False, "is_meta": False, "page": 0}, new_idx)
            new_card.translate_requested.connect(self._on_translate)
            if hasattr(new_card, '_checkbox'):
                new_card._checkbox.stateChanged.connect(self._update_action_buttons)
            idx = self.card_layout.indexOf(insert_after)
            self.card_layout.insertWidget(idx + 1, new_card)
            self._cards.insert(self._cards.index(insert_after) + 1, new_card)
            insert_after = new_card
        self._save_state()

    # ---- 自动翻译 / 排版 ----

    def _on_toggle_auto_translate(self):
        self._auto_translate = not self._auto_translate
        if self._auto_translate:
            self.auto_trans_btn.setText("🔄 自动翻译：开")
            self.auto_trans_btn.setStyleSheet(
                "QPushButton { background-color: #7aa2f7; color: #1a1b26; font-weight: bold; }"
                "QPushButton:hover { background-color: #89b4fa; }"
            )
        else:
            self.auto_trans_btn.setText("🔄 自动翻译：关")
            self.auto_trans_btn.setStyleSheet("")
        self._apply_auto_visibility()

    def _on_toggle_auto_format(self):
        self._auto_format = not self._auto_format
        if self._auto_format:
            self.auto_format_btn.setText("📝 自动排版：开")
            self.auto_format_btn.setStyleSheet(
                "QPushButton { background-color: #7aa2f7; color: #1a1b26; font-weight: bold; }"
                "QPushButton:hover { background-color: #89b4fa; }"
            )
        else:
            self.auto_format_btn.setText("📝 自动排版：关")
            self.auto_format_btn.setStyleSheet("")
        self._apply_auto_visibility()
        # 如果开启自动排版，立即检查可见区域
        if self._auto_format:
            self._check_visible_and_format()

    # ---- 图像识别全文（多模态） ----

    def _on_start_image_analysis(self):
        """点击「🖼️ 图像识别全文」按钮——逐页渲染为图片发给多模态模型。"""
        if not self._llm_format and not self._llm_image:
            return
        if self._image_worker and self._image_worker.isRunning():
            return
        if not self._parser or not self._current_path:
            return

        client = self._llm_image or self._llm_format
        page_count = self._parser.page_count

        self._image_start_time = time.time()
        self.image_btn.setText(f"⏳ 0/{page_count} (0s)")
        self.image_btn.setEnabled(False)
        self._image_result_cache.clear()
        self._image_enabled = True

        self._analyze_next_image_page(client, 1, page_count)

    def _analyze_next_image_page(self, client, page_num: int, total: int):
        """渲染下一页并发送给多模态模型（只看图，不绑定PyMuPDF块编号）。"""
        if not self._image_enabled:
            return
        if page_num > total:
            self._on_image_analysis_complete()
            return

        try:
            img_b64 = self._parser.render_page_to_base64(page_num, dpi=72)
        except Exception as e:
            print(f"[PDFViewer] 渲染第{page_num}页失败: {e}")
            QTimer.singleShot(200, lambda: self._analyze_next_image_page(client, page_num + 1, total))
            return

        elapsed = int(time.time() - self._image_start_time)
        self.image_btn.setText(f"⏳ Mimo {page_num}/{total} ({elapsed}s)")

        if self._image_worker and not self._image_worker.isRunning():
            self._image_worker = None

        self._image_worker = ImageStructureWorker(client, page_num, img_b64, IMAGE_STRUCTURE_PROMPT)
        self._image_worker.done.connect(
            lambda p, r, c=client, t=total: self._on_image_page_done(p, r, c, t)
        )
        self._image_worker.err.connect(
            lambda p, e, c=client, t=total: self._on_image_page_err(p, e, c, t)
        )
        self._image_worker.start()

    def _on_image_page_done(self, page_num: int, result: dict, client, total: int):
        """单页图像识别完成——缓存结果，延迟后继续下一页。"""
        self._image_result_cache[page_num] = result
        n_elem = len(result.get("elements", []))
        role = result.get("page_role", "?")
        if result.get("parse_error"):
            print(f"[PDFViewer] 第{page_num}页解析警告 ({n_elem}元素, {role}): {result['parse_error']}")
        else:
            print(f"[PDFViewer] 第{page_num}页完成 ({n_elem}元素, {role})")
        # 500ms 延迟避免 API 限流
        QTimer.singleShot(500, lambda: self._analyze_next_image_page(client, page_num + 1, total))

    def _on_image_page_err(self, page_num: int, err: str, client, total: int):
        """单页图像识别失败——跳过，延迟后继续下一页。"""
        print(f"[PDFViewer] 第{page_num}页图像识别失败: {err}")
        self._image_result_cache[page_num] = {"page_role": "body", "elements": [], "reading_order": [], "parse_error": err}
        QTimer.singleShot(500, lambda: self._analyze_next_image_page(client, page_num + 1, total))

    def _on_image_analysis_complete(self):
        """Mimo 全部识别完成——启动 DeepSeek 整合步骤。"""
        total_ok = sum(
            1 for r in self._image_result_cache.values()
            if isinstance(r, dict) and not r.get("parse_error") and r.get("elements")
        )
        print(f"[PDFViewer] Mimo完成: {total_ok}/{len(self._image_result_cache)} 页有效")

        if total_ok == 0:
            self.image_btn.setText("❌ 无有效结果")
            self.image_btn.setStyleSheet("")
            self.image_btn.setEnabled(True)
            self._image_enabled = False
            return

        # 启动 DeepSeek 整合
        self.image_btn.setText("🧠 DeepSeek整合中...")
        self._start_integration()

    def _start_integration(self):
        """将 PyMuPDF 全文 + Mimo 结构描述发给 DeepSeek 整合。"""
        if not self._llm_chat_client:
            print("[PDFViewer] 未配置聊天API，无法整合")
            self._finish_image_analysis()
            return

        # 提取 PyMuPDF 按页全文
        page_texts = {}
        if self._parser:
            try:
                page_texts = self._parser.extract_text_by_page()
            except Exception as e:
                print(f"[PDFViewer] 提取按页文本失败: {e}")

        # 收集 Mimo 结构描述（只取有效的）
        page_structures = {
            pg: r for pg, r in self._image_result_cache.items()
            if isinstance(pg, int) and isinstance(r, dict) and not r.get("parse_error")
        }

        if not page_texts or not page_structures:
            print("[PDFViewer] 缺少材料，跳过整合")
            self._finish_image_analysis()
            return

        self._integration_worker = TextIntegrationWorker(
            self._llm_chat_client, page_texts, page_structures
        )
        self._integration_worker.done.connect(self._on_integration_done)
        self._integration_worker.err.connect(self._on_integration_err)
        self._integration_worker.finished.connect(
            lambda: setattr(self, '_integration_worker', None)
        )
        self._integration_worker.start()

    def _on_integration_done(self, integrated_text: str):
        """DeepSeek 整合完成——重建卡片。"""
        print(f"[PDFViewer] DeepSeek整合完成: {len(integrated_text)} 字符")
        self._integrated_text = integrated_text
        self._rebuild_from_integration(integrated_text)
        self._finish_image_analysis()

    def _on_integration_err(self, err: str):
        """DeepSeek 整合失败——用 Mimo 原始结果重建。"""
        print(f"[PDFViewer] DeepSeek整合失败: {err}")
        self._finish_image_analysis()

    def _finish_image_analysis(self):
        """清理图像分析状态。"""
        self.image_btn.setText("✅ 图像识别完成")
        self.image_btn.setStyleSheet(
            "QPushButton { background-color: #9ece6a; color: #1a1b26; font-weight: bold; }"
        )
        QTimer.singleShot(3000, lambda: (
            self.image_btn.setText("🖼️ 图像识别全文"),
            self.image_btn.setStyleSheet(""),
            self.image_btn.setEnabled(True),
        ))
        self._image_enabled = False
        self._save_state()

    def _rebuild_from_integration(self, integrated_text: str):
        """解析 DeepSeek 整合后的干净文本，重建卡片。

        标记格式:
            # 标题或章节名          → 大号蓝色卡片
            正文段落(无标记)         → 默认样式卡片
            -- 参考文献条目          → 小号灰色卡片
            ;; 元信息(作者/DOI等)    → 小号灰色卡片
            [图表页: 描述]           → 特殊卡片
        """
        new_paragraphs: list[dict] = []
        current_lines: list[str] = []
        current_type = "body"

        def _flush():
            nonlocal current_lines, current_type
            text = "\n".join(current_lines).strip()
            current_lines = []
            if not text:
                return
            is_heading = current_type == "heading"
            is_meta = current_type in ("meta", "ref")
            new_paragraphs.append({
                "text": text, "page": 0,
                "is_heading": is_heading, "is_meta": is_meta,
                "bbox": (0, 0, 0, 0), "_role": current_type,
            })

        for line in integrated_text.split("\n"):
            stripped = line.strip()
            if not stripped:
                _flush()
                continue

            if stripped.startswith("# "):
                _flush()
                current_type = "heading"
                current_lines.append(stripped[2:])
            elif stripped.startswith("-- "):
                _flush()
                current_type = "ref"
                current_lines.append(stripped[3:])
            elif stripped.startswith(";; "):
                _flush()
                current_type = "meta"
                current_lines.append(stripped[3:])
            elif stripped.startswith("[图表页:"):
                _flush()
                current_type = "figure_page"
                current_lines.append(stripped)
            else:
                if not current_lines:
                    current_type = "body"
                current_lines.append(stripped)

        _flush()

        if not new_paragraphs:
            # 降级: 按空行分段
            for para in integrated_text.split("\n\n"):
                para = para.strip()
                if para:
                    # 去掉可能的标记前缀
                    if para.startswith("# "):
                        role = "heading"
                        para = para[2:]
                    elif para.startswith("-- "):
                        role = "ref"
                        para = para[3:]
                    elif para.startswith(";; "):
                        role = "meta"
                        para = para[3:]
                    else:
                        role = "body"
                    new_paragraphs.append({
                        "text": para, "page": 0,
                        "is_heading": role == "heading",
                        "is_meta": role in ("meta", "ref"),
                        "bbox": (0, 0, 0, 0), "_role": role,
                    })

        # 结构映射
        self._structure_map.clear()
        for i, para in enumerate(new_paragraphs):
            role = para.get("_role", "body")
            mapped = {"heading": "section_header", "meta": "metadata",
                      "ref": "reference", "figure_page": "body"}.get(role, "body")
            self._structure_map[i] = {"label": mapped, "section_name": None}
            if role == "heading":
                self._structure_map[i]["section_name"] = para["text"][:80]

        self._paragraphs = new_paragraphs
        self._formatted = set(range(len(new_paragraphs)))
        self._render_content()

        for card in self._cards:
            if isinstance(card, ParagraphCard) and card._index in self._structure_map:
                self._apply_structure_style(card, self._structure_map[card._index])

        print(f"[PDFViewer] 整合完成: {len(new_paragraphs)} 卡")

    def _apply_auto_visibility(self):
        for card in self._cards:
            if not isinstance(card, ParagraphCard):
                continue
            # 翻译按钮
            if hasattr(card, 'trans_btn'):
                if self._auto_translate:
                    card.trans_btn.setVisible(False)
                else:
                    card.trans_btn.setVisible(not card._translated)
            # 排版按钮
            if hasattr(card, 'format_btn'):
                if self._auto_format:
                    card.format_btn.setVisible(False)
                else:
                    card.format_btn.setVisible(card._index not in self._formatted)

    def _auto_translate_card(self, card):
        if not self._llm_trans or card._translated or not hasattr(card, 'trans_btn'):
            return
        card._request()
