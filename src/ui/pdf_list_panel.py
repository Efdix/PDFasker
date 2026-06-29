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
    QFrame, QHeaderView,
)
from PySide6.QtCore import Qt, Signal

from ..utils.config import (
    load_config, save_config, load_library, save_library,
    add_pdf_to_library, remove_pdf_from_library, get_library_folders,
)


class PDFListPanel(QWidget):
    """左侧 PDF 文件列表面板"""

    pdf_selected = Signal(str)     # 选中 PDF 路径
    pdf_removed = Signal(str)      # PDF 被移除

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(200)
        self.setMaximumWidth(350)
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

        title = QLabel("📚 论文库")
        title.setObjectName("titleLabel")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #313244; max-height: 1px;")
        layout.addWidget(sep)

        # 快捷操作栏
        action_bar = QHBoxLayout()
        action_bar.setContentsMargins(8, 4, 8, 4)
        action_bar.setSpacing(4)

        self.import_btn = QPushButton("＋ 导入")
        self.import_btn.clicked.connect(self._import_pdf)
        action_bar.addWidget(self.import_btn)

        self.folder_btn = QPushButton("📁")
        self.folder_btn.setToolTip("新建文件夹")
        self.folder_btn.setFixedWidth(36)
        self.folder_btn.clicked.connect(self._new_folder)
        action_bar.addWidget(self.folder_btn)

        self.lib_path_btn = QPushButton("📂")
        self.lib_path_btn.setToolTip("设置图书馆路径")
        self.lib_path_btn.setFixedWidth(36)
        self.lib_path_btn.clicked.connect(self._set_library_path)
        action_bar.addWidget(self.lib_path_btn)

        layout.addLayout(action_bar)

        # 树形文件列表
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.setStyleSheet(
            "QTreeWidget { background-color: #1e1e2e; border: none; }"
            "QTreeWidget::item { padding: 4px 8px; }"
            "QTreeWidget::item:hover { background-color: #313244; }"
            "QTreeWidget::item:selected { background-color: #45475a; }"
        )
        layout.addWidget(self.tree, 1)

        # 底部信息
        footer = QLabel()
        footer.setObjectName("subtitleLabel")
        footer.setContentsMargins(12, 4, 12, 8)
        self._footer_label = footer
        layout.addWidget(footer)

    def _refresh(self):
        """刷新列表"""
        self._library = load_library()
        self.tree.clear()

        folders = get_library_folders(self._library)
        uncategorized = [item for item in self._library if not item.get("folder")]

        # 文件夹节点
        folder_items: dict[str, QTreeWidgetItem] = {}
        for folder in folders:
            folder_item = QTreeWidgetItem([f"📁 {folder}"])
            folder_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "name": folder})
            font = folder_item.font(0)
            font.setBold(True)
            folder_item.setFont(0, font)
            self.tree.addTopLevelItem(folder_item)
            folder_items[folder] = folder_item

        # 文件放入对应文件夹
        for item in self._library:
            folder = item.get("folder", "")
            fname = item.get("name", os.path.basename(item.get("path", "")))
            file_item = QTreeWidgetItem([f"📄 {fname}"])
            file_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "pdf", "path": item.get("path")})
            file_item.setToolTip(0, item.get("path", ""))

            if folder and folder in folder_items:
                folder_items[folder].addChild(file_item)
            else:
                self.tree.addTopLevelItem(file_item)

        # 展开所有文件夹
        self.tree.expandAll()

        # 更新底部信息
        total = len(self._library)
        self._footer_label.setText(f"共 {total} 篇论文")

    def _import_pdf(self):
        """导入 PDF"""
        config = load_config()
        library_path = config.get("library_path", str(Path.home() / "Documents" / "PDFasker_Library"))

        files, _ = QFileDialog.getOpenFileNames(
            self, "导入 PDF 论文", "", "PDF 文件 (*.pdf);;所有文件 (*.*)"
        )
        if not files:
            return

        os.makedirs(library_path, exist_ok=True)

        for file_path in files:
            fname = os.path.basename(file_path)
            dest = os.path.join(library_path, fname)

            # 如果目标已存在，加序号
            counter = 1
            name, ext = os.path.splitext(fname)
            while os.path.exists(dest):
                dest = os.path.join(library_path, f"{name}_{counter}{ext}")
                counter += 1

            try:
                shutil.copy2(file_path, dest)
                pdf_info = {
                    "name": os.path.basename(dest),
                    "path": dest,
                    "folder": "",
                    "imported_at": datetime.now().isoformat(),
                }
                add_pdf_to_library(pdf_info)
            except OSError as e:
                QMessageBox.warning(self, "导入失败", f"无法复制文件：\n{str(e)}")

        self._refresh()

    def _new_folder(self):
        """新建文件夹"""
        name, ok = QInputDialog.getText(self, "新建文件夹", "文件夹名称：")
        if ok and name.strip():
            # 文件夹只是一个分类标签，存在 library 数据中即可
            self._refresh()

    def _set_library_path(self):
        """设置图书馆存储路径"""
        config = load_config()
        current = config.get("library_path", "")

        path = QFileDialog.getExistingDirectory(
            self, "选择 PDF 图书馆存储路径", current
        )
        if path:
            config["library_path"] = path
            save_config(config)
            QMessageBox.information(
                self, "已设置",
                f"PDF 图书馆路径已设为：\n{path}\n\n新导入的 PDF 将复制到此目录。"
            )

    def _on_item_clicked(self, item: QTreeWidgetItem, col: int):
        """点击列表项"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "pdf":
            path = data.get("path", "")
            if path and os.path.exists(path):
                self.pdf_selected.emit(path)

    def _on_context_menu(self, pos):
        """右键菜单"""
        item = self.tree.itemAt(pos)
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)

        if data and data.get("type") == "pdf":
            path = data.get("path", "")
            # 移动到文件夹
            move_menu = menu.addMenu("移动到文件夹")
            folders = get_library_folders(self._library)
            uncat_action = move_menu.addAction("（无分类）")
            uncat_action.triggered.connect(lambda: self._move_pdf(path, ""))
            move_menu.addSeparator()
            for folder in folders:
                action = move_menu.addAction(folder)
                action.triggered.connect(lambda checked, f=folder: self._move_pdf(path, f))

            menu.addSeparator()
            remove_action = menu.addAction("从库中移除")
            remove_action.triggered.connect(lambda: self._remove_pdf(path))
        elif data and data.get("type") == "folder":
            rename_action = menu.addAction("重命名文件夹")
            rename_action.triggered.connect(lambda: self._rename_folder(data.get("name", "")))
            delete_action = menu.addAction("删除文件夹")
            delete_action.triggered.connect(lambda: self._delete_folder(data.get("name", "")))

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _move_pdf(self, pdf_path: str, folder: str):
        """将 PDF 移动到指定文件夹"""
        library = load_library()
        for item in library:
            if item.get("path") == pdf_path:
                item["folder"] = folder
                break
        save_library(library)
        self._refresh()

    def _remove_pdf(self, pdf_path: str):
        """从图书馆移除 PDF"""
        reply = QMessageBox.question(
            self, "确认", "确定要从论文库中移除此 PDF 吗？\n（不会删除原始文件）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            remove_pdf_from_library(pdf_path)
            self.pdf_removed.emit(pdf_path)
            self._refresh()

    def _rename_folder(self, old_name: str):
        """重命名文件夹"""
        new_name, ok = QInputDialog.getText(self, "重命名文件夹", "新名称：", text=old_name)
        if ok and new_name.strip() and new_name != old_name:
            library = load_library()
            for item in library:
                if item.get("folder") == old_name:
                    item["folder"] = new_name.strip()
            save_library(library)
            self._refresh()

    def _delete_folder(self, folder_name: str):
        """删除文件夹（文件归入未分类）"""
        reply = QMessageBox.question(
            self, "确认", f"确定删除文件夹「{folder_name}」？\n其中的 PDF 将变为未分类。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            library = load_library()
            for item in library:
                if item.get("folder") == folder_name:
                    item["folder"] = ""
            save_library(library)
            self._refresh()
