"""写作面板 —— 综述/论文/专利/软著 写作辅助。

布局: 顶部工具栏 | 左侧编辑器 | 右侧知识库状态 + AI辅助
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QScrollArea, QLabel, QFrame, QSplitter, QProgressBar,
    QMessageBox, QFileDialog, QComboBox, QGroupBox, QInputDialog,
    QSizePolicy, QListWidget, QListWidgetItem, QApplication, QMenu,
    QLineEdit,
)
from PySide6.QtCore import Qt, Signal, QThread, QSize
from PySide6.QtGui import QFont, QTextCursor

if TYPE_CHECKING:
    from ..core.llm_client import LLMClient
    from ..core.zotero_parser import ZoteroLibrary
    from ..core.review_checker import ReviewChecker
    from ..core.writing_coach import WritingCoach, WritingProfile


# ============================================================
# 后台工作线程
# ============================================================

class StyleGuideWorker(QThread):
    """后台生成风格指南。"""
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, coach: "WritingCoach", client: "LLMClient"):
        super().__init__()
        self._coach = coach
        self._client = client

    def run(self):
        try:
            guide = self._coach.generate_style_guide(self._client)
            if guide:
                self.finished_signal.emit(guide)
            else:
                self.error_signal.emit("风格分析失败：LLM 返回为空或格式异常")
        except Exception as e:
            self.error_signal.emit(str(e))


class PolishWorker(QThread):
    """后台润色文字。"""
    finished_signal = Signal(str)
    error_signal = Signal(str)

    def __init__(self, coach: "WritingCoach", client: "LLMClient",
                 text: str, writing_type: str):
        super().__init__()
        self._coach = coach
        self._client = client
        self._text = text
        self._writing_type = writing_type

    def run(self):
        try:
            result = self._coach.polish_text(
                self._client, self._text, self._writing_type
            )
            self.finished_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))


class CiteRewriteWorker(QThread):
    """后台基于引文改写。"""
    finished_signal = Signal(str)
    error_signal = Signal(str)

    def __init__(self, coach: "WritingCoach", client: "LLMClient",
                 text: str, zotero, writing_type: str):
        super().__init__()
        self._coach = coach
        self._client = client
        self._text = text
        self._zotero = zotero
        self._writing_type = writing_type

    def run(self):
        try:
            result = self._coach.rewrite_with_citations(
                self._client, self._text, self._zotero, self._writing_type
            )
            self.finished_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))


class MissingLitWorker(QThread):
    """后台检测遗漏文献。"""
    progress_signal = Signal(str)
    finished_signal = Signal(object)  # dict with gaps + papers
    error_signal = Signal(str)

    def __init__(self, coach: "WritingCoach", client: "LLMClient",
                 draft_text: str, zotero):
        super().__init__()
        self._coach = coach
        self._client = client
        self._draft = draft_text
        self._zotero = zotero

    def run(self):
        try:
            # Step 1: LLM 分析
            self.progress_signal.emit("正在分析草稿主题和遗漏方向...")
            gaps = self._coach.detect_missing_literature(
                self._client, self._draft, self._zotero
            )
            if not gaps:
                self.error_signal.emit("LLM 分析失败，无法检测遗漏文献")
                return

            # Step 2: S2 推荐 API
            self.progress_signal.emit("正在调用 S2 推荐 API...")
            # 收集已引用文献的 DOI
            import re
            cited_dois = []
            if self._zotero and hasattr(self._zotero, '_items'):
                cite_pattern = re.compile(r'\[(\d+(?:[,，\s]*\d+)*)\]')
                cited_nums = set()
                for m in cite_pattern.finditer(self._draft):
                    for num in re.split(r'[,，\s]+', m.group(1)):
                        if num.strip().isdigit():
                            cited_nums.add(int(num.strip()))
                for i, item in enumerate(self._zotero._items):
                    if (i + 1) in cited_nums and item.doi:
                        cited_dois.append(item.doi)

            rec_papers = self._coach.search_s2_recommendations(cited_dois)

            # Step 3: S2 搜索 API（补充横向遗漏）
            self.progress_signal.emit("正在 S2 搜索横向遗漏方向...")
            search_papers = []
            for gap in gaps.get("horizontal_gaps", []):
                queries = gap.get("search_queries", [])
                papers = self._coach.search_semantic_scholar(queries, limit=8)
                for p in papers:
                    p["gap_category"] = gap.get("domain", "横向遗漏")
                search_papers.extend(papers)

            for gap in gaps.get("vertical_gaps", []):
                queries = gap.get("search_queries", [])
                papers = self._coach.search_semantic_scholar(queries, limit=8)
                for p in papers:
                    p["gap_category"] = gap.get("domain", "纵向遗漏")
                search_papers.extend(papers)

            self.finished_signal.emit({
                "gaps": gaps,
                "recommendations": rec_papers,
                "search_results": search_papers,
            })
        except Exception as e:
            self.error_signal.emit(str(e))


class ReviewCheckWorker(QThread):
    """后台执行引文核查（复用 review_checker）。"""
    progress_signal = Signal(str, int, int)
    finished_signal = Signal(object)
    error_signal = Signal(str)

    def __init__(self, checker: "ReviewChecker", review_text: str):
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


# ============================================================
# 写作面板
# ============================================================

class WritingPanel(QWidget):
    """写作面板 —— 综述/论文/专利/软著 写作辅助。"""

    # 信号
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._write_client: LLMClient | None = None
        self._zotero: ZoteroLibrary | None = None
        self._review_checker: ReviewChecker | None = None
        self._coach = self._create_coach()
        self._current_writing_type = "综述"
        self._style_worker: StyleGuideWorker | None = None
        self._review_worker: ReviewCheckWorker | None = None

        self._setup_ui()
        self._refresh_kb_dropdown()

    @staticmethod
    def _create_coach():
        from ..core.writing_coach import WritingCoach
        return WritingCoach()

    # ---- 注入依赖 ----

    def set_write_client(self, client: "LLMClient | None"):
        self._write_client = client

    def set_zotero_library(self, zotero: "ZoteroLibrary | None"):
        self._zotero = zotero
        self._update_zotero_status()

    def set_checker(self, checker: "ReviewChecker | None"):
        self._review_checker = checker

    # ---- UI 构建 ----

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ===== 顶部工具栏 =====
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(12, 8, 12, 8)
        toolbar.setSpacing(10)

        title = QLabel("📝 写作")
        title.setObjectName("titleLabel")
        toolbar.addWidget(title)

        # 写作类型
        type_label = QLabel("类型:")
        type_label.setStyleSheet("color: #8a8ea6; font-size: 13px;")
        toolbar.addWidget(type_label)

        self._type_combo = QComboBox()
        self._type_combo.setEditable(True)
        self._type_combo.setMinimumWidth(160)
        from ..core.writing_prompts import get_all_writing_types
        for key, label in get_all_writing_types():
            self._type_combo.addItem(label, key)
        self._type_combo.currentIndexChanged.connect(self._on_writing_type_changed)
        toolbar.addWidget(self._type_combo)

        toolbar.addSpacing(10)

        # 知识库
        kb_label = QLabel("知识库:")
        kb_label.setStyleSheet("color: #8a8ea6; font-size: 13px;")
        toolbar.addWidget(kb_label)

        self._kb_combo = QComboBox()
        self._kb_combo.setEditable(True)
        self._kb_combo.setMinimumWidth(180)
        self._kb_combo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._kb_combo.customContextMenuRequested.connect(self._on_kb_context_menu)
        self._kb_combo.currentIndexChanged.connect(self._on_kb_changed)
        toolbar.addWidget(self._kb_combo)

        toolbar.addSpacing(8)

        # Zotero 路径
        zotero_label = QLabel("Zotero:")
        zotero_label.setStyleSheet("color: #8a8ea6; font-size: 13px;")
        toolbar.addWidget(zotero_label)

        self._zotero_path_edit = QLineEdit()
        self._zotero_path_edit.setPlaceholderText("自动检测...")
        self._zotero_path_edit.setMaximumWidth(200)
        self._zotero_path_edit.setStyleSheet(
            "QLineEdit { background-color: #24253a; color: #a9b1d6; "
            "border: 1px solid #3b3d54; border-radius: 4px; padding: 2px 6px; "
            "font-size: 12px; }"
        )
        toolbar.addWidget(self._zotero_path_edit)

        self._zotero_browse_btn = QPushButton("📂")
        self._zotero_browse_btn.setFixedWidth(45)
        self._zotero_browse_btn.setToolTip("浏览选择 Zotero 数据目录")
        self._zotero_browse_btn.clicked.connect(self._on_zotero_browse)
        toolbar.addWidget(self._zotero_browse_btn)

        toolbar.addStretch()
        main_layout.addLayout(toolbar)

        # ===== 分隔线 =====
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #2a2c3d; max-height: 1px;")
        main_layout.addWidget(sep)

        # ===== 主区域: 编辑器 | 右侧栏 =====
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(3)
        splitter.setOpaqueResize(False)

        # -- 编辑器 --
        editor_frame = QFrame()
        editor_frame.setStyleSheet("background-color: #1a1b26;")
        editor_layout = QVBoxLayout(editor_frame)
        editor_layout.setContentsMargins(8, 8, 8, 8)

        self.editor = QTextEdit()
        self.editor.setPlaceholderText(
            "在此编写你的综述/论文...\n\n"
            "提示：选中文字后可在右侧使用 AI 辅助功能"
        )
        self.editor.setStyleSheet(
            "QTextEdit { background-color: #1e2030; color: #cfd2e3; "
            "border: 1px solid #3b3d54; border-radius: 8px; "
            "padding: 16px; font-size: 14px; line-height: 1.8; }"
            "QTextEdit:focus { border-color: #7aa2f7; }"
        )
        editor_layout.addWidget(self.editor)

        splitter.addWidget(editor_frame)

        # -- 右侧栏 --
        right_frame = QFrame()
        right_frame.setMinimumWidth(220)
        right_frame.setMaximumWidth(320)
        right_frame.setStyleSheet("background-color: #1a1b26;")
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(10)

        # 知识库状态
        kb_group = QGroupBox("📚 知识库状态")
        kb_group.setStyleSheet(
            "QGroupBox { color: #a9b1d6; font-weight: bold; border: 1px solid #2a2c3d; "
            "border-radius: 8px; margin-top: 8px; padding: 12px 8px 8px 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
        )
        kb_layout = QVBoxLayout(kb_group)
        kb_layout.setSpacing(6)

        self._kb_status_label = QLabel("未选择知识库")
        self._kb_status_label.setWordWrap(True)
        self._kb_status_label.setStyleSheet("color: #8a8ea6; font-size: 12px;")
        kb_layout.addWidget(self._kb_status_label)

        self._personal_btn = QPushButton("📄 添加参考论文")
        self._personal_btn.setToolTip("上传你自己的论文 PDF 供风格分析")
        self._personal_btn.clicked.connect(self._on_add_personal_paper)
        kb_layout.addWidget(self._personal_btn)

        self._journal_btn = QPushButton("📰 添加期刊范文")
        self._journal_btn.setToolTip("上传目标期刊的综述 PDF 供风格分析")
        self._journal_btn.clicked.connect(self._on_add_journal_paper)
        kb_layout.addWidget(self._journal_btn)

        self._style_btn = QPushButton("📐 生成风格指南")
        self._style_btn.setToolTip("基于已添加的论文和范文，让 AI 分析写作风格并生成指南")
        self._style_btn.clicked.connect(self._on_generate_style_guide)
        self._style_btn.setEnabled(False)
        kb_layout.addWidget(self._style_btn)

        right_layout.addWidget(kb_group)

        # Zotero 状态
        zotero_group = QGroupBox("📖 Zotero")
        zotero_group.setStyleSheet(
            "QGroupBox { color: #a9b1d6; font-weight: bold; border: 1px solid #2a2c3d; "
            "border-radius: 8px; margin-top: 8px; padding: 12px 8px 8px 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
        )
        zotero_layout = QVBoxLayout(zotero_group)
        zotero_layout.setSpacing(4)

        self._zotero_status_label = QLabel("未连接")
        self._zotero_status_label.setWordWrap(True)
        self._zotero_status_label.setStyleSheet("color: #636688; font-size: 12px;")
        zotero_layout.addWidget(self._zotero_status_label)
        right_layout.addWidget(zotero_group)

        # AI 辅助
        ai_group = QGroupBox("🤖 AI 辅助")
        ai_group.setStyleSheet(
            "QGroupBox { color: #a9b1d6; font-weight: bold; border: 1px solid #2a2c3d; "
            "border-radius: 8px; margin-top: 8px; padding: 12px 8px 8px 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
        )
        ai_layout = QVBoxLayout(ai_group)
        ai_layout.setSpacing(6)

        self._polish_btn = QPushButton("✨ 润色选中文字")
        self._polish_btn.setToolTip("AI 润色编辑器中选中的文字")
        self._polish_btn.clicked.connect(self._on_polish)
        ai_layout.addWidget(self._polish_btn)

        self._cite_rewrite_btn = QPushButton("📎 基于引文改写")
        self._cite_rewrite_btn.setToolTip("根据 Zotero 中引用文献的原文改写选中文字")
        self._cite_rewrite_btn.clicked.connect(self._on_cite_rewrite)
        ai_layout.addWidget(self._cite_rewrite_btn)

        self._check_cite_btn = QPushButton("📖 核查引文准确性")
        self._check_cite_btn.setToolTip("逐条检查综述中的引文是否准确反映原文观点")
        self._check_cite_btn.clicked.connect(self._on_check_citations)
        ai_layout.addWidget(self._check_cite_btn)

        self._missing_lit_btn = QPushButton("🔍 检测遗漏文献")
        self._missing_lit_btn.setToolTip("分析草稿主题，检索可能遗漏的文献")
        self._missing_lit_btn.clicked.connect(self._on_detect_missing)
        ai_layout.addWidget(self._missing_lit_btn)

        right_layout.addWidget(ai_group)
        right_layout.addStretch()

        splitter.addWidget(right_frame)
        splitter.setSizes([650, 250])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        main_layout.addWidget(splitter, 1)

        # ===== 底部状态栏 =====
        status_sep = QFrame()
        status_sep.setFrameShape(QFrame.Shape.HLine)
        status_sep.setStyleSheet("background-color: #2a2c3d; max-height: 1px;")
        main_layout.addWidget(status_sep)

        status_bar = QHBoxLayout()
        status_bar.setContentsMargins(12, 4, 12, 4)
        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet("color: #8a8ea6; font-size: 12px;")
        status_bar.addWidget(self._status_label)
        status_bar.addStretch()

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        self._progress_bar.setMaximumWidth(180)
        self._progress_bar.setMaximumHeight(14)
        self._progress_bar.setStyleSheet(
            "QProgressBar { background-color: #24253a; border: 1px solid #3b3d54; "
            "border-radius: 7px; }"
            "QProgressBar::chunk { background-color: #7aa2f7; border-radius: 6px; }"
        )
        status_bar.addWidget(self._progress_bar)
        main_layout.addLayout(status_bar)

    # ---- 知识库操作 ----

    def _refresh_kb_dropdown(self):
        """刷新知识库下拉列表，最后一项为'＋ 新建知识库...'。"""
        self._kb_combo.blockSignals(True)
        self._kb_combo.clear()
        self._kb_combo.addItem("(未选择)", "")
        for name in self._coach.profile_names:
            profile = self._coach._profiles.get(name)
            extra = ""
            if profile:
                extra = f" ({profile.personal_count}篇论文, {profile.journal_count}篇范文)"
            self._kb_combo.addItem(f"{name}{extra}", name)

        # 分隔 + 新建项
        self._kb_combo.insertSeparator(self._kb_combo.count())
        self._kb_combo.addItem("＋ 新建知识库...", "__new__")

        # 恢复当前选择
        if self._coach.current_profile:
            idx = self._kb_combo.findData(self._coach.current_profile.name)
            if idx >= 0:
                self._kb_combo.setCurrentIndex(idx)
        self._kb_combo.blockSignals(False)
        self._update_kb_status()

    def _on_kb_changed(self, idx: int):
        data = self._kb_combo.itemData(idx) or ""
        if data == "__new__":
            # 触发新建
            self._kb_combo.blockSignals(True)
            self._kb_combo.setCurrentIndex(0)
            self._kb_combo.blockSignals(False)
            self._on_new_kb()
            return
        if data and data in self._coach.profile_names:
            self._coach.switch_profile(data)
            profile = self._coach.current_profile
            if profile and profile.writing_type:
                type_idx = self._type_combo.findData(profile.writing_type)
                if type_idx >= 0:
                    self._type_combo.blockSignals(True)
                    self._type_combo.setCurrentIndex(type_idx)
                    self._type_combo.blockSignals(False)
                    self._current_writing_type = profile.writing_type
        else:
            self._coach._current_profile = None
        self._update_kb_status()

    def _on_kb_context_menu(self, pos):
        """知识库下拉右键菜单：删除。"""
        data = self._kb_combo.currentData() or ""
        if not data or data == "__new__" or data not in self._coach.profile_names:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #24253a; color: #cfd2e3; border: 1px solid #3b3d54; }"
            "QMenu::item:selected { background: #3b3d54; }"
        )
        a = menu.addAction("🗑 删除此知识库")
        a.triggered.connect(lambda: self._on_delete_kb())
        menu.exec(self._kb_combo.mapToGlobal(pos))

    def _on_zotero_browse(self):
        """浏览选择 Zotero 数据目录。"""
        current = self._zotero_path_edit.text().strip()
        path = QFileDialog.getExistingDirectory(self, "选择 Zotero 数据目录", current or "")
        if path:
            self._zotero_path_edit.setText(path)
            # 同时更新 config
            from ..utils.config import load_config, save_config
            cfg = load_config()
            cfg["zotero_data_dir"] = path
            save_config(cfg)
            self._status_label.setText(f"Zotero 路径已更新: {path}")

    def _on_writing_type_changed(self, idx: int):
        self._current_writing_type = self._type_combo.itemData(idx) or "综述"

    def _on_new_kb(self):
        name, ok = QInputDialog.getText(
            self, "新建知识库", "知识库名称：",
        )
        if ok and name.strip():
            try:
                profile = self._coach.create_profile(
                    name.strip(), self._current_writing_type
                )
                self._refresh_kb_dropdown()
                self._status_label.setText(f"已创建知识库: {name.strip()}")
            except ValueError as e:
                QMessageBox.warning(self, "创建失败", str(e))

    def _on_delete_kb(self):
        if not self._coach.current_profile:
            return
        name = self._coach.current_profile.name
        r = QMessageBox.question(
            self, "确认删除",
            f"删除知识库「{name}」及其所有关联论文数据？\n此操作不可恢复。"
        )
        if r == QMessageBox.StandardButton.Yes:
            self._coach.delete_profile(name)
            self._refresh_kb_dropdown()
            self._status_label.setText(f"已删除知识库: {name}")

    def _on_add_personal_paper(self):
        if not self._coach.current_profile:
            QMessageBox.warning(self, "提示", "请先选择或创建一个知识库")
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择参考论文 PDF", "", "PDF 文件 (*.pdf);;所有文件 (*.*)"
        )
        for path in paths:
            result = self._coach.add_personal_paper(path)
            if result:
                self._status_label.setText(f"已添加个人论文: {result['filename']}")
            else:
                self._status_label.setText(f"添加失败: {os.path.basename(path)}")
        self._refresh_kb_dropdown()

    def _on_add_journal_paper(self):
        if not self._coach.current_profile:
            QMessageBox.warning(self, "提示", "请先选择或创建一个知识库")
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择期刊范文 PDF", "", "PDF 文件 (*.pdf);;所有文件 (*.*)"
        )
        for path in paths:
            result = self._coach.add_journal_paper(path)
            if result:
                self._status_label.setText(f"已添加期刊范文: {result['filename']}")
            else:
                self._status_label.setText(f"添加失败: {os.path.basename(path)}")
        self._refresh_kb_dropdown()

    def _on_generate_style_guide(self):
        """生成风格指南（Phase 2）。"""
        if not self._coach.current_profile:
            return
        if self._coach.current_profile.total_papers == 0:
            QMessageBox.warning(self, "提示", "请先添加参考论文或期刊范文")
            return
        if not self._write_client:
            QMessageBox.warning(self, "提示", "请先配置写作 API")
            return

        self._style_btn.setEnabled(False)
        self._style_btn.setText("⏳ 分析中...")
        self._progress_bar.setVisible(True)
        self._progress_bar.setRange(0, 0)  # 不确定进度条
        self._status_label.setText("正在分析写作风格（可能需要 30-60 秒）...")
        QApplication.processEvents()

        self._style_worker = StyleGuideWorker(self._coach, self._write_client)
        self._style_worker.finished_signal.connect(self._on_style_guide_ready)
        self._style_worker.error_signal.connect(self._on_style_guide_error)
        self._style_worker.start()

    def _on_style_guide_ready(self, guide: dict):
        self._progress_bar.setVisible(False)
        self._progress_bar.setRange(0, 100)
        self._style_btn.setEnabled(True)
        self._style_btn.setText("📐 重新生成")
        self._update_kb_status()
        self._status_label.setText("✅ 风格指南已生成")

        # 简略展示风格指南内容
        lines = []
        if guide.get("citation_style"):
            lines.append(f"引用格式: {guide['citation_style'][:80]}")
        if guide.get("structure_template"):
            lines.append(f"结构: {guide['structure_template'][:80]}")
        if guide.get("sentence_templates"):
            n = len(guide["sentence_templates"]) if isinstance(guide["sentence_templates"], list) else 1
            lines.append(f"句式模板: {n} 个")
        QMessageBox.information(
            self, "风格指南已生成",
            "AI 已分析所有论文并生成写作风格指南。\n\n"
            + "\n".join(lines) +
            "\n\n后续写作时，AI 将自动遵循此风格指南。"
        )

    def _on_style_guide_error(self, err: str):
        self._progress_bar.setVisible(False)
        self._progress_bar.setRange(0, 100)
        self._style_btn.setEnabled(True)
        self._style_btn.setText("📐 生成风格指南")
        self._status_label.setText(f"风格分析失败: {err[:60]}")
        QMessageBox.warning(self, "风格分析失败", err)

    # ---- Phase 3: 润色 + 引文改写 + 遗漏检测 ----

    def _on_polish(self):
        """润色选中文字。"""
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            QMessageBox.warning(self, "提示", "请先在编辑器中选中要润色的文字")
            return
        if not self._write_client:
            QMessageBox.warning(self, "提示", "请先配置写作 API")
            return

        text = cursor.selectedText().strip()
        self._polish_btn.setEnabled(False)
        self._polish_btn.setText("⏳ 润色中...")
        self._status_label.setText("正在润色...")

        self._polish_worker = PolishWorker(
            self._coach, self._write_client, text, self._current_writing_type
        )
        self._polish_worker.finished_signal.connect(self._on_polish_done)
        self._polish_worker.error_signal.connect(self._on_polish_error)
        self._polish_worker.start()

    def _on_polish_done(self, result: str):
        self._polish_btn.setEnabled(True)
        self._polish_btn.setText("✨ 润色选中文字")
        self._status_label.setText("润色完成")
        # 替换选中文字
        cursor = self.editor.textCursor()
        cursor.insertText(result)
        QMessageBox.information(self, "润色完成", "已将润色后的文字替换到编辑器中。")

    def _on_polish_error(self, err: str):
        self._polish_btn.setEnabled(True)
        self._polish_btn.setText("✨ 润色选中文字")
        self._status_label.setText(f"润色失败: {err[:60]}")
        QMessageBox.warning(self, "润色失败", err)

    def _on_cite_rewrite(self):
        """基于引文改写。"""
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            QMessageBox.warning(self, "提示", "请先在编辑器中选中包含引用的文字")
            return
        if not self._write_client:
            QMessageBox.warning(self, "提示", "请先配置写作 API")
            return
        if not self._zotero or not self._zotero.is_available:
            QMessageBox.warning(self, "提示", "请先连接 Zotero 文献库")
            return

        text = cursor.selectedText().strip()
        self._cite_rewrite_btn.setEnabled(False)
        self._cite_rewrite_btn.setText("⏳ 改写中...")
        self._status_label.setText("正在基于引文原文改写...")

        self._cite_worker = CiteRewriteWorker(
            self._coach, self._write_client, text,
            self._zotero, self._current_writing_type
        )
        self._cite_worker.finished_signal.connect(self._on_cite_rewrite_done)
        self._cite_worker.error_signal.connect(self._on_cite_rewrite_error)
        self._cite_worker.start()

    def _on_cite_rewrite_done(self, result: str):
        self._cite_rewrite_btn.setEnabled(True)
        self._cite_rewrite_btn.setText("📎 基于引文改写")
        self._status_label.setText("改写完成")
        cursor = self.editor.textCursor()
        cursor.insertText("\n\n" + result)
        QMessageBox.information(self, "改写完成", "改写结果已追加到编辑器中。")

    def _on_cite_rewrite_error(self, err: str):
        self._cite_rewrite_btn.setEnabled(True)
        self._cite_rewrite_btn.setText("📎 基于引文改写")
        self._status_label.setText(f"改写失败: {err[:60]}")

    def _on_detect_missing(self):
        """检测遗漏文献。"""
        draft = self.editor.toPlainText().strip()
        if not draft:
            QMessageBox.warning(self, "提示", "请先编写包含引用的综述草稿")
            return
        if not self._write_client:
            QMessageBox.warning(self, "提示", "请先配置写作 API")
            return

        self._missing_lit_btn.setEnabled(False)
        self._missing_lit_btn.setText("⏳ 检测中...")
        self._progress_bar.setVisible(True)
        self._progress_bar.setRange(0, 0)
        self._status_label.setText("正在分析草稿 + 检索 S2...")

        self._missing_worker = MissingLitWorker(
            self._coach, self._write_client, draft, self._zotero
        )
        self._missing_worker.progress_signal.connect(
            lambda msg: self._status_label.setText(msg)
        )
        self._missing_worker.finished_signal.connect(self._on_missing_lit_done)
        self._missing_worker.error_signal.connect(self._on_missing_lit_error)
        self._missing_worker.start()

    def _on_missing_lit_done(self, result: dict):
        self._progress_bar.setVisible(False)
        self._progress_bar.setRange(0, 100)
        self._missing_lit_btn.setEnabled(True)
        self._missing_lit_btn.setText("🔍 检测遗漏文献")
        self._status_label.setText("遗漏文献检测完成")

        gaps = result.get("gaps", {})
        recs = result.get("recommendations", [])
        search = result.get("search_results", [])

        # 构建展示文本
        lines = ["=== 遗漏文献检测结果 ===\n"]

        # 已覆盖方向
        covered = gaps.get("covered_domains", [])
        if covered:
            lines.append("📊 已覆盖方向：")
            for d in covered:
                lines.append(f"  · {d.get('domain', '?')} ({d.get('paper_count', 0)}篇, 最新{d.get('latest_year', '?')})")

        # S2 推荐
        if recs:
            lines.append(f"\n📚 S2 推荐文献（基于你已引用文献）：")
            for p in recs[:10]:
                lines.append(f"  · {p['authors']} ({p['year']}) - {p['title'][:80]} ⭐{p.get('citationCount', 0)}")

        # 搜索补充
        if search:
            lines.append(f"\n🔍 横向/纵向补充搜索：")
            for p in search[:10]:
                gap = p.get("gap_category", "")
                lines.append(f"  [{gap}] {p['authors']} ({p['year']}) - {p['title'][:80]} ⭐{p.get('citationCount', 0)}")

        # 导出 CSV 按钮
        full_text = "\n".join(lines)
        msg = QMessageBox(self)
        msg.setWindowTitle("遗漏文献检测")
        msg.setText(full_text[:2000])
        msg.setDetailedText(full_text)

        # 导出 CSV
        export_btn = msg.addButton("导出选中为CSV", QMessageBox.ButtonRole.ActionRole)
        close_btn = msg.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        if msg.clickedButton() == export_btn:
            self._export_missing_csv(recs + search)

    def _on_missing_lit_error(self, err: str):
        self._progress_bar.setVisible(False)
        self._progress_bar.setRange(0, 100)
        self._missing_lit_btn.setEnabled(True)
        self._missing_lit_btn.setText("🔍 检测遗漏文献")
        self._status_label.setText(f"检测失败: {err[:60]}")
        QMessageBox.warning(self, "检测失败", err)

    def _export_missing_csv(self, papers: list[dict]):
        """导出文献列表为 CSV。"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出遗漏文献 CSV", "missing_literature.csv",
            "CSV 文件 (*.csv)"
        )
        if not path:
            return
        import csv
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["title", "authors", "year", "citationCount", "doi", "url", "source", "gap_category"])
                for p in papers:
                    writer.writerow([
                        p.get("title", ""),
                        p.get("authors", ""),
                        p.get("year", ""),
                        p.get("citationCount", ""),
                        p.get("doi", ""),
                        p.get("url", ""),
                        p.get("source", ""),
                        p.get("gap_category", ""),
                    ])
            self._status_label.setText(f"CSV 已导出: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    # ---- Zotero ----

    def _update_zotero_status(self):
        if self._zotero and self._zotero.is_available:
            count = len(self._zotero._items) if hasattr(self._zotero, '_items') else 0
            self._zotero_status_label.setText(f"✅ 已连接 ({count} 篇文献)")
            self._zotero_status_label.setStyleSheet("color: #9ece6a; font-size: 12px;")
            # 更新路径显示
            from ..utils.config import load_config
            cfg = load_config()
            zdir = cfg.get("zotero_data_dir", "") or self._zotero._data_dir
            if zdir and not self._zotero_path_edit.text():
                self._zotero_path_edit.setText(zdir)
        else:
            self._zotero_status_label.setText("⚠️ 未连接")
            self._zotero_status_label.setStyleSheet("color: #e0af68; font-size: 12px;")

    # ---- 知识库状态 ----

    def _update_kb_status(self):
        profile = self._coach.current_profile
        if profile:
            lines = [
                f"名称: {profile.name}",
                f"类型: {profile.writing_type}",
                f"个人论文: {profile.personal_count} 篇",
                f"期刊范文: {profile.journal_count} 篇",
                f"风格指南: {'✅ 已生成' if profile.has_style_guide else '⏳ 未生成'}",
            ]
            self._kb_status_label.setText("\n".join(lines))
            self._style_btn.setEnabled(profile.total_papers > 0)
        else:
            self._kb_status_label.setText("未选择知识库\n请在下拉菜单中选择或新建")
            self._style_btn.setEnabled(False)

    # ---- AI 辅助 ----

    def _on_check_citations(self):
        """核查引文准确性。"""
        text = self.editor.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请先编写包含引用的综述文本")
            return
        if not self._review_checker:
            QMessageBox.warning(self, "提示", "引文核查功能需要配置写作 API 和 Zotero 连接")
            return

        self._check_cite_btn.setEnabled(False)
        self._check_cite_btn.setText("⏳ 核查中...")
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)

        self._review_worker = ReviewCheckWorker(self._review_checker, text)
        self._review_worker.progress_signal.connect(self._on_review_progress)
        self._review_worker.finished_signal.connect(self._on_review_finished)
        self._review_worker.error_signal.connect(self._on_review_error)
        self._review_worker.start()

    def _on_review_progress(self, msg: str, cur: int, tot: int):
        self._progress_bar.setValue(int(cur / max(tot, 1) * 100))
        self._status_label.setText(msg)

    def _on_review_finished(self, result):
        self._progress_bar.setVisible(False)
        self._check_cite_btn.setEnabled(True)
        self._check_cite_btn.setText("📖 核查引文准确性")

        # 展示结果
        if hasattr(result, 'claims'):
            n = len(result.claims)
            issues = sum(1 for c in result.claims if c.status != "引用恰当")
            self._status_label.setText(f"核查完成: {n} 条引文, {issues} 条需关注")
            # TODO: 弹窗展示详细结果（复用 ClaimResultCard）
            details = "\n\n".join(
                f"[{c.status}] 引文{c.citation_marker}: {c.ai_feedback[:200]}"
                for c in result.claims if c.status != "引用恰当"
            )
            if details:
                QMessageBox.information(self, "引文核查结果", details[:2000] or "未发现明显问题")
            else:
                QMessageBox.information(self, "引文核查结果", "✅ 所有引文表述准确")
        else:
            self._status_label.setText("核查完成")

    def _on_review_error(self, err: str):
        self._progress_bar.setVisible(False)
        self._check_cite_btn.setEnabled(True)
        self._check_cite_btn.setText("📖 核查引文准确性")
        self._status_label.setText(f"核查失败: {err[:80]}")

    # ---- 生命周期 ----

    def shutdown(self):
        """清理后台线程。"""
        if self._style_worker and self._style_worker.isRunning():
            self._style_worker.quit()
            self._style_worker.wait(2000)
        if self._review_worker and self._review_worker.isRunning():
            self._review_worker.quit()
            self._review_worker.wait(2000)

    def get_editor_text(self) -> str:
        return self.editor.toPlainText()

    def set_editor_text(self, text: str):
        self.editor.setPlainText(text)
