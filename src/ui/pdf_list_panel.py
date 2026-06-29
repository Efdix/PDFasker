"""
PDF 文件列表面板 —— 管理导入的 PDF、文件夹分类
"""

import os
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QFileDialog, QInputDialog, QMenu, QMessageBox,
    QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from ..utils.config import (
    load_config, save_config, load_library, save_library,
    add_pdf_to_library, remove_pdf_from_library, get_library_folders,
)


class PDFListPanel(QWidget):
    """左侧 PDF 文件列表面板 —— 支持拖拽导入"""

    pdf_selected = Signal(str)
    pdf_removed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(180)
        self.setMaximumWidth(320)
        self.setAcceptDrops(True)
        self._library: list[dict] = []
        self._setup_ui()
        self._refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        header = QHBoxLayout()
        header.setContentsMargins(12, 8, 12, 8)
        title = QLabel("论文库")
        title.setObjectName("titleLabel")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #2a2c3d; max-height: 1px;")
        layout.addWidget(sep)

        # 快捷操作栏
        action_bar = QHBoxLayout()
        action_bar.setContentsMargins(8, 4, 8, 4)
        action_bar.setSpacing(4)

        self.import_btn = QPushButton("+ 导入 PDF")
        self.import_btn.clicked.connect(self._import_pdf)
        action_bar.addWidget(self.import_btn)

        self.folder_btn = QPushButton("+ 文件夹")
        self.folder_btn.setToolTip("新建分类文件夹")
        self.folder_btn.clicked.connect(self._new_folder)
        action_bar.addWidget(self.folder_btn)

        self.lib_path_btn = QPushButton("...")
        self.lib_path_btn.setToolTip("设置图书馆存储路径")
        self.lib_path_btn.setFixedWidth(32)
        self.lib_path_btn.clicked.connect(self._set_library_path)
        action_bar.addWidget(self.lib_path_btn)

        layout.addLayout(action_bar)

        # 树形文件列表
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setAnimated(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.setStyleSheet(
            "QTreeWidget { background-color: #1a1b26; border: none; outline: none; }"
            "QTreeWidget::item { padding: 6px 10px; color: #cfd2e3; border-radius: 4px; }"
            "QTreeWidget::item:hover { background-color: #2a2c3d; }"
            "QTreeWidget::item:selected { background-color: #3b3d54; }"
        )
        layout.addWidget(self.tree, 1)

        # 底部信息
        footer = QLabel()
        footer.setObjectName("subtitleLabel")
        footer.setContentsMargins(12, 4, 12, 8)
        self._footer_label = footer
        layout.addWidget(footer)

    def _refresh(self):
        """刷新列表 —— 排序：文件夹在前 + 按名称排序"""
        self._library = load_library()

        # 按导入时间排序（新的在前）
        self._library.sort(key=lambda x: x.get("imported_at", ""), reverse=True)

        self.tree.clear()
        folders = sorted(get_library_folders(self._library))

        # 文件夹节点（先添加文件夹，显示为粗体）
        folder_items: dict[str, QTreeWidgetItem] = {}
        for folder in folders:
            item = QTreeWidgetItem([folder])
            item.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "name": folder})
            font = item.font(0)
            font.setBold(True)
            font.setPointSize(11)
            item.setFont(0, font)
            item.setForeground(0, Qt.GlobalColor.white)  # 会被 stylesheet 覆盖，但作为兜底
            self.tree.addTopLevelItem(item)
            folder_items[folder] = item

        # 未分类的 PDF
        for pdf in self._library:
            folder = pdf.get("folder", "")
            fname = pdf.get("name", os.path.basename(pdf.get("path", "")))
            file_item = QTreeWidgetItem([fname])
            file_item.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "pdf",
                "path": pdf.get("path"),
            })
            file_item.setToolTip(0, pdf.get("path", ""))
            # 根据文件是否存在设置颜色
            if os.path.exists(pdf.get("path", "")):
                file_item.setForeground(0, Qt.GlobalColor.white)
            else:
                file_item.setForeground(0, Qt.GlobalColor.darkGray)
                file_item.setText(0, fname + " (缺失)")

            if folder and folder in folder_items:
                folder_items[folder].addChild(file_item)
            else:
                self.tree.addTopLevelItem(file_item)

        self.tree.expandAll()
        total = len(self._library)
        self._footer_label.setText(f"共 {total} 篇论文")

    def _import_pdf(self):
        config = load_config()
        lib_path = config.get("library_path", str(Path.home() / "Documents" / "PDFasker_Library"))
        files, _ = QFileDialog.getOpenFileNames(
            self, "导入 PDF 论文", "", "PDF 文件 (*.pdf);;所有文件 (*.*)"
        )
        if files:
            self._import_files(files)

    def _import_files(self, files: list[str]):
        config = load_config()
        lib_path = config.get("library_path", str(Path.home() / "Documents" / "PDFasker_Library"))
        os.makedirs(lib_path, exist_ok=True)
        for file_path in files:
            fname = os.path.basename(file_path)
            dest = os.path.join(lib_path, fname)
            counter = 1
            name, ext = os.path.splitext(fname)
            while os.path.exists(dest):
                dest = os.path.join(lib_path, f"{name}_{counter}{ext}")
                counter += 1
            try:
                shutil.copy2(file_path, dest)
                add_pdf_to_library({
                    "name": os.path.basename(dest),
                    "path": dest,
                    "folder": "",
                    "imported_at": datetime.now().isoformat(),
                })
            except OSError as e:
                QMessageBox.warning(self, "导入失败", str(e))
        self._refresh()

    def _new_folder(self):
        name, ok = QInputDialog.getText(self, "新建文件夹", "文件夹名称：")
        if ok and name.strip():
            # 文件夹作为分类标签存在；这里不需要单独存储
            self._refresh()

    def _set_library_path(self):
        config = load_config()
        current = config.get("library_path", "")
        path = QFileDialog.getExistingDirectory(self, "选择图书馆路径", current)
        if path:
            config["library_path"] = path
            save_config(config)
            QMessageBox.information(self, "已设置", f"图书馆路径：\n{path}")

    def _on_item_clicked(self, item: QTreeWidgetItem, col: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "pdf":
            path = data.get("path", "")
            if path and os.path.exists(path):
                self.pdf_selected.emit(path)
            else:
                QMessageBox.warning(self, "文件缺失", f"找不到文件：\n{path}")

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #24253a; color: #cfd2e3; border: 1px solid #3b3d54; }"
            "QMenu::item:selected { background: #3b3d54; }"
        )

        if data and data.get("type") == "pdf":
            path = data.get("path", "")
            move_menu = menu.addMenu("  移动到")
            folders = sorted(get_library_folders(self._library))
            a = move_menu.addAction("(未分类)")
            a.triggered.connect(lambda: self._move_pdf(path, ""))
            if folders:
                move_menu.addSeparator()
            for f in folders:
                a = move_menu.addAction(f)
                a.triggered.connect(lambda checked, folder=f: self._move_pdf(path, folder))
            menu.addSeparator()
            a = menu.addAction("  从库中移除")
            a.triggered.connect(lambda: self._remove_pdf(path))
        elif data and data.get("type") == "folder":
            name = data.get("name", "")
            a = menu.addAction("  重命名")
            a.triggered.connect(lambda: self._rename_folder(name))
            a = menu.addAction("  删除（文件保留）")
            a.triggered.connect(lambda: self._delete_folder(name))

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _move_pdf(self, path: str, folder: str):
        lib = load_library()
        for item in lib:
            if item.get("path") == path:
                item["folder"] = folder
                break
        save_library(lib)
        self._refresh()

    def _remove_pdf(self, path: str):
        r = QMessageBox.question(self, "确认", "从论文库中移除此 PDF？\n（不删除文件）")
        if r == QMessageBox.StandardButton.Yes:
            remove_pdf_from_library(path)
            self.pdf_removed.emit(path)
            self._refresh()

    def _rename_folder(self, old: str):
        new, ok = QInputDialog.getText(self, "重命名", "新名称：", text=old)
        if ok and new.strip() and new != old:
            lib = load_library()
            for item in lib:
                if item.get("folder") == old:
                    item["folder"] = new.strip()
            save_library(lib)
            self._refresh()

    def _delete_folder(self, name: str):
        r = QMessageBox.question(self, "确认", f"删除文件夹「{name}」？\n文件将变为未分类。")
        if r == QMessageBox.StandardButton.Yes:
            lib = load_library()
            for item in lib:
                if item.get("folder") == name:
                    item["folder"] = ""
            save_library(lib)
            self._refresh()

    # ========== 拖拽导入 ==========

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".pdf"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith(".pdf"):
                paths.append(p)
        if paths:
            self._import_files(paths)
