"""
聊天面板 —— 侧边栏聊天界面
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QScrollArea, QLabel, QSizePolicy, QFrame,
)
from PySide6.QtCore import Qt, Signal, QTimer, QEvent
from PySide6.QtGui import QFont, QKeyEvent


class ChatBubble(QFrame):
    """单条聊天气泡 —— 优化可读性"""

    def __init__(self, role: str, content: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)

        # 角色标签
        role_label = QLabel("🤖 AI 回答" if role == "assistant" else "👤 你的问题")
        role_font = QFont("Microsoft YaHei UI", 11)
        role_font.setBold(True)
        role_label.setFont(role_font)
        role_label.setStyleSheet(
            "color: #7aa2f7; padding: 2px 0;" if role == "assistant"
            else "color: #9ece6a; padding: 2px 0;"
        )
        layout.addWidget(role_label)

        # 内容 —— 大字号，高对比度
        content_label = QLabel(content)
        content_label.setWordWrap(True)
        content_label.setTextFormat(Qt.TextFormat.MarkdownText)
        content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        content_font = QFont("Microsoft YaHei UI", 13)
        content_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.2)
        content_label.setFont(content_font)
        content_label.setStyleSheet(
            "color: #e2e5f2; line-height: 1.7; padding: 4px 0;"
        )
        layout.addWidget(content_label)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #2a2c3d; max-height: 1px; margin-top: 4px;")
        layout.addWidget(sep)

    def update_content(self, content: str):
        """更新气泡内容（用于流式输出）"""
        for i in range(self.layout().count()):
            w = self.layout().itemAt(i).widget()
            if isinstance(w, QLabel) and "color: #e2e5f2" in (w.styleSheet() or ""):
                w.setText(content)
                break


class ChatPanel(QWidget):
    """聊天面板：消息列表 + 输入区"""

    send_message = Signal(str)       # 用户发送消息
    clear_requested = Signal()       # 请求清空对话

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bubbles: list[ChatBubble] = []
        self._current_ai_bubble: ChatBubble | None = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部工具栏
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(12, 8, 12, 8)

        title = QLabel("💬 对话")
        title.setObjectName("titleLabel")
        toolbar.addWidget(title)

        toolbar.addStretch()

        clear_btn = QPushButton("清空对话")
        clear_btn.clicked.connect(self._on_clear)
        toolbar.addWidget(clear_btn)

        layout.addLayout(toolbar)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #313244; max-height: 1px;")
        layout.addWidget(sep)

        # 消息滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.msg_container = QWidget()
        self.msg_layout = QVBoxLayout(self.msg_container)
        self.msg_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.msg_layout.addStretch()

        # 欢迎消息
        welcome = QLabel(
            "👋 欢迎使用 PDFasker！\n\n"
            "使用方法：\n"
            "1. 从左侧论文库选择或导入 PDF\n"
            "2. 在下方输入框输入你的问题\n"
            "3. AI 将基于论文内容为你解答\n\n"
            "📌 请先在设置中配置 API Key"
        )
        welcome.setWordWrap(True)
        welcome.setStyleSheet("color: #9599b5; padding: 24px; font-size: 13px;")
        self.msg_layout.insertWidget(0, welcome)

        self.scroll_area.setWidget(self.msg_container)
        layout.addWidget(self.scroll_area, 1)

        # 输入区
        input_frame = QFrame()
        input_frame.setStyleSheet("background-color: #161720; border-top: 1px solid #2a2c3d;")
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(12, 10, 12, 12)

        self.input_box = QTextEdit()
        self.input_box.setPlaceholderText("输入你的问题，按 Ctrl+Enter 发送...")
        self.input_box.setMaximumHeight(120)
        self.input_box.setMinimumHeight(64)
        input_layout.addWidget(self.input_box)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.send_btn = QPushButton("发送 ✈")
        self.send_btn.setObjectName("primaryBtn")
        self.send_btn.clicked.connect(self._on_send)
        self.send_btn.setEnabled(False)
        btn_layout.addWidget(self.send_btn)

        input_layout.addLayout(btn_layout)
        layout.addWidget(input_frame)

        # 快捷键：Ctrl+Enter 发送
        self.input_box.installEventFilter(self)

    def eventFilter(self, obj, event):
        """处理快捷键"""
        if obj == self.input_box and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    def _on_send(self):
        text = self.input_box.toPlainText().strip()
        if not text:
            return
        self.input_box.clear()
        self.send_btn.setEnabled(False)
        self.send_message.emit(text)

    def _on_clear(self):
        self.clear_requested.emit()

    def add_user_message(self, text: str):
        """添加用户消息气泡"""
        bubble = ChatBubble("user", text)
        self._insert_bubble(bubble)
        self._bubbles.append(bubble)

    def start_ai_response(self):
        """开始 AI 回复（创建空气泡用于流式填充）"""
        bubble = ChatBubble("assistant", "")
        self._insert_bubble(bubble)
        self._current_ai_bubble = bubble
        self._bubbles.append(bubble)

    def append_ai_text(self, chunk: str):
        """追加 AI 回复文本（流式）"""
        if self._current_ai_bubble:
            # 累积文本并更新
            for i in range(self._current_ai_bubble.layout().count()):
                w = self._current_ai_bubble.layout().itemAt(i).widget()
                if isinstance(w, QLabel) and w.styleSheet() == "":
                    current = w.text()
                    w.setText(current + chunk)
                    break
        self._scroll_to_bottom()

    def finish_ai_response(self):
        """完成 AI 回复"""
        self._current_ai_bubble = None
        self.send_btn.setEnabled(True)

    def clear_messages(self):
        """清除所有消息"""
        self._bubbles.clear()
        self._current_ai_bubble = None
        while self.msg_layout.count() > 1:
            item = self.msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.msg_layout.addStretch()
        self.send_btn.setEnabled(True)

    def _insert_bubble_from_history(self, role: str, content: str):
        """从历史记录恢复气泡（不做动画）"""
        bubble = ChatBubble(role, content)
        self._insert_bubble(bubble)
        self._bubbles.append(bubble)

    def set_input_enabled(self, enabled: bool):
        """设置输入框是否可用"""
        self.input_box.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)

    def _insert_bubble(self, bubble: ChatBubble):
        """在 stretch 之前插入气泡"""
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, bubble)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """滚动到底部"""
        QTimer.singleShot(50, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))
