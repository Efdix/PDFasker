"""
PDF 阅读器 —— 精致段落视图 + 中英对照翻译
"""

import re
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QPushButton,
    QLabel, QFrame, QFileDialog, QProgressBar,
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont


# ========== 段落翻译后台线程 ==========

class TranslationWorker(QThread):
    """后台线程：调用 LLM 翻译单段文本"""
    finished = Signal(int, str)  # paragraph_index, translated_text
    error = Signal(int, str)     # paragraph_index, error_message

    def __init__(self, client, paragraph_index: int, text: str):
        super().__init__()
        self._client = client
        self._idx = paragraph_index
        self._text = text

    def run(self):
        try:
            result = self._client.chat_sync([
                {
                    "role": "system",
                    "content": (
                        "你是一个学术论文翻译助手。请将以下英文段落翻译成中文。"
                        "要求：\n"
                        "1. 保持学术术语的准确性，专业术语首次出现时保留英文并括号注中文\n"
                        "2. 保留原文的段落结构和逻辑关系\n"
                        "3. 翻译自然流畅，符合中文学术写作习惯\n"
                        "4. 只输出中文译文，不要添加任何额外说明"
                    ),
                },
                {"role": "user", "content": self._text},
            ])
            self.finished.emit(self._idx, result)
        except Exception as e:
            self.error.emit(self._idx, str(e))


# ========== 段落卡片组件 ==========

class ParagraphCard(QFrame):
    """单段文本卡片，支持中英对照显示"""

    translate_requested = Signal(int, str)  # index, text

    def __init__(self, index: int, text: str, is_english: bool, parent=None):
        super().__init__(parent)
        self._index = index
        self._text = text
        self._is_english = is_english
        self._translated = False
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "ParagraphCard {"
            "  background-color: #181825;"
            "  border: 1px solid #313244;"
            "  border-radius: 8px;"
            "  margin: 4px 8px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # 原文标签
        self.text_label = QLabel(self._text)
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        if self._is_english:
            en_font = QFont("Segoe UI", 11)
            en_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.3)
            self.text_label.setFont(en_font)
            self.text_label.setStyleSheet("color: #cdd6f4; line-height: 1.8;")
        else:
            self.text_label.setStyleSheet("color: #cdd6f4; line-height: 1.8;")
        layout.addWidget(self.text_label)

        # 中英对照（仅英文段落）
        if self._is_english:
            self.trans_sep = QFrame()
            self.trans_sep.setFrameShape(QFrame.Shape.HLine)
            self.trans_sep.setStyleSheet("background-color: #45475a; max-height: 1px;")
            self.trans_sep.setVisible(False)
            layout.addWidget(self.trans_sep)

            self.zh_label = QLabel()
            self.zh_label.setWordWrap(True)
            self.zh_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            zh_font = QFont("Microsoft YaHei", 11)
            self.zh_label.setFont(zh_font)
            self.zh_label.setStyleSheet("color: #a6e3a1; line-height: 1.8;")
            self.zh_label.setVisible(False)
            layout.addWidget(self.zh_label)

            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            self.trans_btn = QPushButton("🌐 翻译本段")
            self.trans_btn.setFixedWidth(120)
            self.trans_btn.clicked.connect(self._request_translation)
            btn_layout.addWidget(self.trans_btn)
            layout.addLayout(btn_layout)

    def _request_translation(self):
        if not self._translated:
            self.trans_btn.setText("⏳ 翻译中...")
            self.trans_btn.setEnabled(False)
            self.translate_requested.emit(self._index, self._text)

    def show_translation(self, zh_text: str):
        self._translated = True
        self.trans_sep.setVisible(True)
        self.zh_label.setText(zh_text)
        self.zh_label.setVisible(True)
        self.trans_btn.setText("✅ 已翻译")
        self.trans_btn.setStyleSheet("color: #a6e3a1;")

    def show_translation_error(self, error: str):
        self.trans_btn.setText("❌ 失败")
        self.trans_btn.setEnabled(True)
        self.trans_btn.setToolTip(error)


# ========== PDF 阅读器主体 ==========

class PDFViewerPanel(QWidget):
    """PDF 阅读器 —— 段落视图 + 中英对照"""

    pdf_loaded = Signal(str)
    pdf_path_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pdf_text: str = ""
        self._paragraphs: list[str] = []
        self._cards: list[ParagraphCard] = []
        self._current_path: str = ""
        self._llm_client = None
        self._trans_worker: TranslationWorker | None = None
        self._pending_translations: dict[int, str] = {}
        self._setup_ui()

    def set_llm_client(self, client):
        self._llm_client = client

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部工具栏
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(12, 8, 12, 8)
        title = QLabel("📖 论文阅读")
        title.setObjectName("titleLabel")
        toolbar.addWidget(title)
        toolbar.addStretch()

        self.batch_trans_btn = QPushButton("🌐 全文翻译")
        self.batch_trans_btn.setToolTip("逐段翻译所有英文段落")
        self.batch_trans_btn.clicked.connect(self._batch_translate)
        self.batch_trans_btn.setEnabled(False)
        toolbar.addWidget(self.batch_trans_btn)

        self.open_btn = QPushButton("打开 PDF")
        self.open_btn.setObjectName("primaryBtn")
        self.open_btn.clicked.connect(self._open_pdf)
        toolbar.addWidget(self.open_btn)
        layout.addLayout(toolbar)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #313244; max-height: 1px;")
        layout.addWidget(sep)

        # 信息栏
        info_bar = QHBoxLayout()
        info_bar.setContentsMargins(12, 4, 12, 4)
        self.info_label = QLabel("尚未加载 PDF — 请从左侧论文库选择或点击「打开 PDF」")
        self.info_label.setObjectName("subtitleLabel")
        info_bar.addWidget(self.info_label)
        info_bar.addStretch()
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        info_bar.addWidget(self.progress_bar)
        layout.addLayout(info_bar)

        # 阅读滚动区
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.reader_container = QWidget()
        self.reader_layout = QVBoxLayout(self.reader_container)
        self.reader_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.reader_layout.setSpacing(4)
        self.reader_layout.setContentsMargins(0, 8, 0, 8)

        self.placeholder = QLabel(
            "📄 点击「打开 PDF」或从左侧论文库选择一篇论文开始阅读\n\n"
            "功能亮点：\n"
            "• 段落式精致排版，告别密密麻麻的文本\n"
            "• 英文段落一键翻译，中英对照阅读\n"
            "• 支持全文批量翻译"
        )
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet("color: #6c7086; padding: 60px; font-size: 14px;")
        self.reader_layout.addWidget(self.placeholder)

        self.scroll_area.setWidget(self.reader_container)
        layout.addWidget(self.scroll_area, 1)

    def _open_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 PDF 文件", "", "PDF 文件 (*.pdf);;所有文件 (*.*)"
        )
        if file_path:
            self.load_pdf(file_path)

    def load_pdf(self, file_path: str):
        self._current_path = file_path
        self.pdf_path_changed.emit(file_path)
        try:
            from ..core.pdf_parser import PDFParser
            self.info_label.setText("⏳ 正在解析...")
            self.info_label.setStyleSheet("color: #f9e2af;")
            with PDFParser(file_path) as parser:
                self._pdf_text = parser.extract_full_text()
                page_count = parser.page_count
            self._paragraphs = self._split_paragraphs(self._pdf_text)
            self._render_paragraphs()
            self.info_label.setText(f"📖 已加载 · {page_count} 页 · {len(self._paragraphs)} 段")
            self.info_label.setStyleSheet("color: #a6e3a1;")
            self.batch_trans_btn.setEnabled(True)
            self.pdf_loaded.emit(self._pdf_text)
        except Exception as e:
            self.info_label.setText(f"❌ 加载失败：{e}")
            self.info_label.setStyleSheet("color: #f38ba8;")

    def _split_paragraphs(self, text: str) -> list[str]:
        """智能分段：按双换行 + 章节标题识别"""
        clean = re.sub(r'\[第 \d+ 页\]\n?', '', text)
        raw_paras = re.split(r'\n\s*\n', clean)
        paragraphs = []
        buffer = ""
        for para in raw_paras:
            para = para.strip()
            if not para:
                continue
            is_heading = (
                len(para) < 100 and (
                    para.isupper() or
                    re.match(r'^[IVX]+\.\s', para) or
                    re.match(r'^\d+[\.\)]\s', para) or
                    re.match(r'^(Abstract|Introduction|References|Conclusion|Method|Result|Discussion|Appendix|Related Work|Background)', para, re.IGNORECASE)
                )
            )
            if is_heading:
                if buffer.strip():
                    paragraphs.append(buffer.strip())
                    buffer = ""
                paragraphs.append(para)
            elif len(para) < 80 and buffer:
                buffer += " " + para
            else:
                if buffer.strip():
                    paragraphs.append(buffer.strip())
                buffer = para
        if buffer.strip():
            paragraphs.append(buffer.strip())
        return paragraphs

    def _is_english(self, text: str) -> bool:
        alpha_count = sum(1 for c in text if c.isascii() and c.isalpha())
        total = max(len(text), 1)
        return (alpha_count / total) > 0.55

    def _render_paragraphs(self):
        self._cards.clear()
        while self.reader_layout.count():
            item = self.reader_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, para in enumerate(self._paragraphs):
            is_en = self._is_english(para)
            card = ParagraphCard(i, para, is_en)
            card.translate_requested.connect(self._on_translate_requested)
            self.reader_layout.addWidget(card)
            self._cards.append(card)
        self.reader_layout.addStretch()

    def _on_translate_requested(self, idx: int, text: str):
        if not self._llm_client:
            return
        if self._trans_worker and self._trans_worker.isRunning():
            self._pending_translations[idx] = text
            return
        self._start_translation(idx, text)

    def _start_translation(self, idx: int, text: str):
        self._trans_worker = TranslationWorker(self._llm_client, idx, text)
        self._trans_worker.finished.connect(self._on_translation_done)
        self._trans_worker.error.connect(self._on_translation_error)
        self._trans_worker.start()

    def _on_translation_done(self, idx: int, zh_text: str):
        if 0 <= idx < len(self._cards):
            self._cards[idx].show_translation(zh_text)
        self._process_next_translation()

    def _on_translation_error(self, idx: int, error: str):
        if 0 <= idx < len(self._cards):
            self._cards[idx].show_translation_error(error)
        self._process_next_translation()

    def _process_next_translation(self):
        if self._pending_translations:
            idx, text = next(iter(self._pending_translations.items()))
            del self._pending_translations[idx]
            self._start_translation(idx, text)

    def _batch_translate(self):
        if not self._llm_client:
            return
        self.batch_trans_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(self._cards))
        count = 0
        for i, card in enumerate(self._cards):
            if card._is_english and not card._translated:
                card._request_translation()
                count += 1
        if count == 0:
            self.progress_bar.setVisible(False)
            self.batch_trans_btn.setEnabled(True)

    def get_pdf_text(self) -> str:
        return self._pdf_text

    def get_current_path(self) -> str:
        return self._current_path
