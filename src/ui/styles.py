"""
全局 QSS 样式表 —— 现代简洁风格
"""

STYLESHEET = """
/* ========== 全局 ========== */
QMainWindow {
    background-color: #1e1e2e;
}

QWidget {
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
    color: #cdd6f4;
}

/* ========== 分割器 ========== */
QSplitter::handle {
    background-color: #313244;
    width: 2px;
}

QSplitter::handle:hover {
    background-color: #89b4fa;
}

/* ========== 滚动条 ========== */
QScrollBar:vertical {
    background: #1e1e2e;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #585b70;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: #1e1e2e;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background: #45475a;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: #585b70;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ========== 按钮 ========== */
QPushButton {
    background-color: #45475a;
    color: #cdd6f4;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #585b70;
}
QPushButton:pressed {
    background-color: #6c7086;
}
QPushButton:disabled {
    background-color: #313244;
    color: #6c7086;
}

QPushButton#primaryBtn {
    background-color: #89b4fa;
    color: #1e1e2e;
}
QPushButton#primaryBtn:hover {
    background-color: #b4d0fb;
}

QPushButton#dangerBtn {
    background-color: #f38ba8;
    color: #1e1e2e;
}
QPushButton#dangerBtn:hover {
    background-color: #f5a8bd;
}

/* ========== 输入框 ========== */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #89b4fa;
}

/* ========== 标签页 ========== */
QTabWidget::pane {
    border: 1px solid #45475a;
    background-color: #1e1e2e;
    border-radius: 6px;
}
QTabBar::tab {
    background-color: #313244;
    color: #a6adc8;
    padding: 8px 20px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #45475a;
    color: #cdd6f4;
}
QTabBar::tab:hover {
    background-color: #45475a;
}

/* ========== 标签 ========== */
QLabel {
    color: #cdd6f4;
}
QLabel#titleLabel {
    font-size: 16px;
    font-weight: bold;
    color: #89b4fa;
}
QLabel#subtitleLabel {
    font-size: 12px;
    color: #a6adc8;
}
QLabel#errorLabel {
    color: #f38ba8;
    font-weight: bold;
}

/* ========== 组合框 ========== */
QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 10px;
}
QComboBox:hover {
    border-color: #89b4fa;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #45475a;
    border: 1px solid #45475a;
}

/* ========== 对话框 ========== */
QDialog {
    background-color: #1e1e2e;
}

/* ========== 提示框 ========== */
QToolTip {
    background-color: #45475a;
    color: #cdd6f4;
    border: 1px solid #585b70;
    border-radius: 4px;
    padding: 4px;
}

/* ========== 菜单栏 ========== */
QMenuBar {
    background-color: #181825;
    color: #cdd6f4;
    border-bottom: 1px solid #313244;
}
QMenuBar::item:selected {
    background-color: #45475a;
}
QMenu {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
}
QMenu::item:selected {
    background-color: #45475a;
}

/* ========== 进度条 ========== */
QProgressBar {
    background-color: #313244;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: #cdd6f4;
}
QProgressBar::chunk {
    background-color: #89b4fa;
    border-radius: 4px;
}
"""
