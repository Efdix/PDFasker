"""
综述写作面板 —— 编写综述 + 引文核查 + 文献库搜索
"""

import os
import re
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QScrollArea, QLabel, QFrame, QSplitter, QProgressBar,
    QMessageBox, QFileDialog,
    QSizePolicy, QGroupBox,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QSize
from PySide6.QtGui import QFont, QTextCursor

from ..core.review_checker import ReviewChecker, CitationClaim, ReviewCheckResult
from ..core.zotero_parser import ZoteroLibrary, ZoteroItem
from ..utils.layout import calc_layout_height


# ========== 后台核查线程 ==========

class ReviewCheckWorker(QThread):
    """后台执行综述引文核查，不阻塞 UI"""
    progress_signal = Signal(str, int, int)  # message, current, total
    finished_signal = Signal(object)          # ReviewCheckResult
    error_signal = Signal(str)

    def __init__(self, checker: ReviewChecker, review_text: str):
        super().__init__()
        self._checker = checker
        self._text = review_text

    def run(self):
        try:
            result = self._checker.check_review(
                self._text,
                progress_callback=lambda msg, cur, tot: self.progress_signal.emit(msg, cur, tot)
            )
            self.finished_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))


# ========== 追问聊天线程 ==========

class FollowChatWorker(QThread):
    """后台处理追问对话"""
    reply_ready = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, client, messages: list[dict]):
        super().__init__()
        self._client = client
        self._messages = messages

    def run(self):
        try:
            reply = self._client.chat_sync(self._messages)
            self.reply_ready.emit(reply)
        except Exception as e:
            self.error_occurred.emit(str(e))


# ========== 引文声明的结果卡片 ==========

class ClaimResultCard(QFrame):
    """单条引文验证结果卡片"""

    def __init__(self, claim: CitationClaim, parent=None):
        super().__init__(parent)
        self._claim = claim
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

    def _setup_ui(self):
        self.setStyleSheet(
            "ClaimResultCard { background-color: #1a1b26; border: 1px solid #2a2c3d; "
            "border-radius: 10px; margin: 4px 0px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        # 状态行
        verdict_row = QHBoxLayout()
        status_config = {
            "引用恰当": ("✅", "#9ece6a"),
            "建议补充": ("📝", "#7aa2f7"),
            "表述可优化": ("💡", "#e0af68"),
            "需核实": ("⚠️", "#f7768e"),
            "文献未匹配": ("❓", "#9599b5"),
        }
        icon, color = status_config.get(self._claim.status, ("❓", "#9599b5"))

        verdict_label = QLabel(f"{icon} {self._claim.status}")
        verdict_label.setStyleSheet(f"color: {color}; font-size: 15px; font-weight: bold;")
        verdict_row.addWidget(verdict_label)

        marker = QLabel(f"引文: {self._claim.citation_marker}")
        marker.setStyleSheet("color: #7aa2f7; font-size: 12px; padding: 2px 6px;")
        verdict_row.addWidget(marker)

        verdict_row.addStretch()

        if self._claim.matched_item:
            matched = QLabel(f"📄 {self._claim.matched_item.title[:60]}...")
        else:
            matched = QLabel("📭 未匹配到文献")
        matched.setStyleSheet("color: #9599b5; font-size: 11px;")
        matched.setWordWrap(True)
        verdict_row.addWidget(matched)

        layout.addLayout(verdict_row)

        # 左右对照：综述原文 | AI 改写建议
        if self._claim.rewrite_suggestion and "无需大幅修改" not in self._claim.rewrite_suggestion:
            compare = QHBoxLayout()
            compare.setSpacing(8)

            # 左：原文
            left_frame = QFrame()
            left_frame.setStyleSheet("background-color: #1e2030; border: 1px solid #3b3d54; border-radius: 8px;")
            ll = QVBoxLayout(left_frame)
            ll.setContentsMargins(10, 8, 10, 8)
            lh = QLabel("📝 你的原文")
            lh.setStyleSheet("color: #8a8ea6; font-size: 11px; font-weight: bold;")
            ll.addWidget(lh)
            lt = QLabel(self._claim.claim_text)
            lt.setWordWrap(True)
            lt.setStyleSheet("color: #cfd2e3; font-size: 12px; line-height: 1.5;")
            lt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            ll.addWidget(lt)
            compare.addWidget(left_frame, 1)

            # 右：AI 建议
            right_frame = QFrame()
            right_frame.setStyleSheet("background-color: #1e2030; border: 1px solid #7aa2f7; border-radius: 8px;")
            rl = QVBoxLayout(right_frame)
            rl.setContentsMargins(10, 8, 10, 8)
            rh_row = QHBoxLayout()
            rh = QLabel("✨ 建议改写")
            rh.setStyleSheet("color: #7aa2f7; font-size: 11px; font-weight: bold;")
            rh_row.addWidget(rh)
            rh_row.addStretch()
            copy_btn = QPushButton("📋 复制")
            copy_btn.setFixedWidth(64)
            copy_btn.setStyleSheet(
                "QPushButton { background-color: #2a2c3d; color: #7aa2f7; border: 1px solid #3b3d54; "
                "border-radius: 4px; padding: 2px 6px; font-size: 11px; }"
                "QPushButton:hover { background-color: #3b3d54; }"
            )
            copy_text = self._claim.rewrite_suggestion
            copy_btn.clicked.connect(lambda checked=False, t=copy_text: self._copy_to_clipboard(t))
            rh_row.addWidget(copy_btn)
            rl.addLayout(rh_row)
            rt = QLabel(self._claim.rewrite_suggestion)
            rt.setWordWrap(True)
            rt.setStyleSheet("color: #e2e5f2; font-size: 12px; line-height: 1.6;")
            rt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            rl.addWidget(rt)
            compare.addWidget(right_frame, 1)

            layout.addLayout(compare)
        else:
            # 无改写建议，仅显示原文
            claim_section = QLabel(f"📝 你的原文：{self._claim.claim_text}")
            claim_section.setWordWrap(True)
            claim_section.setStyleSheet("color: #cfd2e3; font-size: 13px; line-height: 1.5; padding: 4px 0;")
            layout.addWidget(claim_section)

        # AI 反馈（诊断）
        if self._claim.ai_feedback:
            feedback = QLabel(self._claim.ai_feedback)
            feedback.setWordWrap(True)
            feedback.setStyleSheet("color: #a9b1d6; font-size: 12px; line-height: 1.5; padding: 4px 0;")
            feedback.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(feedback)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #2a2c3d; max-height: 1px;")
        layout.addWidget(sep)

    def _copy_to_clipboard(self, text: str):
        """复制文本到剪贴板"""
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        sender = self.sender()
        if sender:
            orig = sender.text()
            sender.setText("✅ 已复制")
            QTimer.singleShot(1500, lambda: sender.setText(orig))


# ========== 综述写作面板 ==========

class ReviewPanel(QWidget):
    """综述写作与引文核查面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._zotero: ZoteroLibrary | None = None
        self._checker: ReviewChecker | None = None
        self._check_worker: ReviewCheckWorker | None = None
        self._last_result: ReviewCheckResult | None = None
        self._llm_chat = None     # 聊天客户端（用于核查后追问）
        self._follow_chat_history: list[dict] = []  # 追问对话历史
        self._scroll_syncing = False  # 左右同步滚动锁
        self._setup_ui()

    def set_zotero_library(self, zotero: ZoteroLibrary):
        self._zotero = zotero

    def set_checker(self, checker: ReviewChecker):
        self._checker = checker

    def set_chat_client(self, client):
        """设置聊天客户端（用于核查后的追问对话）"""
        self._llm_chat = client

    def shutdown(self):
        """关闭前清理所有后台线程，避免 QThread 销毁警告"""
        workers = [
            getattr(self, '_check_worker', None),
            getattr(self, '_fw', None),
        ]
        for w in workers:
            if w is not None and w.isRunning():
                w.quit()
                if not w.wait(3000):
                    w.terminate()
                    w.wait()

    def set_zotero_path(self, path: str):
        """设置/更换 Zotero 数据目录"""
        self._zotero = ZoteroLibrary(path)
        if self._checker:
            self._checker._zotero = self._zotero

        if self._zotero.is_available and self._zotero._sqlite_path:
            # 找到了有效的 sqlite
            count = self._zotero.load()
            sqlite_short = self._zotero._sqlite_path
            if len(sqlite_short) > 60:
                sqlite_short = "..." + sqlite_short[-57:]
            self.zotero_path_label.setText(f"📂 {self._zotero.data_dir}")
            self.zotero_path_label.setStyleSheet("color: #9ece6a; font-size: 11px;")
            self.zotero_status.setText(f"✅ 已加载 {count} 条文献 | SQLite: {sqlite_short}")
            self.zotero_status.setStyleSheet("color: #9ece6a; font-size: 11px;")
            self.zotero_btn.setText("📂 更换 Zotero 目录")
            self.zotero_hint.setVisible(False)
        else:
            self.zotero_path_label.setText("未检测到有效 Zotero 库")
            self.zotero_path_label.setStyleSheet("color: #e0af68; font-size: 11px;")
            self.zotero_status.setText(f"所选目录未找到 zotero.sqlite，请重试")
            self.zotero_status.setStyleSheet("color: #f7768e; font-size: 11px;")
            self.zotero_hint.setVisible(True)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---- 标题栏 ----
        header = QHBoxLayout()
        header.setContentsMargins(12, 8, 12, 8)
        title = QLabel("📝 综述写作辅助")
        title.setObjectName("titleLabel")
        header.addWidget(title)
        header.addStretch()

        # Zotero 设置按钮
        self.zotero_btn = QPushButton("📂 设置 Zotero 目录")
        self.zotero_btn.clicked.connect(self._on_set_zotero)
        header.addWidget(self.zotero_btn)
        main_layout.addLayout(header)

        # ---- Zotero 状态栏 ----
        zotero_bar = QHBoxLayout()
        zotero_bar.setContentsMargins(12, 2, 12, 2)
        self.zotero_path_label = QLabel("未检测到 Zotero 库")
        self.zotero_path_label.setStyleSheet("color: #9599b5; font-size: 11px;")
        zotero_bar.addWidget(self.zotero_path_label)
        zotero_bar.addStretch()
        self.zotero_status = QLabel("请设置 Zotero 数据目录以启用文献匹配")
        self.zotero_status.setStyleSheet("color: #9599b5; font-size: 11px;")
        zotero_bar.addWidget(self.zotero_status)
        main_layout.addLayout(zotero_bar)

        # Zotero 路径提示
        self.zotero_hint = QLabel(
            "💡 <b>如何找到 Zotero 数据目录？</b><br>"
            "&nbsp;&nbsp;&nbsp;打开 Zotero → 编辑 → 设置 → 高级 → 文件和文件夹 → "
            "<span style='color:#7aa2f7;'>数据目录位置</span> → 复制该路径<br>"
            "&nbsp;&nbsp;&nbsp;典型路径：<code>C:\\Users\\你的用户名\\Zotero</code> 或 "
            "<code>%APPDATA%\\Zotero\\Zotero</code>"
        )
        self.zotero_hint.setStyleSheet(
            "color: #636688; font-size: 11px; padding: 4px 12px; line-height: 1.6;"
        )
        self.zotero_hint.setWordWrap(True)
        self.zotero_hint.setVisible(True)
        main_layout.addWidget(self.zotero_hint)

        # ---- 分隔线 ----
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #2a2c3d; max-height: 1px;")
        main_layout.addWidget(sep)

        # ---- 编辑区（紧凑） ----
        edit_section = QVBoxLayout()
        edit_section.setContentsMargins(12, 6, 12, 6)
        edit_section.setSpacing(4)

        edit_toolbar = QHBoxLayout()
        edit_toolbar.setSpacing(6)
        write_hint = QLabel("在此编写或粘贴综述草稿")
        write_hint.setStyleSheet("color: #9599b5; font-size: 12px;")
        edit_toolbar.addWidget(write_hint)
        edit_toolbar.addStretch()

        self.search_btn = QPushButton("🔍 搜索相关文献")
        self.search_btn.setToolTip("根据综述主题在文献库中搜索可能遗漏的文献")
        self.search_btn.clicked.connect(self._on_search_library)
        edit_toolbar.addWidget(self.search_btn)

        self.check_btn = QPushButton("✨ AI 辅助修改")
        self.check_btn.setObjectName("primaryBtn")
        self.check_btn.setToolTip("让 AI 对照真实文献，帮你优化综述内容")
        self.check_btn.clicked.connect(self._on_check_review)
        edit_toolbar.addWidget(self.check_btn)
        edit_section.addLayout(edit_toolbar)

        # 综述文本编辑器（紧凑高度）
        self.review_editor = QTextEdit()
        self.review_editor.setPlaceholderText(
            "在此编写综述草稿… 使用 [1] 或 (Author, Year) 标注引用"
        )
        self.review_editor.setStyleSheet(
            "QTextEdit { background-color: #24253a; color: #e2e5f2; border: 1px solid #3b3d54; "
            "border-radius: 8px; padding: 10px; font-size: 13px; line-height: 1.5; }"
        )
        self.review_editor.setMaximumHeight(160)
        self.review_editor.setMinimumHeight(80)
        edit_section.addWidget(self.review_editor)

        # 进度条
        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(3)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: #24253a; border: none; border-radius: 2px; }"
            "QProgressBar::chunk { background-color: #7aa2f7; border-radius: 2px; }"
        )
        progress_row.addWidget(self.progress_bar, 1)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #9599b5; font-size: 11px;")
        self.progress_label.setVisible(False)
        progress_row.addWidget(self.progress_label)
        edit_section.addLayout(progress_row)

        main_layout.addLayout(edit_section)

        # ---- 分隔线 ----
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("background-color: #2a2c3d; max-height: 1px;")
        main_layout.addWidget(sep2)

        # ===== 结果区：左右对照 =====
        result_header = QHBoxLayout()
        result_header.setContentsMargins(12, 6, 12, 6)
        result_title = QLabel("📊 修改建议")
        result_title.setObjectName("titleLabel")
        result_header.addWidget(result_title)
        result_header.addStretch()
        self.result_count = QLabel("")
        self.result_count.setStyleSheet("color: #9599b5; font-size: 12px;")
        result_header.addWidget(self.result_count)
        main_layout.addLayout(result_header)

        # 左右分割器（原文 | AI 反馈）
        self.compare_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.compare_splitter.setHandleWidth(3)

        # ---- 左：原文 ----
        left_frame = QFrame()
        left_frame.setStyleSheet("QFrame { background-color: #1a1b26; border: none; }")
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(4, 4, 2, 4)
        left_layout.setSpacing(4)
        left_header = QLabel("📝 你的原文")
        left_header.setStyleSheet("color: #8a8ea6; font-size: 12px; font-weight: bold; padding: 4px 8px;")
        left_layout.addWidget(left_header)
        self.original_view = QTextEdit()
        self.original_view.setReadOnly(True)
        self.original_view.setStyleSheet(
            "QTextEdit { background-color: #1e2030; color: #cfd2e3; border: 1px solid #3b3d54; "
            "border-radius: 8px; padding: 10px; font-size: 13px; line-height: 1.7; }"
        )
        left_layout.addWidget(self.original_view, 1)
        self.compare_splitter.addWidget(left_frame)

        # ---- 右：AI 反馈 ----
        right_frame = QFrame()
        right_frame.setStyleSheet("QFrame { background-color: #1a1b26; border: none; }")
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(2, 4, 4, 4)
        right_layout.setSpacing(4)
        right_header = QLabel("✨ AI 修改建议")
        right_header.setStyleSheet("color: #7aa2f7; font-size: 12px; font-weight: bold; padding: 4px 8px;")
        right_layout.addWidget(right_header)
        self.feedback_view = QTextEdit()
        self.feedback_view.setReadOnly(True)
        self.feedback_view.setStyleSheet(
            "QTextEdit { background-color: #1e2030; color: #e2e5f2; border: 1px solid #7aa2f7; "
            "border-radius: 8px; padding: 10px; font-size: 13px; line-height: 1.7; }"
        )
        right_layout.addWidget(self.feedback_view, 1)
        self.compare_splitter.addWidget(right_frame)

        self.compare_splitter.setSizes([400, 500])
        self.compare_splitter.setStretchFactor(0, 1)
        self.compare_splitter.setStretchFactor(1, 1)

        # 同步滚动
        self.original_view.verticalScrollBar().valueChanged.connect(
            self._sync_scroll_left_to_right
        )
        self.feedback_view.verticalScrollBar().valueChanged.connect(
            self._sync_scroll_right_to_left
        )
        self._scroll_syncing = False  # 防止递归

        main_layout.addWidget(self.compare_splitter, 1)

        # ---- 追问区 ----
        self.follow_chat_group = QGroupBox("💬 追问与修正")
        self.follow_chat_group.setVisible(False)
        self.follow_chat_group.setMaximumHeight(150)
        fcl = QVBoxLayout(self.follow_chat_group)
        fcl.setContentsMargins(8, 8, 8, 8)
        fcl.setSpacing(6)

        self.follow_chat_display = QTextEdit()
        self.follow_chat_display.setReadOnly(True)
        self.follow_chat_display.setMinimumHeight(40)
        self.follow_chat_display.setVisible(False)
        self.follow_chat_display.setStyleSheet(
            "QTextEdit { background-color: #161720; color: #cfd2e3; border: 1px solid #2a2c3d; "
            "border-radius: 6px; padding: 8px; font-size: 12px; }"
        )
        fcl.addWidget(self.follow_chat_display, 1)

        fcw = QHBoxLayout()
        fcw.setSpacing(6)
        self.follow_chat_input = QTextEdit()
        self.follow_chat_input.setPlaceholderText("与 AI 讨论修改方案... 按 Ctrl+Enter 发送")
        self.follow_chat_input.setMaximumHeight(44)
        self.follow_chat_input.setMinimumHeight(32)
        self.follow_chat_input.setStyleSheet(
            "QTextEdit { background-color: #24253a; color: #e2e5f2; border: 1px solid #3b3d54; "
            "border-radius: 6px; padding: 6px 10px; font-size: 13px; }"
        )
        self.follow_chat_input.installEventFilter(self)
        fcw.addWidget(self.follow_chat_input, 1)
        self.follow_send_btn = QPushButton("发送")
        self.follow_send_btn.setObjectName("primaryBtn")
        self.follow_send_btn.setFixedWidth(60)
        self.follow_send_btn.clicked.connect(self._on_follow_chat_send)
        fcw.addWidget(self.follow_send_btn)
        fcl.addLayout(fcw)

        main_layout.addWidget(self.follow_chat_group)

    def _sync_scroll_left_to_right(self, value: int):
        """左→右同步滚动"""
        if self._scroll_syncing:
            return
        self._scroll_syncing = True
        left_max = self.original_view.verticalScrollBar().maximum()
        right_max = self.feedback_view.verticalScrollBar().maximum()
        if left_max > 0:
            ratio = value / left_max
            self.feedback_view.verticalScrollBar().setValue(int(ratio * right_max))
        self._scroll_syncing = False

    def _sync_scroll_right_to_left(self, value: int):
        """右→左同步滚动"""
        if self._scroll_syncing:
            return
        self._scroll_syncing = True
        right_max = self.feedback_view.verticalScrollBar().maximum()
        left_max = self.original_view.verticalScrollBar().maximum()
        if right_max > 0:
            ratio = value / right_max
            self.original_view.verticalScrollBar().setValue(int(ratio * left_max))
        self._scroll_syncing = False

    # ========== 事件处理 ==========

    def eventFilter(self, obj, event):
        """Ctrl+Enter 发送追问"""
        from PySide6.QtCore import QEvent
        if obj == self.follow_chat_input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._on_follow_chat_send()
                return True
        return super().eventFilter(obj, event)

    def _on_set_zotero(self):
        """设置 Zotero 数据目录 —— 智能识别用户选择的路径"""
        # 先尝试自动检测
        auto_path = ZoteroLibrary._auto_detect()
        current = ""
        if self._zotero and self._zotero._sqlite_path:
            current = os.path.dirname(self._zotero._sqlite_path)
        elif auto_path:
            current = auto_path

        # 构建对话框提示
        dialog_title = "选择 Zotero 数据目录"
        if auto_path:
            dialog_title = f"选择 Zotero 数据目录（已自动检测到）"

        path = QFileDialog.getExistingDirectory(
            self, dialog_title,
            current or os.path.expanduser("~")
        )
        if not path:
            # 用户取消——如果有自动检测到的路径，尝试使用
            if auto_path and not (self._zotero and self._zotero._sqlite_path):
                self.set_zotero_path(auto_path)
                from ..utils.config import load_config, save_config
                cfg = load_config()
                cfg["zotero_data_dir"] = auto_path
                save_config(cfg)
                QMessageBox.information(
                    self, "自动检测成功",
                    f"已自动检测到 Zotero 库：\n{auto_path}\n\n"
                    f"加载了 {self._zotero.item_count} 条文献。"
                )
            return

        # 用户选了路径，交给 ZoteroLibrary 智能解析
        self.set_zotero_path(path)

        if self._zotero and self._zotero._sqlite_path:
            # 成功
            from ..utils.config import load_config, save_config
            cfg = load_config()
            cfg["zotero_data_dir"] = path
            save_config(cfg)

            QMessageBox.information(
                self, "设置成功",
                f"Zotero 文献库已连接！\n\n"
                f"📂 数据目录：{self._zotero.data_dir}\n"
                f"📄 文献总数：{self._zotero.item_count}\n"
                f"📎 含 PDF：{len(self._zotero.get_items_with_pdf())}"
            )
        else:
            # 失败——显示详细提示
            QMessageBox.warning(
                self, "未找到 Zotero 数据库",
                f"在所选目录及其子目录中未找到 zotero.sqlite。\n\n"
                f"请按以下步骤找到正确路径：\n"
                f"1. 打开 Zotero 软件\n"
                f"2. 点击菜单：编辑 → 设置\n"
                f"3. 选择「高级」选项卡\n"
                f"4. 点击「文件和文件夹」\n"
                f"5. 复制「数据目录位置」中的完整路径\n"
                f"6. 回到本软件粘贴或选择该路径\n\n"
                f"常见路径示例：\n"
                f"• C:\\Users\\你的用户名\\Zotero\n"
                f"• C:\\Users\\你的用户名\\AppData\\Roaming\\Zotero\\Zotero\\profiles\\xxxxx.default"
            )

    def _on_check_review(self):
        """开始引文核查"""
        review_text = self.review_editor.toPlainText().strip()
        if not review_text:
            QMessageBox.warning(self, "提示", "请先编写综述文本")
            return

        if not self._checker:
            QMessageBox.warning(self, "未配置", "请先在设置中配置聊天 API")
            return

        if not self._zotero or not self._zotero.is_available:
            QMessageBox.warning(self, "未设置文献库", "请先设置 Zotero 数据目录")
            return

        # 确保已加载
        if self._zotero.item_count == 0:
            self._zotero.load()
            self.zotero_status.setText(f"✅ 已加载 {self._zotero.item_count} 条文献")
            self.zotero_status.setStyleSheet("color: #9ece6a; font-size: 11px;")

        # 禁用按钮，显示进度
        self.check_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(True)

        # 清空旧结果
        self._clear_results()

        # 后台运行
        self._check_worker = ReviewCheckWorker(self._checker, review_text)
        self._check_worker.progress_signal.connect(self._on_progress)
        self._check_worker.finished_signal.connect(self._on_check_finished)
        self._check_worker.error_signal.connect(self._on_check_error)
        self._check_worker.start()

    def _on_progress(self, message: str, current: int, total: int):
        self.progress_label.setText(f"⏳ {message}")
        self.progress_label.setStyleSheet(
            "color: #e0af68; font-size: 13px; font-weight: bold; padding: 4px 12px;"
        )
        self.progress_bar.setValue(current)
        self.progress_bar.setVisible(True)
        if current >= 100:
            self.progress_bar.setVisible(False)
            self.progress_label.setVisible(False)

    def _on_check_finished(self, result: ReviewCheckResult):
        """核查完成，渲染结果"""
        self._last_result = result
        self._render_results(result)
        self.check_btn.setEnabled(True)
        self.search_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

    def _on_check_error(self, error_msg: str):
        QMessageBox.critical(self, "核查出错", f"引文核查过程中发生错误：\n{error_msg}")
        self.check_btn.setEnabled(True)
        self.search_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

    def _clear_results(self):
        """清除之前的结果"""
        self.original_view.clear()
        self.feedback_view.clear()
        self.follow_chat_group.setVisible(False)
        self.follow_chat_display.clear()
        self._follow_chat_history = []
        self.result_count.setText("")
        self.compare_splitter.setVisible(True)

    def _render_results(self, result: ReviewCheckResult):
        """渲染核查结果 —— 左边原文，右边 AI 反馈"""
        self._clear_results()

        review_text = self.review_editor.toPlainText().strip()
        claims = result.claims

        # ---- 左：原文 ----
        self.original_view.setPlainText(review_text)

        # ---- 右：AI 反馈（HTML 格式，重点高亮） ----
        html_parts = []

        # 统计摘要
        if claims:
            good = sum(1 for c in claims if c.status == "引用恰当")
            supplement = sum(1 for c in claims if c.status == "建议补充")
            improve = sum(1 for c in claims if c.status == "表述可优化")
            verify = sum(1 for c in claims if c.status == "需核实")
            missing = sum(1 for c in claims if c.status == "文献未匹配")

            self.result_count.setText(
                f"共 {len(claims)} 条 | ✅{good} 📝{supplement} 💡{improve} ⚠️{verify} ❓{missing}"
            )

            html_parts.append(
                f'<div style="margin-bottom:16px; padding:12px; background-color:#1e2035; '
                f'border-radius:8px; border-left:3px solid #7aa2f7;">'
                f'<b style="color:#7aa2f7; font-size:14px;">📊 引文核查结果</b><br>'
                f'<span style="color:#cfd2e3;">共 {len(claims)} 条 | '
                f'<span style="color:#9ece6a;">✅{good} 恰当</span> | '
                f'<span style="color:#7aa2f7;">📝{supplement} 建议补充</span> | '
                f'<span style="color:#e0af68;">💡{improve} 可优化</span> | '
                f'<span style="color:#f7768e;">⚠️{verify} 需核实</span> | '
                f'<span style="color:#9599b5;">❓{missing} 未匹配</span></span>'
                f'</div>'
            )

            # 逐条引文核查结果
            for claim in claims:
                icon_color = {
                    "引用恰当": ("✅", "#9ece6a"),
                    "建议补充": ("📝", "#7aa2f7"),
                    "表述可优化": ("💡", "#e0af68"),
                    "需核实": ("⚠️", "#f7768e"),
                    "文献未匹配": ("❓", "#9599b5"),
                }.get(claim.status, ("❓", "#9599b5"))

                matched_info = ""
                if claim.matched_item:
                    matched_info = f' → <i>{claim.matched_item.title[:60]}...</i>'

                # 提取诊断
                diag = ""
                diag_m = re.search(r'\*\*诊断\*\*\s*[：:]\s*(.+?)(?:\n|$)', claim.ai_feedback)
                if diag_m:
                    diag = diag_m.group(1).strip()

                fix_text = ""
                fix_m = re.search(r'\*\*需核实/修正的内容\*\*\s*[：:]\s*(.+?)(?:\n\n\*\*|\Z)', claim.ai_feedback, re.DOTALL)
                if fix_m and fix_m.group(1).strip() not in ("无", "无。", "N/A", "-"):
                    fix_text = fix_m.group(1).strip()[:300]

                wording = ""
                wording_m = re.search(r'\*\*措辞微调\*\*\s*[：:]\s*(.+?)(?:\n\n\*\*|\Z)', claim.ai_feedback, re.DOTALL)
                if wording_m and wording_m.group(1).strip() not in ("无", "无。", "N/A", "-"):
                    wording = wording_m.group(1).strip()[:200]

                html_parts.append(
                    f'<div style="margin-bottom:10px; padding:10px 12px; '
                    f'background-color:#1e2030; border-radius:8px; '
                    f'border-left:3px solid {icon_color[1]};">'
                    f'<b style="color:{icon_color[1]};">{icon_color[0]} {claim.status}</b>'
                    f'<span style="color:#7aa2f7;"> [{claim.citation_marker}]</span>'
                    f'{matched_info}<br>'
                    f'<span style="color:#cfd2e3; font-size:12px;">📝 <b>综述原文：</b>'
                    f'{claim.claim_text[:200]}...</span><br>'
                )
                if diag:
                    html_parts.append(
                        f'<span style="color:#a9b1d6; font-size:12px;">🔍 {diag}</span><br>'
                    )
                if fix_text:
                    html_parts.append(
                        f'<span style="color:#f7768e; font-size:12px;">'
                        f'<b>⚠️ 需核实：</b>{fix_text}</span><br>'
                    )
                if wording:
                    html_parts.append(
                        f'<span style="color:#e0af68; font-size:12px;">'
                        f'<b>💡 措辞建议：</b>{wording}</span><br>'
                    )
                html_parts.append('</div>')

        # 整体核查意见（核心内容，重点展示）
        if result.overall_assessment:
            # 将 markdown 风格的粗体转为 HTML
            assessment = result.overall_assessment
            assessment = assessment.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            assessment = re.sub(r'\*\*(.+?)\*\*', r'<b style="color:#7aa2f7;">\1</b>', assessment)
            assessment = assessment.replace("\n", "<br>")

            html_parts.append(
                f'<div style="margin-top:8px; padding:14px; background-color:#1e2035; '
                f'border-radius:8px; border:1px solid #7aa2f7;">'
                f'<b style="color:#7aa2f7; font-size:15px;">📋 整体核查意见</b><br><br>'
                f'<span style="color:#e2e5f2; font-size:13px; line-height:1.8;">'
                f'{assessment}</span>'
                f'</div>'
            )

        if not html_parts:
            html_parts.append(
                '<div style="color:#9ece6a; padding:40px; text-align:center; font-size:14px;">'
                '✅ 未检测到带引用的声明</div>'
            )

        self.feedback_view.setHtml("".join(html_parts))

        # 显示追问聊天区
        self.follow_chat_group.setVisible(True)

    def _on_follow_chat_send(self):
        """发送追问消息"""
        question = self.follow_chat_input.toPlainText().strip()
        if not question:
            return

        if not self._llm_chat:
            QMessageBox.warning(self, "未配置", "请先在设置中配置聊天 API")
            return

        if not self._last_result:
            return

        # 首次发送时显示聊天历史区
        if not self.follow_chat_display.isVisible():
            self.follow_chat_display.setVisible(True)

        # 构建上下文：核查结果摘要 + 对话历史
        context = self._build_follow_context()

        # 显示用户消息
        self._append_follow_message("👤 你", question)
        self.follow_chat_input.clear()
        self.follow_send_btn.setEnabled(False)
        self.follow_send_btn.setText("...")

        # 调用 LLM
        from ..core.llm_client import LLMClient  # noqa
        client = self._llm_chat

        messages = [
            {"role": "system", "content": (
                "你是学术写作助手，帮助用户修正和完善综述。以下是一次引文分析的结果，"
                "用户可能会询问相关问题或提供修正信息。请基于分析结果和专业知识回答。\n\n"
                f"{context}"
            )},
            *self._follow_chat_history[-6:],
            {"role": "user", "content": question},
        ]

        self._fw = FollowChatWorker(client, messages)
        self._fw.reply_ready.connect(lambda t: self._on_follow_reply(t))
        self._fw.error_occurred.connect(lambda e: self._on_follow_error(e))
        self._fw.start()

    def _build_follow_context(self) -> str:
        """构建追问的上下文信息"""
        if not self._last_result:
            return ""

        parts = ["## 引文分析结果摘要\n"]
        for claim in self._last_result.claims:
            matched_title = claim.matched_item.title[:80] if claim.matched_item else "未匹配"
            parts.append(
                f"- {claim.status} | {claim.citation_marker} → {matched_title}\n"
                f"  综述原文：{claim.claim_text[:200]}\n"
                f"  AI 反馈：{claim.ai_feedback[:150]}...\n"
            )

        if self._last_result.overall_assessment:
            parts.append(f"\n## 整体评价\n{self._last_result.overall_assessment[:1000]}")

        return "\n".join(parts)

    def _on_follow_reply(self, text: str):
        """接收追问回复"""
        self._append_follow_message("🤖 AI", text)
        self._follow_chat_history.append({"role": "assistant", "content": text})
        self.follow_send_btn.setEnabled(True)
        self.follow_send_btn.setText("发送")

    def _on_follow_error(self, err: str):
        self._append_follow_message("❌", f"出错：{err}")
        self.follow_send_btn.setEnabled(True)
        self.follow_send_btn.setText("发送")

    def _append_follow_message(self, role: str, content: str):
        """追加消息到追问聊天区"""
        display = self.follow_chat_display
        display.append(f"<b style='color:#7aa2f7;'>{role}</b>")
        display.append(content)
        display.append("")  # 空行
        display.verticalScrollBar().setValue(display.verticalScrollBar().maximum())

    def _on_search_library(self):
        """搜索文献库中与综述主题相关的文献"""
        if not self._zotero or not self._zotero.is_available:
            QMessageBox.warning(self, "未设置文献库", "请先设置 Zotero 数据目录")
            return

        review_text = self.review_editor.toPlainText().strip()
        if not review_text:
            QMessageBox.warning(self, "提示", "请先编写综述文本以提取搜索主题")
            return

        # 用 LLM 提取核心主题关键词
        if not self._checker:
            QMessageBox.warning(self, "未配置", "请先在设置中配置聊天 API")
            return

        try:
            prompt = (
                "从以下综述文本中提取 3-5 个核心研究主题关键词（英文），"
                "用于在文献库中搜索相关文献。直接输出关键词，用逗号分隔，不要其他内容。\n\n"
                f"综述文本：\n{review_text[:2000]}"
            )
            keywords_str = self._checker._llm.chat_sync([{"role": "user", "content": prompt}])

            # 搜索
            all_results = []
            for kw in keywords_str.split(","):
                kw = kw.strip().strip("'\"")
                if kw:
                    results = self._zotero.search(kw, max_results=5)
                    for item in results:
                        if item not in all_results:
                            all_results.append(item)

            if all_results:
                # 弹出结果对话框
                self._show_search_results(all_results)
            else:
                QMessageBox.information(self, "搜索结果", "未找到相关文献。")

        except Exception as e:
            QMessageBox.critical(self, "搜索出错", str(e))

    def _show_search_results(self, items: list[ZoteroItem]):
        """显示文献搜索结果对话框"""
        dialog = QMessageBox(self)
        dialog.setWindowTitle("文献库搜索结果")
        dialog.setIcon(QMessageBox.Icon.Information)

        lines = [f"找到 {len(items)} 篇相关文献：\n"]
        for i, item in enumerate(items[:15], 1):
            authors_short = ", ".join(item.authors[:3])
            if len(item.authors) > 3:
                authors_short += " et al."
            pdf_status = "📄" if (item.pdf_path and os.path.isfile(item.pdf_path)) else "📭"
            lines.append(
                f"{i}. {pdf_status} {item.title[:80]}\n"
                f"   {authors_short} ({item.year}) — {item.publication[:40]}"
            )

        dialog.setText("\n".join(lines))
        dialog.exec()

    def get_review_text(self) -> str:
        return self.review_editor.toPlainText()

    def set_review_text(self, text: str):
        self.review_editor.setPlainText(text)
