"""PDFasker 主窗口 v2 —— 两阶段管线：Stage1自动解析 + Stage2用户触发整合。

两套 API：文献阅读（逐页解析+跨页整合+翻译+问答）、综述写作（引文核查）。
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread, Signal as QtSignal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QLabel, QMainWindow, QMessageBox,
    QSplitter, QStatusBar, QTabWidget,
)

from .core.context_manager import ContextManager
from .core.llm_client import LLMClient
from .core.review_checker import ReviewChecker
from .core.zotero_parser import ZoteroLibrary
from .ui.chat_panel import ChatPanel
from .ui.pdf_list_panel import PDFListPanel
from .ui.pdf_viewer import PDFViewerPanel
from .ui.review_panel import ReviewPanel
from .ui.settings_dialog import SettingsDialog
from .ui.styles import STYLESHEET
from .utils.config import (
    delete_chat_history, get_reading_api, get_review_api,
    load_chat_history, load_config, save_chat_history,
)


class LLMWorker(QThread):
    """后台 LLM 调用线程，避免阻塞 UI。"""
    chunk_received = QtSignal(str)
    finished = QtSignal()
    error = QtSignal(str)

    def __init__(self, client: LLMClient, messages: list[dict]) -> None:
        super().__init__()
        self._client = client
        self._messages = messages

    def run(self) -> None:
        try:
            for chunk in self._client.chat_stream(self._messages):
                self.chunk_received.emit(chunk)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """PDFasker 主窗口 v2 —— 管理论文阅读与综述写作两个 Tab。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDFasker — AI 论文解读助手")
        self.resize(1280, 800)
        self.setMinimumSize(900, 600)

        self._config = load_config()
        self._llm_reading: LLMClient | None = None
        self._llm_review: LLMClient | None = None
        self._context_manager = ContextManager(
            max_tokens=self._config.get("max_tokens", 1_000_000)
        )
        self._llm_worker: LLMWorker | None = None
        self._current_pdf_path: str = ""

        # PDF 处理器池：pdf_path → PDFProcessor
        self._processors: dict[str, object] = {}

        # 综述相关
        self._zotero: ZoteroLibrary | None = None
        self._review_checker: ReviewChecker | None = None

        self._setup_ui()
        self._apply_styles()
        self._init_all_clients()
        self._init_review()

    def _setup_ui(self):
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

        self._main_tabs = QTabWidget()

        # Tab 0: 论文阅读
        outer_splitter = QSplitter(Qt.Orientation.Horizontal)
        outer_splitter.setHandleWidth(3)
        outer_splitter.setOpaqueResize(False)

        self.pdf_list = PDFListPanel()
        self.pdf_list.pdf_selected.connect(self._on_library_pdf_selected)
        self.pdf_list.pdf_removed.connect(self._on_library_pdf_removed)
        self.pdf_list.pdf_reload_requested.connect(self._on_library_pdf_reload)
        self.pdf_list.pdf_imported.connect(self._on_pdf_imported)

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
        inner_splitter.setStretchFactor(0, 2)
        inner_splitter.setStretchFactor(1, 1)

        outer_splitter.addWidget(self.pdf_list)
        outer_splitter.addWidget(inner_splitter)
        outer_splitter.setSizes([200, 1000])
        outer_splitter.setStretchFactor(0, 0)
        outer_splitter.setStretchFactor(1, 1)

        self._main_tabs.addTab(outer_splitter, "📖 论文阅读")

        # Tab 1: 综述写作
        self._review_panel = ReviewPanel()
        self._main_tabs.addTab(self._review_panel, "📝 综述写作")

        self.setCentralWidget(self._main_tabs)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._status_model_label = QLabel("未配置 API")
        self._status_model_label.setStyleSheet("color: #a6adc8; padding: 2px 8px;")
        self.status_bar.addPermanentWidget(self._status_model_label)

    def _apply_styles(self) -> None:
        self.setStyleSheet(STYLESHEET)

    # ========== 事件处理 ==========

    def _on_open_pdf(self) -> None:
        self.pdf_viewer._open_pdf()

    def _on_pdf_loaded(self, text: str):
        """PDF 加载完成（Stage 2 整合后）—— 更新上下文和聊天。"""
        if self._current_pdf_path:
            self._save_current_chat()

        self._current_pdf_path = self.pdf_viewer.get_current_path()
        self._context_manager.load_pdf_text(text)

        history = load_chat_history(self._current_pdf_path)
        self._context_manager.load_history(history)
        self.chat_panel.clear_messages()
        for msg in history:
            if msg["role"] == "user":
                self.chat_panel.add_user_message(msg["content"])
            elif msg["role"] == "assistant":
                self.chat_panel._insert_bubble_from_history("assistant", msg["content"])

        token_est = self._context_manager.estimate_tokens(text)
        self.status_bar.showMessage(
            f"PDF 已加载 | 约 {token_est:,} tokens | "
            f"历史 {len(history)} 条对话"
        )
        self.chat_panel.set_input_enabled(True)

    def _save_current_chat(self):
        if self._current_pdf_path:
            save_chat_history(self._current_pdf_path, self._context_manager.get_history())

    def _on_pdf_path_changed(self, path: str):
        fname = os.path.basename(path) if path else ""
        self.setWindowTitle(f"PDFasker — {fname}" if fname else "PDFasker — AI 论文解读助手")

    def _on_library_pdf_removed(self, path: str):
        """PDF 从库中移除 → 清理处理器和视图。"""
        self.pdf_viewer._reset_view()
        self.setWindowTitle("PDFasker — AI 论文解读助手")
        # 清理对应的处理器
        if path in self._processors:
            proc = self._processors.pop(path)
            if hasattr(proc, 'cancel'):
                proc.cancel()

    def _on_pdf_imported(self, path: str):
        """PDF 导入后立即在后台开始 Stage 1 逐页解析。"""
        if not path:
            return

        self._save_current_chat()
        self._current_pdf_path = ""
        self.pdf_viewer._reset_view()

        # 注入 LLM 客户端
        self.pdf_viewer.set_llm_client(self._llm_reading)
        self.pdf_viewer.load_pdf(path)

        # 连接进度信号到论文列表面板
        if hasattr(self.pdf_viewer, '_processor') and self.pdf_viewer._processor:
            proc = self.pdf_viewer._processor
            self._processors[path] = proc
            proc.stage1_progress.connect(self._on_processor_progress)

    def _on_library_pdf_selected(self, path: str):
        """用户点击论文列表中的一篇 PDF。"""
        if not path:
            return

        # 如果已有缓存且视图为空，则加载
        if path != self.pdf_viewer.get_current_path():
            self._save_current_chat()
            self.pdf_viewer.set_llm_client(self._llm_reading)
            self.pdf_viewer.load_pdf(path)

            # 连接信号
            if hasattr(self.pdf_viewer, '_processor') and self.pdf_viewer._processor:
                proc = self.pdf_viewer._processor
                self._processors[path] = proc
                proc.stage1_progress.connect(self._on_processor_progress)

    def _on_library_pdf_reload(self, path: str):
        """清除所有缓存后重新加载 PDF。"""
        if path:
            self._save_current_chat()
            self._current_pdf_path = ""

            # 清除逐页缓存
            from .utils.config import delete_page_cache
            delete_page_cache(path)

            self.pdf_viewer._reset_view()
            self.pdf_viewer.set_llm_client(self._llm_reading)
            self.pdf_viewer.load_pdf(path)

    def _on_processor_progress(self, pdf_path: str, current: int, total: int):
        """转发 Stage 1 进度到论文列表面板。"""
        self.pdf_list.update_pdf_progress(pdf_path, current, total)

    def _on_follow_up_from_reader(self, context: str):
        if not self._llm_reading:
            QMessageBox.warning(self, "未配置", "请先配置文献阅读 API")
            return
        self.chat_panel.set_input_enabled(True)
        self.chat_panel.add_user_message(f"[追问] {context[:100]}...")
        self._context_manager.add_to_history("user", context)
        messages = self._context_manager.build_messages(context)
        self.chat_panel.start_ai_response()
        self._llm_worker = LLMWorker(self._llm_reading, messages)
        self._llm_worker.chunk_received.connect(self._on_ai_chunk)
        self._llm_worker.finished.connect(self._on_ai_finished)
        self._llm_worker.error.connect(self._on_ai_error)
        self._llm_worker.start()

    def _on_user_message(self, text: str):
        if not self._llm_reading:
            QMessageBox.warning(self, "未配置 API", "请先配置文献阅读 API。\n菜单 → 设置 → API 配置")
            self.chat_panel.set_input_enabled(True)
            return
        if not self._context_manager.has_pdf:
            QMessageBox.warning(self, "未加载 PDF", "请先打开一个 PDF 文件。")
            self.chat_panel.set_input_enabled(True)
            return

        self.chat_panel.add_user_message(text)
        self._context_manager.add_to_history("user", text)
        messages = self._context_manager.build_messages(text)
        self.chat_panel.start_ai_response()
        self.status_bar.showMessage("AI 正在思考...")

        self._llm_worker = LLMWorker(self._llm_reading, messages)
        self._llm_worker.chunk_received.connect(self._on_ai_chunk)
        self._llm_worker.finished.connect(self._on_ai_finished)
        self._llm_worker.error.connect(self._on_ai_error)
        self._llm_worker.start()

    def _on_ai_chunk(self, chunk: str):
        self.chat_panel.append_ai_text(chunk)

    def _on_ai_finished(self):
        ai_text = ""
        if self.chat_panel._current_ai_bubble:
            ai_text = self.chat_panel._current_ai_bubble.get_content()
        self._context_manager.add_to_history("assistant", ai_text)
        self.chat_panel.finish_ai_response()
        self.chat_panel.set_token_count(self._context_manager.estimate_tokens(
            self._context_manager.get_full_context_for_estimation()
        ))
        if self._current_pdf_path:
            save_chat_history(self._current_pdf_path, self._context_manager.get_history())
        self.status_bar.showMessage("就绪")
        self._llm_worker = None

    def _on_ai_error(self, error_msg: str):
        self.chat_panel.append_ai_text(f"\n\n❌ 错误：{error_msg}")
        self.chat_panel.finish_ai_response()
        self.status_bar.showMessage(f"错误：{error_msg}")
        self._llm_worker = None

    def _on_clear_chat(self):
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

    def _on_about(self) -> None:
        QMessageBox.about(
            self, "关于 PDFasker",
            "<h3>PDFasker</h3>"
            "<p>AI 论文解读助手 v2.0</p>"
            "<p>支持 DeepSeek V4、Mimo 及所有 OpenAI 兼容接口。</p>"
            "<p>两套 API：文献阅读（逐页解析+跨页整合+翻译+问答）、综述写作</p>"
            "<p>🆕 视觉 LLM 自动识别论文结构 · 智能图片提取 · 两阶段管线</p>"
        )

    def closeEvent(self, event) -> None:
        """窗口关闭时保存状态并清理后台线程。"""
        self._save_current_chat()
        self._review_panel.shutdown()

        # 取消所有进行中的 PDF 处理器
        for proc in self._processors.values():
            if hasattr(proc, 'cancel'):
                proc.cancel()

        if self._llm_worker and self._llm_worker.isRunning():
            self._llm_worker.quit()
            if not self._llm_worker.wait(3000):
                self._llm_worker.terminate()
                self._llm_worker.wait()
        super().closeEvent(event)

    # ========== API 客户端初始化 ==========

    def _init_all_clients(self) -> None:
        """根据配置初始化两套 LLM 客户端并注入到各子面板。"""

        def _make_client(cfg: dict) -> LLMClient | None:
            if cfg.get("api_key") and cfg.get("base_url") and cfg.get("model"):
                return LLMClient(cfg["api_key"], cfg["base_url"], cfg["model"])
            return None

        reading_cfg = get_reading_api(self._config)
        review_cfg = get_review_api(self._config)

        self._llm_reading = _make_client(reading_cfg)
        self._llm_review = _make_client(review_cfg)

        # 注入到子面板
        self.pdf_viewer.set_llm_client(self._llm_reading)
        self.chat_panel.set_input_enabled(self._llm_reading is not None)

        if self._llm_reading:
            model_name = reading_cfg.get("model", "unknown")
            self._status_model_label.setText(f"📖 {model_name}")
            self._status_model_label.setStyleSheet("color: #9ece6a; padding: 2px 8px;")
        else:
            self._status_model_label.setText("未配置 API")
            self._status_model_label.setStyleSheet("color: #a6adc8; padding: 2px 8px;")

    def _init_review(self) -> None:
        """初始化综述写作模块。"""
        zotero_dir = self._config.get("zotero_data_dir", "")
        self._zotero = ZoteroLibrary(zotero_dir)
        if self._llm_review:
            self._review_checker = ReviewChecker(self._llm_review, self._zotero)
            self._review_panel.set_checker(self._review_checker)
        self._review_panel.set_zotero_library(self._zotero)
