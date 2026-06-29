"""
PDFasker — AI 论文解读助手
主入口
"""

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from src.app import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PDFasker")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("PDFasker")

    # 高 DPI 支持
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
