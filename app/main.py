"""
main.py
───────
应用入口点。
"""

import sys

# ─────────────────────────────────────────────────────────────────
# Worker 模式（PyInstaller 官方推荐的子进程方案）
# ─────────────────────────────────────────────────────────────────
# 打包成 .exe 后，sys.executable 指向应用自身而非 Python 解释器。
# core/executor.py 会以 `<exe> --run-script <脚本>` 的形式调用本程序，
# 这里在加载 Qt / 配置之前拦截该调用，直接执行分析脚本然后退出，
# 从而避免重新启动整个 GUI（即“发送后应用关闭又重开”的根因）。
# 必须放在 `from config.settings import settings` 之前，
# 这样 worker 进程无需任何 API key 即可运行。
if len(sys.argv) >= 3 and sys.argv[1] == "--run-script":
    with open(sys.argv[2], encoding="utf-8") as _f:
        _src = _f.read()
    exec(compile(_src, sys.argv[2], "exec"), {"__name__": "__main__"})
    raise SystemExit(0)

import multiprocessing

# 防御性：multiprocessing 在冻结环境下需要它；从源码运行时为无操作。
multiprocessing.freeze_support()

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