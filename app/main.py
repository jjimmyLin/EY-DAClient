"""
main.py
───────
应用入口点。
"""

import sys
from config.settings import settings

# 验证配置
try:
    settings.validate()
except EnvironmentError as e:
    print(f"❌ 配置错误: {e}")
    sys.exit(1)

# 启动 UI
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()