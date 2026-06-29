"""
PDFasker 主应用窗口
"""

from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QMessageBox, QMenuBar, QMenu,
    QStatusBar, QLabel, QTabWidget,
)
from PySide6.QtCore import Qt, QThread, Signal as QtSignal
from PySide6.QtGui import QAction

from .ui.styles import STYLESHEET
from .ui.pdf_list_panel import PDFListPanel
from .ui.pdf_viewer import PDFViewerPanel
from .ui.chat_panel import ChatPanel
from .ui.settings_dialog import SettingsDialog
from .ui.review_panel import ReviewPanel
from .core.llm_client import LLMClient
from .core.context_manager import ContextManager
from .core.zotero_parser import ZoteroLibrary
from .core.review_checker import ReviewChecker
from .utils.config import (
    load_config, add_pdf_to_library,
    load_chat_history, save_chat_history, delete_chat_history,
)


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
            for chunk in self._client.chat_stream(self._messages):
                self.chunk_received.emit(chunk)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """PDFasker 主窗口 —— 论文阅读 + 综述写作"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDFasker — AI 论文解读助手")
        self.resize(1280, 800)
        self.setMinimumSize(900, 600)

        self._config = load_config()
        self._llm_chat: LLMClient | None = None
        self._llm_trans: LLMClient | None = None
        self._llm_image: LLMClient | None = None
        self._llm_review: LLMClient | None = None
        self._context_manager = ContextManager(
            max_tokens=self._config.get("max_tokens", 1_000_000)
        )
        self._llm_worker: LLMWorker | None = None
        self._current_pdf_path: str = ""

        # 综述相关
        self._zotero: ZoteroLibrary | None = None
        self._review_checker: ReviewChecker | None = None

        self._setup_ui()
        self._apply_styles()
        self._init_all_clients()
        self._init_review()

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

        # 主布局：使用 QTabWidget 切换「论文阅读」和「综述写作」
        self._main_tabs = QTabWidget()
        self._main_tabs.setStyleSheet(
            "QTabWidget::pane { border: none; }"
            "QTabBar::tab { padding: 8px 28px; font-size: 14px; font-weight: bold; "
            "background: #1a1b26; color: #9599b5; border: none; "
            "border-bottom: 2px solid transparent; }"
            "QTabBar::tab:selected { color: #7aa2f7; border-bottom: 2px solid #7aa2f7; }"
            "QTabBar::tab:hover { color: #cfd2e3; }"
        )

        # === Tab 0: 论文阅读（原有三栏布局）===
        outer_splitter = QSplitter(Qt.Orientation.Horizontal)
        outer_splitter.setHandleWidth(3)
        outer_splitter.setOpaqueResize(False)  # 拖拽时只显示指示线，松手才渲染，减少卡顿

        # 左：PDF 论文库
        self.pdf_list = PDFListPanel()
        self.pdf_list.pdf_selected.connect(self._on_library_pdf_selected)

        # 中：PDF 阅读器 + 右：聊天面板
        inner_splitter = QSplitter(Qt.Orientation.Horizontal)
        inner_splitter.setHandleWidth(3)
        inner_splitter.setOpaqueResize(False)

        self.pdf_viewer = PDFViewerPanel()
        self.pdf_viewer.setMinimumWidth(300)
        self.pdf_viewer.pdf_loaded.connect(self._on_pdf_loaded)
        self.pdf_viewer.pdf_path_changed.connect(self._on_pdf_path_changed)
        self.pdf_viewer.follow_up_question.connect(self._on_follow_up_from_reader)

        self.chat_panel = ChatPanel()
        self.chat_panel.setMinimumWidth(250)
        self.chat_panel.send_message.connect(self._on_user_message)
        self.chat_panel.clear_requested.connect(self._on_clear_chat)

        inner_splitter.addWidget(self.pdf_viewer)
        inner_splitter.addWidget(self.chat_panel)
        inner_splitter.setSizes([550, 450])
        inner_splitter.setStretchFactor(0, 2)  # 阅读器优先拉伸
        inner_splitter.setStretchFactor(1, 1)

        outer_splitter.addWidget(self.pdf_list)
        outer_splitter.addWidget(inner_splitter)
        outer_splitter.setSizes([200, 1000])
        outer_splitter.setStretchFactor(0, 0)  # 论文库不随窗口拉伸
        outer_splitter.setStretchFactor(1, 1)

        self._main_tabs.addTab(outer_splitter, "📖 论文阅读")

        # === Tab 1: 综述写作 ===
        self._review_panel = ReviewPanel()
        self._main_tabs.addTab(self._review_panel, "📝 综述写作")

        self.setCentralWidget(self._main_tabs)

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
        """PDF 加载完成：初始化上下文 + 加载历史对话"""
        # 保存旧文档的对话
        if self._current_pdf_path:
            self._save_current_chat()

        self._current_pdf_path = self.pdf_viewer.get_current_path()
        self._context_manager.load_pdf_text(text)

        # 加载该文档的历史对话
        history = load_chat_history(self._current_pdf_path)
        self._context_manager._chat_history = history.copy()
        # 刷新聊天面板
        self.chat_panel.clear_messages()
        for msg in history:
            if msg["role"] == "user":
                self.chat_panel.add_user_message(msg["content"])
            elif msg["role"] == "assistant":
                self.chat_panel._insert_bubble_from_history("assistant", msg["content"])

        token_est = self._context_manager.estimate_tokens(text)
        self.status_bar.showMessage(
            f"PDF 已加载 | 约 {token_est:,} tokens | "
            f"历史 {len(history)} 条对话" + (" (可享缓存优惠)" if history else "")
        )
        self.chat_panel.set_input_enabled(True)

    def _save_current_chat(self):
        """保存当前文档的对话历史"""
        if self._current_pdf_path and self._context_manager._chat_history:
            save_chat_history(self._current_pdf_path, self._context_manager._chat_history)

    def _on_pdf_path_changed(self, path: str):
        """PDF 路径变更时更新标题"""
        import os
        fname = os.path.basename(path) if path else ""
        self.setWindowTitle(f"PDFasker — {fname}" if fname else "PDFasker — AI 论文解读助手")

    def _on_library_pdf_selected(self, path: str):
        """从论文库中选择 PDF —— 先保存旧对话再加载新文档"""
        if path and path != self.pdf_viewer.get_current_path():
            self._save_current_chat()
            self.pdf_viewer.load_pdf(path)

    def _on_follow_up_from_reader(self, context: str):
        """读者在翻译/图析后点击追问 → 直接发送到聊天"""
        if not self._llm_chat:
            QMessageBox.warning(self, "未配置", "请先配置聊天 API")
            return
        self.chat_panel.set_input_enabled(True)
        # 作为用户消息发送
        self.chat_panel.add_user_message(f"[追问] {context[:100]}...")
        self._context_manager.add_to_history("user", context)
        messages = self._context_manager.build_messages(context)
        self.chat_panel.start_ai_response()
        self._llm_worker = LLMWorker(self._llm_chat, messages)
        self._llm_worker.chunk_received.connect(self._on_ai_chunk)
        self._llm_worker.finished.connect(self._on_ai_finished)
        self._llm_worker.error.connect(self._on_ai_error)
        self._llm_worker.start()

    def _on_user_message(self, text: str):
        """用户发送消息"""
        if not self._llm_chat:
            QMessageBox.warning(
                self, "未配置 API",
                "请先配置聊天 API。\n菜单 → 设置 → API 配置 → 聊天标签页"
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
        self._llm_worker = LLMWorker(self._llm_chat, messages)
        self._llm_worker.chunk_received.connect(self._on_ai_chunk)
        self._llm_worker.finished.connect(self._on_ai_finished)
        self._llm_worker.error.connect(self._on_ai_error)
        self._llm_worker.start()

    def _on_ai_chunk(self, chunk: str):
        """接收 AI 流式回复的片段"""
        self.chat_panel.append_ai_text(chunk)

    def _on_ai_finished(self):
        """AI 回复完成 —— 收集全文存入历史并保存"""
        ai_text = ""
        if self.chat_panel._current_ai_bubble:
            ai_text = self.chat_panel._current_ai_bubble.get_content()

        self._context_manager.add_to_history("assistant", ai_text)
        self.chat_panel.finish_ai_response()
        # 实时保存对话历史
        if self._current_pdf_path:
            save_chat_history(self._current_pdf_path, self._context_manager._chat_history)
        self.status_bar.showMessage("就绪")
        self._llm_worker = None

    def _on_ai_error(self, error_msg: str):
        """AI 调用出错"""
        self.chat_panel.append_ai_text(f"\n\n❌ 错误：{error_msg}")
        self.chat_panel.finish_ai_response()
        self.status_bar.showMessage(f"错误：{error_msg}")
        self._llm_worker = None

    def _on_clear_chat(self):
        """清空对话历史（内存 + 磁盘）"""
        self._context_manager.clear_history()
        self.chat_panel.clear_messages()
        if self._current_pdf_path:
            delete_chat_history(self._current_pdf_path)
        self.status_bar.showMessage("对话已清空")

    def _on_open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            self._config = load_config()
            self._init_all_clients()
            self.status_bar.showMessage("API 配置已更新")

    def _on_about(self):
        QMessageBox.about(
            self, "关于 PDFasker",
            "<h3>PDFasker</h3>"
            "<p>AI 论文解读助手 v3.0</p>"
            "<p>支持 DeepSeek V4、MiniMax 及所有 OpenAI 兼容接口。</p>"
            "<p>三套 API 独立配置：聊天 / 翻译 / 图析</p>"
            "<p>🆕 综述写作辅助：Zotero 文献库集成 + AI 对照原文优化综述</p>"
        )

    def closeEvent(self, event):
        """关闭窗口时保存对话"""
        self._save_current_chat()
        super().closeEvent(event)

    def _init_all_clients(self):
        """初始化三套 LLM 客户端"""
        from .utils.config import get_api_config

        def _make_client(key: str) -> LLMClient | None:
            cfg = get_api_config(self._config, key)
            if cfg.get("api_key") and cfg.get("base_url") and cfg.get("model"):
                try:
                    return LLMClient(cfg["api_key"], cfg["base_url"], cfg["model"])
                except Exception:
                    return None
            return None

        self._llm_chat = _make_client("chat_api")
        self._llm_trans = _make_client("translation_api")
        self._llm_image = _make_client("image_api")
        self._llm_review = _make_client("review_api")

        # 注入到子面板
        self.pdf_viewer.set_translation_client(self._llm_trans)
        self.pdf_viewer.set_image_client(self._llm_image)

        # 更新综述检查器
        self._init_review()

        # 状态栏
        parts = []
        if self._llm_chat: parts.append(f"聊天:{self._llm_chat.model}")
        if self._llm_trans: parts.append(f"翻译:{self._llm_trans.model}")
        if self._llm_image: parts.append(f"图析:{self._llm_image.model}")
        if self._llm_review: parts.append(f"综述:{self._llm_review.model}")
        if parts:
            self._status_model_label.setText(" | ".join(parts))
            self._status_model_label.setStyleSheet("color: #9ece6a; padding: 2px 8px;")
        else:
            self._status_model_label.setText("未配置 API — 请前往设置")
            self._status_model_label.setStyleSheet("color: #e0af68; padding: 2px 8px;")

    def _init_review(self):
        """初始化综述写作相关的 Zotero 库和检查器"""
        # Zotero 文献库
        zotero_path = self._config.get("zotero_data_dir", "")
        self._zotero = ZoteroLibrary(zotero_path)

        # 综述检查器 —— 优先用独立的综述 API，fallback 到聊天 API
        review_client = self._llm_review or self._llm_chat
        if review_client:
            self._review_checker = ReviewChecker(review_client, self._zotero)
        else:
            self._review_checker = None

        # 注入到综述面板
        self._review_panel.set_zotero_library(self._zotero)
        self._review_panel.set_checker(self._review_checker)
        # 也传入聊天客户端，用于核查后追问
        self._review_panel.set_chat_client(self._llm_chat)

        # 如果配置了 Zotero 路径，触发加载
        if zotero_path and self._zotero.is_available:
            self._review_panel.set_zotero_path(zotero_path)
