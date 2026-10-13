# main.py - 启动入口
import sys
import os
from pathlib import Path

# 添加项目根目录到sys.path，确保能找到各个模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon, QFont
from gui.main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
     # ===== 全局默认字体 =====
    app.setFont(QFont("Microsoft YaHei", 10))

    # 设置图标
    icon_path = Path("icon/Tigo.ico")
    if icon_path.exists():
        app.setwindowIcon(QIcon(str(icon_path)))
        
    window = MainWindow()
    window.show()
    sys.exit(app.exec())