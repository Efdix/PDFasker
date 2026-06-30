"""PDFasker — AI 论文解读助手，主入口模块。"""

import sys

from PySide6.QtWidgets import QApplication

from src.app import MainWindow


def main() -> None:
    """应用程序入口：创建 QApplication 并启动主窗口。"""
    app = QApplication(sys.argv)
    app.setApplicationName("PDFasker")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("PDFasker")
    app.setStyle("Fusion")  # 跨平台一致的暗色主题基础

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
