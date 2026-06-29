"""
PDF 查看面板 —— 显示 PDF 文本内容
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QFileDialog, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal


class PDFViewerPanel(QWidget):
    """PDF 文本查看面板，支持加载和预览"""

    pdf_loaded = Signal(str)       # PDF 文本加载完成
    pdf_path_changed = Signal(str) # PDF 路径变更

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pdf_text: str = ""
        self._current_path: str = ""
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部工具栏
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(12, 8, 12, 8)

        title = QLabel("📄 PDF 阅读器")
        title.setObjectName("titleLabel")
        toolbar.addWidget(title)

        toolbar.addStretch()

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

        self.info_label = QLabel("尚未加载 PDF")
        self.info_label.setObjectName("subtitleLabel")
        info_bar.addWidget(self.info_label)

        info_bar.addStretch()

        self.page_count_label = QLabel("")
        self.page_count_label.setObjectName("subtitleLabel")
        info_bar.addWidget(self.page_count_label)

        layout.addLayout(info_bar)

        # 文本显示区
        self.text_view = QTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setPlaceholderText(
            "点击「打开 PDF」加载一篇论文...\n\n"
            "支持功能：\n"
            "• 提取 PDF 全部文本\n"
            "• 保留页码信息\n"
            "• 在右侧对话区向 AI 提问"
        )
        self.text_view.setStyleSheet(
            "QTextEdit { background-color: #1e1e2e; border: none; padding: 12px; }"
        )
        layout.addWidget(self.text_view, 1)

    def _open_pdf(self):
        """打开 PDF 文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 PDF 文件",
            "",
            "PDF 文件 (*.pdf);;所有文件 (*.*)",
        )
        if not file_path:
            return

        self._current_path = file_path
        self.pdf_path_changed.emit(file_path)
        self.load_pdf(file_path)

    def load_pdf(self, file_path: str):
        """加载并显示 PDF 文本"""
        try:
            from ..core.pdf_parser import PDFParser

            self.info_label.setText(f"📖 正在加载: {file_path}")
            self.info_label.setStyleSheet("color: #f9e2af;")
            self.text_view.setPlainText("正在解析 PDF...")

            with PDFParser(file_path) as parser:
                self._pdf_text = parser.extract_full_text()
                page_count = parser.page_count
                preview = parser.get_text_preview(max_chars=50000)

            self.text_view.setPlainText(preview)
            self.page_count_label.setText(f"共 {page_count} 页")
            self.info_label.setText(f"📖 已加载")
            self.info_label.setStyleSheet("color: #a6e3a1;")

            self.pdf_loaded.emit(self._pdf_text)

        except Exception as e:
            self.text_view.setPlainText(f"❌ 解析 PDF 失败：\n{str(e)}")
            self.info_label.setText("❌ 加载失败")
            self.info_label.setStyleSheet("color: #f38ba8;")
            self.page_count_label.setText("")

    def get_pdf_text(self) -> str:
        return self._pdf_text

    def get_current_path(self) -> str:
        return self._current_path
