"""
PDFasker 主应用窗口
"""

from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QMessageBox, QMenuBar, QMenu,
    QStatusBar, QLabel,
)
from PySide6.QtCore import Qt, QThread, Signal as QtSignal
from PySide6.QtGui import QAction

from .ui.styles import STYLESHEET
from .ui.pdf_viewer import PDFViewerPanel
from .ui.chat_panel import ChatPanel
from .ui.settings_dialog import SettingsDialog
from .core.llm_client import LLMClient
from .core.context_manager import ContextManager
from .utils.config import load_config


class LLMWorker(QThread):
    """后台线程：调用 LLM API，避免阻塞 UI"""

    chunk_received = QtSignal(str)
    finished = QtSignal()
    error = QtSignal(str)

    def __init__(self, client: LLMClient, messages: list[dict]):
        super().__init__()
        self._client = client
        self._messages = messages

    def run(self):
        try:
            for chunk in self._client.chat(self._messages, stream=True):
                self.chunk_received.emit(chunk)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """PDFasker 主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDFasker — AI 论文解读助手")
        self.resize(1280, 800)
        self.setMinimumSize(900, 600)

        # 核心组件
        self._config = load_config()
        self._llm_client: LLMClient | None = None
        self._context_manager = ContextManager(
            max_tokens=self._config.get("max_tokens", 1_000_000)
        )
        self._llm_worker: LLMWorker | None = None

        # UI
        self._setup_ui()
        self._apply_styles()
        self._try_init_llm_client()

    def _setup_ui(self):
        """构建界面布局"""
        # 菜单栏
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件(&F)")
        open_action = QAction("打开 PDF...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open_pdf)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        settings_menu = menubar.addMenu("设置(&S)")
        api_action = QAction("API 配置...", self)
        api_action.setShortcut("Ctrl+,")
        api_action.triggered.connect(self._on_open_settings)
        settings_menu.addAction(api_action)

        help_menu = menubar.addMenu("帮助(&H)")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

        # 主分割器：左侧 PDF 查看器 + 右侧聊天面板
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)

        self.pdf_viewer = PDFViewerPanel()
        self.pdf_viewer.pdf_loaded.connect(self._on_pdf_loaded)
        self.pdf_viewer.pdf_path_changed.connect(self._on_pdf_path_changed)

        self.chat_panel = ChatPanel()
        self.chat_panel.send_message.connect(self._on_user_message)
        self.chat_panel.clear_requested.connect(self._on_clear_chat)

        splitter.addWidget(self.pdf_viewer)
        splitter.addWidget(self.chat_panel)
        splitter.setSizes([600, 680])  # 初始比例

        self.setCentralWidget(splitter)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._status_model_label = QLabel("未配置 API")
        self._status_model_label.setStyleSheet("color: #a6adc8; padding: 2px 8px;")
        self.status_bar.addPermanentWidget(self._status_model_label)

    def _apply_styles(self):
        """应用全局样式"""
        self.setStyleSheet(STYLESHEET)

    # ========== 事件处理 ==========

    def _on_open_pdf(self):
        """菜单栏或快捷键打开 PDF"""
        self.pdf_viewer._open_pdf()

    def _on_pdf_loaded(self, text: str):
        """PDF 加载完成后初始化上下文"""
        self._context_manager.load_pdf_text(text)
        token_est = self._context_manager.estimate_tokens(text)
        self.status_bar.showMessage(
            f"PDF 已加载 | 约 {token_est:,} tokens | "
            f"共 {len(text):,} 字符"
        )
        self.chat_panel.set_input_enabled(True)

    def _on_pdf_path_changed(self, path: str):
        """PDF 路径变更时更新标题"""
        import os
        fname = os.path.basename(path) if path else ""
        self.setWindowTitle(f"PDFasker — {fname}" if fname else "PDFasker — AI 论文解读助手")

    def _on_user_message(self, text: str):
        """用户发送消息"""
        if not self._llm_client:
            QMessageBox.warning(
                self, "未配置 API",
                "请先配置 API Key 和 Base URL。\n菜单 → 设置 → API 配置"
            )
            self.chat_panel.set_input_enabled(True)
            return

        if not self._context_manager._pdf_text:
            QMessageBox.warning(
                self, "未加载 PDF",
                "请先打开一个 PDF 文件。"
            )
            self.chat_panel.set_input_enabled(True)
            return

        # 显示用户消息
        self.chat_panel.add_user_message(text)
        self._context_manager.add_to_history("user", text)

        # 构建消息并调用 LLM
        messages = self._context_manager.build_messages(text)

        # 开始 AI 回复
        self.chat_panel.start_ai_response()
        self.chat_panel.send_btn.setEnabled(False)
        self.status_bar.showMessage("AI 正在思考...")

        # 后台线程调用 API
        self._llm_worker = LLMWorker(self._llm_client, messages)
        self._llm_worker.chunk_received.connect(self._on_ai_chunk)
        self._llm_worker.finished.connect(self._on_ai_finished)
        self._llm_worker.error.connect(self._on_ai_error)
        self._llm_worker.start()

    def _on_ai_chunk(self, chunk: str):
        """接收 AI 流式回复的片段"""
        self.chat_panel.append_ai_text(chunk)

    def _on_ai_finished(self):
        """AI 回复完成"""
        # 收集完整回复存入历史
        ai_text = ""
        if self.chat_panel._current_ai_bubble:
            layout = self.chat_panel._current_ai_bubble.layout()
            for i in range(layout.count()):
                w = layout.itemAt(i).widget()
                if isinstance(w, QLabel) and w.styleSheet() == "":
                    ai_text = w.text()
                    break

        self._context_manager.add_to_history("assistant", ai_text)
        self.chat_panel.finish_ai_response()
        self.status_bar.showMessage("就绪")
        self._llm_worker = None

    def _on_ai_error(self, error_msg: str):
        """AI 调用出错"""
        self.chat_panel.append_ai_text(f"\n\n❌ 错误：{error_msg}")
        self.chat_panel.finish_ai_response()
        self.status_bar.showMessage(f"错误：{error_msg}")
        self._llm_worker = None

    def _on_clear_chat(self):
        """清空对话历史"""
        self._context_manager.clear_history()
        self.chat_panel.clear_messages()
        self.status_bar.showMessage("对话已清空")

    def _on_open_settings(self):
        """打开设置对话框"""
        dialog = SettingsDialog(self)
        if dialog.exec():
            self._config = load_config()
            self._try_init_llm_client()
            self.status_bar.showMessage("API 配置已更新")

    def _on_about(self):
        QMessageBox.about(
            self, "关于 PDFasker",
            "<h3>PDFasker</h3>"
            "<p>AI 论文解读助手 v1.0</p>"
            "<p>基于大语言模型，帮助你快速理解和分析科研论文。</p>"
            "<hr>"
            "<p>支持 DeepSeek、MiniMax 及所有 OpenAI 兼容接口。</p>"
        )

    def _try_init_llm_client(self):
        """尝试初始化 LLM 客户端"""
        api_key = self._config.get("api_key", "")
        base_url = self._config.get("base_url", "")
        model = self._config.get("model", "")

        if api_key and base_url and model:
            try:
                self._llm_client = LLMClient(
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                )
                self._status_model_label.setText(
                    f"模型: {model} | API: {self._config.get('provider', '')}"
                )
                self._status_model_label.setStyleSheet("color: #a6e3a1; padding: 2px 8px;")
            except Exception as e:
                self._llm_client = None
                self._status_model_label.setText(f"API 初始化失败: {e}")
                self._status_model_label.setStyleSheet("color: #f38ba8; padding: 2px 8px;")
        else:
            self._status_model_label.setText("未配置 API — 请前往设置")
            self._status_model_label.setStyleSheet("color: #f9e2af; padding: 2px 8px;")
