"""
全局 QSS 样式表 —— 暗色主题，优化可读性
"""

STYLESHEET = """
/* ========== 全局 ========== */
QMainWindow {
    background-color: #1a1b26;
}

QWidget {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 14px;
    color: #cfd2e3;
}

/* ========== 滚动区域 ========== */
QScrollArea {
    background-color: #1a1b26;
    border: none;
}

/* ========== 分割器 ========== */
QSplitter::handle {
    background-color: #2a2c3d;
}
QSplitter::handle:horizontal {
    width: 3px;
}
QSplitter::handle:vertical {
    height: 3px;
}

/* ========== 滚动条 ========== */
QScrollBar:vertical {
    background: #1a1b26;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #3b3d54;
    border-radius: 5px;
    min-height: 40px;
}
QScrollBar::handle:vertical:hover {
    background: #515479;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: #1a1b26;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #3b3d54;
    border-radius: 5px;
    min-width: 40px;
}
QScrollBar::handle:horizontal:hover {
    background: #515479;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ========== 按钮 ========== */
QPushButton {
    background-color: #3b3d54;
    color: #cfd2e3;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    font-size: 13px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #515479;
}
QPushButton:pressed {
    background-color: #636688;
}
QPushButton:disabled {
    background-color: #2a2c3d;
    color: #636688;
}
QPushButton#primaryBtn {
    background-color: #7aa2f7;
    color: #1a1b26;
    font-weight: bold;
}
QPushButton#primaryBtn:hover {
    background-color: #a9c8ff;
}

/* ========== 输入框 ========== */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #24253a;
    color: #e2e5f2;
    border: 1px solid #3b3d54;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 14px;
    selection-background-color: #7aa2f7;
    selection-color: #1a1b26;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #7aa2f7;
}

/* ========== 标签 ========== */
QLabel {
    color: #cfd2e3;
}
QLabel#titleLabel {
    font-size: 15px;
    font-weight: bold;
    color: #7aa2f7;
}
QLabel#subtitleLabel {
    font-size: 12px;
    color: #9599b5;
}

/* ========== 组合框 ========== */
QComboBox {
    background-color: #24253a;
    color: #cfd2e3;
    border: 1px solid #3b3d54;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 14px;
}
QComboBox:hover {
    border-color: #7aa2f7;
}
QComboBox QAbstractItemView {
    background-color: #24253a;
    color: #cfd2e3;
    selection-background-color: #3b3d54;
    border: 1px solid #3b3d54;
    outline: none;
}

/* ========== 对话框 ========== */
QDialog {
    background-color: #1a1b26;
}
QGroupBox {
    color: #cfd2e3;
    font-weight: bold;
    border: 1px solid #2a2c3d;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}

/* ========== 提示框 ========== */
QToolTip {
    background-color: #3b3d54;
    color: #cfd2e3;
    border: 1px solid #515479;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}

/* ========== 菜单栏 ========== */
QMenuBar {
    background-color: #161720;
    color: #cfd2e3;
    border-bottom: 1px solid #2a2c3d;
    font-size: 13px;
}
QMenuBar::item:selected {
    background-color: #2a2c3d;
}
QMenu {
    background-color: #24253a;
    color: #cfd2e3;
    border: 1px solid #3b3d54;
}
QMenu::item:selected {
    background-color: #3b3d54;
}

/* ========== 进度条 ========== */
QProgressBar {
    background-color: #24253a;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: #cfd2e3;
    height: 6px;
    font-size: 11px;
}
QProgressBar::chunk {
    background-color: #7aa2f7;
    border-radius: 4px;
}

/* ========== 树形控件 ========== */
QTreeWidget {
    background-color: #1a1b26;
    border: none;
    outline: none;
    font-size: 13px;
}
QTreeWidget::item {
    padding: 6px 10px;
    color: #cfd2e3;
    border-radius: 4px;
}
QTreeWidget::item:hover {
    background-color: #2a2c3d;
}
QTreeWidget::item:selected {
    background-color: #3b3d54;
}
QTreeWidget::branch:has-children:!has-siblings:closed,
QTreeWidget::branch:closed:has-children:has-siblings {
    border-image: none;
}

/* ========== 状态栏 ========== */
QStatusBar {
    background-color: #161720;
    color: #9599b5;
    border-top: 1px solid #2a2c3d;
    font-size: 12px;
}
"""

