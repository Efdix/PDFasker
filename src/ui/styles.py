"""
全局 QSS 样式表 —— Catppuccin 暗色主题，专注可读性与交互反馈
"""

STYLESHEET = """
/* ============================================================
   全局基础
   ============================================================ */
QMainWindow {
    background-color: #1a1b26;
}

QWidget {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 14px;
    color: #cfd2e3;
}

/* ============================================================
   滚动区域
   ============================================================ */
QScrollArea {
    background-color: #1a1b26;
    border: none;
}

/* ============================================================
   分割器
   ============================================================ */
QSplitter::handle {
    background-color: #313244;
}
QSplitter::handle:horizontal {
    width: 3px;
}
QSplitter::handle:vertical {
    height: 3px;
}
QSplitter::handle:hover {
    background-color: #7aa2f7;
}

/* ============================================================
   滚动条 —— 细窄、圆角、hover 高亮
   ============================================================ */
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px 0;
}
QScrollBar::handle:vertical {
    background: #3b3d54;
    border-radius: 4px;
    min-height: 36px;
}
QScrollBar::handle:vertical:hover {
    background: #7aa2f7;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 0 2px;
}
QScrollBar::handle:horizontal {
    background: #3b3d54;
    border-radius: 4px;
    min-width: 36px;
}
QScrollBar::handle:horizontal:hover {
    background: #7aa2f7;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ============================================================
   按钮 —— 层次分明 + 按动反馈（padding 位移模拟下压）
   ============================================================ */
QPushButton {
    background-color: #3b3d54;
    color: #cfd2e3;
    border: none;
    border-radius: 6px;
    padding: 7px 14px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #515479;
}
QPushButton:pressed {
    background-color: #636688;
    padding: 8px 13px 6px 15px;
}
QPushButton:disabled {
    background-color: #252636;
    color: #56586f;
}

/* 主要操作按钮 */
QPushButton#primaryBtn {
    background-color: #7aa2f7;
    color: #1a1b26;
    font-weight: 700;
}
QPushButton#primaryBtn:hover {
    background-color: #89b4fa;
}
QPushButton#primaryBtn:pressed {
    background-color: #6c91dd;
    padding: 8px 13px 6px 15px;
}
QPushButton#primaryBtn:disabled {
    background-color: #3b3d54;
    color: #636688;
}

/* 成功/确认风格 */
QPushButton#successBtn {
    background-color: #9ece6a;
    color: #1a1b26;
    font-weight: 700;
}
QPushButton#successBtn:hover {
    background-color: #b3de82;
}

/* 危险/警告风格 */
QPushButton#dangerBtn {
    background-color: #f7768e;
    color: #1a1b26;
    font-weight: 700;
}
QPushButton#dangerBtn:hover {
    background-color: #ff91a5;
}

/* ============================================================
   复选框
   ============================================================ */
QCheckBox {
    color: #9599b5;
    font-size: 12px;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #3b3d54;
    border-radius: 4px;
    background: #1e2030;
}
QCheckBox::indicator:hover {
    border-color: #7aa2f7;
}
QCheckBox::indicator:checked {
    border-color: #7aa2f7;
    background: #7aa2f7;
}

/* ============================================================
   输入框 —— 聚焦环形光晕效果
   ============================================================ */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #24253a;
    color: #e2e5f2;
    border: 1px solid #3b3d54;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 14px;
    line-height: 1.6;
    selection-background-color: #7aa2f7;
    selection-color: #1a1b26;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #7aa2f7;
    background-color: #252740;
}

/* ============================================================
   标签 —— 语义化角色
   ============================================================ */
QLabel {
    color: #cfd2e3;
    line-height: 1.5;
}
QLabel#titleLabel {
    font-size: 16px;
    font-weight: 700;
    color: #c4d3ff;
    letter-spacing: 0.3px;
}
QLabel#subtitleLabel {
    font-size: 12px;
    color: #8a8ea6;
}
QLabel#sectionLabel {
    font-size: 13px;
    font-weight: 600;
    color: #a9b1d6;
}

/* ============================================================
   组合框
   ============================================================ */
QComboBox {
    background-color: #24253a;
    color: #cfd2e3;
    border: 1px solid #3b3d54;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 14px;
    combobox-popup: 1;
}
QComboBox:hover {
    border-color: #7aa2f7;
}
QComboBox:focus {
    border-color: #7aa2f7;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #8a8ea6;
    margin-right: 6px;
}
QComboBox QAbstractItemView {
    background-color: #24253a;
    color: #cfd2e3;
    selection-background-color: #3b3d54;
    selection-color: #e2e5f2;
    border: 1px solid #3b3d54;
    border-radius: 4px;
    outline: none;
    padding: 4px;
}
QComboBox QAbstractItemView::item {
    padding: 6px 10px;
    border-radius: 3px;
}
QComboBox QAbstractItemView::item:hover {
    background-color: #2a2c3d;
}

/* ============================================================
   标签页
   ============================================================ */
QTabWidget::pane {
    border: none;
    background-color: #1a1b26;
}
QTabBar::tab {
    padding: 8px 24px;
    font-size: 14px;
    font-weight: 600;
    background: #1a1b26;
    color: #8a8ea6;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
}
QTabBar::tab:selected {
    color: #7aa2f7;
    border-bottom: 2px solid #7aa2f7;
}
QTabBar::tab:hover:!selected {
    color: #cfd2e3;
    background-color: #24253a;
}

/* ============================================================
   对话框 / 分组框
   ============================================================ */
QDialog {
    background-color: #1a1b26;
}
QGroupBox {
    color: #cfd2e3;
    font-weight: 600;
    font-size: 13px;
    border: 1px solid #313244;
    border-radius: 8px;
    margin-top: 14px;
    padding: 18px 12px 12px 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: #a9b1d6;
}

/* ============================================================
   工具提示
   ============================================================ */
QToolTip {
    background-color: #3b3d54;
    color: #e2e5f2;
    border: 1px solid #515479;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 12px;
    line-height: 1.4;
}

/* ============================================================
   菜单栏
   ============================================================ */
QMenuBar {
    background-color: #161720;
    color: #cfd2e3;
    border-bottom: 1px solid #313244;
    font-size: 13px;
    padding: 2px 0;
}
QMenuBar::item {
    padding: 4px 10px;
    border-radius: 4px;
}
QMenuBar::item:selected {
    background-color: #313244;
}
QMenu {
    background-color: #24253a;
    color: #cfd2e3;
    border: 1px solid #3b3d54;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 28px 6px 14px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #3b3d54;
}

/* ============================================================
   进度条
   ============================================================ */
QProgressBar {
    background-color: #252636;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: transparent;
    height: 6px;
}
QProgressBar::chunk {
    background-color: #7aa2f7;
    border-radius: 4px;
}

/* ============================================================
   树形控件（论文库）
   ============================================================ */
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
    min-height: 24px;
}
QTreeWidget::item:hover {
    background-color: #2a2c3d;
}
QTreeWidget::item:selected {
    background-color: #3b3d54;
    color: #e2e5f2;
}

/* ============================================================
   列表控件
   ============================================================ */
QListWidget {
    background-color: #1a1b26;
    border: none;
    outline: none;
    font-size: 13px;
}
QListWidget::item {
    padding: 6px 10px;
    border-radius: 4px;
}
QListWidget::item:hover {
    background-color: #2a2c3d;
}
QListWidget::item:selected {
    background-color: #3b3d54;
    color: #e2e5f2;
}

/* ============================================================
   状态栏
   ============================================================ */
QStatusBar {
    background-color: #161720;
    color: #8a8ea6;
    border-top: 1px solid #313244;
    font-size: 12px;
    padding: 2px 8px;
}

/* ============================================================
   卡片类容器（悬停微亮）
   ============================================================ */
ParagraphCard {
    background-color: #1a1b26;
    border: 1px solid #2a2c3d;
    border-radius: 10px;
    margin: 4px 0px;
}
ParagraphCard:hover {
    border-color: #3b3d54;
}

ClaimResultCard {
    background-color: #1a1b26;
    border: 1px solid #2a2c3d;
    border-radius: 10px;
    margin: 4px 0px;
}
ClaimResultCard:hover {
    border-color: #3b3d54;
}

ImageCard {
    background-color: #1a1b26;
    border: 1px solid #2a2c3d;
    border-radius: 10px;
    margin: 6px 12px;
}
ImageCard:hover {
    border-color: #4a4d6a;
}

/* ============================================================
   消息框按钮区域
   ============================================================ */
QMessageBox {
    background-color: #1a1b26;
}
QMessageBox QLabel {
    color: #cfd2e3;
    font-size: 13px;
    line-height: 1.6;
}
"""

