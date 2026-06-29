"""
PDF 阅读器 —— 结构化段落 + 图片展示 + 中英对照
"""

import os
import tempfile
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QPushButton,
    QLabel, QFrame, QFileDialog, QProgressBar,
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont, QPixmap


# ========== 段落翻译后台线程 ==========

class TranslationWorker(QThread):
    finished = Signal(int, str)
    error = Signal(int, str)

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
                        "你是学术论文翻译助手。将英文段落译成中文。"
                        "要求：1) 术语准确，首次出现时保留英文并括号注中文；"
                        "2) 保持段落结构和逻辑；3) 自然流畅；4) 只输出译文。"
                    ),
                },
                {"role": "user", "content": self._text},
            ])
            self.finished.emit(self._idx, result)
        except Exception as e:
            self.error.emit(self._idx, str(e))


# ========== 段落卡片 ==========

class ParagraphCard(QFrame):
    translate_requested = Signal(int, str)

    def __init__(self, para: dict, index: int, parent=None):
        super().__init__(parent)
        self._index = index
        self._text = para.get("text", "")
        self._is_heading = para.get("is_heading", False)
        self._is_english = self._detect_english(self._text)
        self._translated = False
        self._setup_ui()

    def _detect_english(self, text: str) -> bool:
        if not text:
            return False
        alpha = sum(1 for c in text if c.isascii() and c.isalpha())
        return (alpha / max(len(text), 1)) > 0.55

    def _setup_ui(self):
        self.setStyleSheet(
            "ParagraphCard {"
            "  background-color: #1a1b26;"
            "  border: 1px solid #2a2c3d;"
            "  border-radius: 10px;"
            "  margin: 6px 12px;"
            "}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        # 标题样式
        if self._is_heading:
            heading_font = QFont("Microsoft YaHei UI", 14)
            heading_font.setBold(True)
            self.text_label = QLabel(self._text)
            self.text_label.setFont(heading_font)
            self.text_label.setStyleSheet("color: #7aa2f7; padding: 4px 0;")
        else:
            if self._is_english:
                text_font = QFont("Segoe UI", 12)
                text_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.3)
            else:
                text_font = QFont("Microsoft YaHei UI", 12)
            self.text_label = QLabel(self._text)
            self.text_label.setFont(text_font)
            self.text_label.setStyleSheet(
                "color: #cfd2e3; line-height: 1.8; padding: 2px 0;"
            )
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.text_label)

        # 翻译区（仅非标题的英文段落）
        if self._is_english and not self._is_heading and len(self._text) > 50:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet("background-color: #2a2c3d; max-height: 1px;")
            self.trans_sep = sep
            layout.addWidget(self.trans_sep)

            zh_font = QFont("Microsoft YaHei UI", 12)
            self.zh_label = QLabel()
            self.zh_label.setFont(zh_font)
            self.zh_label.setWordWrap(True)
            self.zh_label.setStyleSheet("color: #9ece6a; line-height: 1.8; padding: 4px 0;")
            self.zh_label.setVisible(False)
            self.zh_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(self.zh_label)

            btn_row = QHBoxLayout()
            btn_row.addStretch()
            self.trans_btn = QPushButton("🌐 翻译")
            self.trans_btn.setFixedWidth(90)
            self.trans_btn.clicked.connect(self._request)
            btn_row.addWidget(self.trans_btn)
            layout.addLayout(btn_row)

    def _request(self):
        if not self._translated:
            self.trans_btn.setText("⏳")
            self.trans_btn.setEnabled(False)
            self.translate_requested.emit(self._index, self._text)

    def show_translation(self, zh: str):
        self._translated = True
        self.zh_label.setText(zh)
        self.zh_label.setVisible(True)
        self.trans_btn.setText("✅")
        self.trans_btn.setStyleSheet("color: #9ece6a;")

    def show_error(self, err: str):
        self.trans_btn.setText("❌")
        self.trans_btn.setEnabled(True)
        self.trans_btn.setToolTip(err)


# ========== 图片卡片 ==========

class ImageCard(QFrame):
    """PDF 中的图片"""

    def __init__(self, image_path: str, page: int, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "ImageCard {"
            "  background-color: #1a1b26;"
            "  border: 1px solid #2a2c3d;"
            "  border-radius: 10px;"
            "  margin: 6px 12px;"
            "}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        page_label = QLabel(f"📷 第 {page} 页插图")
        page_label.setStyleSheet("color: #9599b5; font-size: 11px;")
        page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(page_label)

        if image_path and os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                # 限制最大宽度
                if pixmap.width() > 600:
                    pixmap = pixmap.scaledToWidth(600, Qt.TransformationMode.SmoothTransformation)
                img_label = QLabel()
                img_label.setPixmap(pixmap)
                img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(img_label)


# ========== PDF 阅读器 ==========

class PDFViewerPanel(QWidget):
    pdf_loaded = Signal(str)
    pdf_path_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pdf_text: str = ""
        self._paragraphs: list[dict] = []
        self._cards: list = []
        self._current_path: str = ""
        self._llm_client = None
        self._trans_worker: TranslationWorker | None = None
        self._pending: dict[int, str] = {}
        self._image_dir = ""
        self._setup_ui()

    def set_llm_client(self, client):
        self._llm_client = client

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

        self.batch_btn = QPushButton("🌐 全译")
        self.batch_btn.setToolTip("翻译所有英文段落")
        self.batch_btn.clicked.connect(self._batch_translate)
        self.batch_btn.setEnabled(False)
        toolbar.addWidget(self.batch_btn)

        self.open_btn = QPushButton("打开 PDF")
        self.open_btn.setObjectName("primaryBtn")
        self.open_btn.clicked.connect(self._open_pdf)
        toolbar.addWidget(self.open_btn)
        layout.addLayout(toolbar)

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
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(180)
        self.progress_bar.setVisible(False)
        info.addWidget(self.progress_bar)
        layout.addLayout(info)

        # 阅读区
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: #1a1b26; }")

        self.container = QWidget()
        self.container.setStyleSheet("background: #1a1b26;")
        self.card_layout = QVBoxLayout(self.container)
        self.card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.card_layout.setSpacing(0)
        self.card_layout.setContentsMargins(0, 10, 0, 20)

        self.placeholder = QLabel(
            "📄 点击「打开 PDF」或从左侧论文库选择论文\n\n"
            "• 段落式排版，清晰可读\n"
            "• 图片自动提取展示\n"
            "• 英文段落一键中英对照\n"
            "• 章节标题自动识别高亮"
        )
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet("color: #636688; padding: 80px 40px; font-size: 15px;")
        self.card_layout.addWidget(self.placeholder)

        self.scroll_area.setWidget(self.container)
        layout.addWidget(self.scroll_area, 1)

    def _open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 PDF", "", "PDF (*.pdf);;All (*.*)")
        if path:
            self.load_pdf(path)

    def load_pdf(self, file_path: str):
        self._current_path = file_path
        self.pdf_path_changed.emit(file_path)

        try:
            from ..core.pdf_parser import PDFParser

            self.info_label.setText("⏳ 解析中...")
            self.info_label.setStyleSheet("color: #e0af68;")

            # 创建临时图片目录
            self._image_dir = tempfile.mkdtemp(prefix="pdfasker_img_")

            with PDFParser(file_path) as parser:
                parser.set_image_output_dir(self._image_dir)
                self._pdf_text = parser.extract_full_text()
                page_count = parser.page_count
                # 使用新的结构化分段
                self._paragraphs = parser.extract_structured_paragraphs()

            self._render_content()
            self.info_label.setText(
                f"📖 已加载 · {page_count} 页 · {len(self._paragraphs)} 段"
            )
            self.info_label.setStyleSheet("color: #9ece6a;")
            self.batch_btn.setEnabled(True)
            self.pdf_loaded.emit(self._pdf_text)

        except Exception as e:
            self.info_label.setText(f"❌ 加载失败：{e}")
            self.info_label.setStyleSheet("color: #f7768e;")

    def _render_content(self):
        """渲染结构化段落和图片"""
        self._cards.clear()
        # 清除旧内容
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, para in enumerate(self._paragraphs):
            if para.get("image_path"):
                # 图片卡片
                card = ImageCard(para["image_path"], para.get("page", 0))
                self.card_layout.addWidget(card)
                self._cards.append(card)
            elif para.get("text", "").strip():
                # 段落卡片
                card = ParagraphCard(para, i)
                card.translate_requested.connect(self._on_translate)
                self.card_layout.addWidget(card)
                self._cards.append(card)

        self.card_layout.addStretch()

    def _on_translate(self, idx: int, text: str):
        if not self._llm_client:
            return
        if self._trans_worker and self._trans_worker.isRunning():
            self._pending[idx] = text
            return
        self._start_trans(idx, text)

    def _start_trans(self, idx: int, text: str):
        self._trans_worker = TranslationWorker(self._llm_client, idx, text)
        self._trans_worker.finished.connect(self._on_done)
        self._trans_worker.error.connect(self._on_err)
        self._trans_worker.start()

    def _on_done(self, idx: int, zh: str):
        for card in self._cards:
            if isinstance(card, ParagraphCard) and card._index == idx:
                card.show_translation(zh)
                break
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

    def _batch_translate(self):
        if not self._llm_client:
            return
        self.batch_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        count = 0
        for card in self._cards:
            if isinstance(card, ParagraphCard) and card._is_english and not card._translated and not card._is_heading:
                card._request()
                count += 1
        if count == 0:
            self.progress_bar.setVisible(False)
            self.batch_btn.setEnabled(True)

    def get_pdf_text(self) -> str:
        return self._pdf_text

    def get_current_path(self) -> str:
        return self._current_path
