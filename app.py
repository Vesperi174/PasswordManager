#!/usr/bin/env python3
"""密码库 —— 轻量本地密码管理器（桌面客户端，Tkinter）。

用法::

    python app.py                      # 打开窗口，数据默认保存在 ./data/vault.db
    python app.py --data D:\\vault      # 指定数据目录
    python app.py --idle-minutes 5     # 闲置 5 分钟自动锁定

只依赖 Python 标准库（含 tkinter），无需 pip 安装任何第三方包。
"""

from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path

def _app_dir() -> Path:
    """程序所在目录。

    * 源码运行：脚本所在目录；
    * 用 PyInstaller 之类打包成 exe 后：``__file__`` 指向解压出的临时目录，
      临时目录退出即删除，数据会随之丢失。因此这里改用 ``sys.executable``（exe 本身）
      所在目录，保证打包后 data/ 仍然稳定。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = _app_dir()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pm import __version__  # noqa: E402
from pm.gui_app import PasswordVaultApp  # noqa: E402


def _enable_dpi_awareness() -> None:
    """Windows 高分屏下避免界面发虚。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - 非 Windows 或旧系统直接忽略
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="轻量本地密码管理器（桌面客户端，零第三方依赖）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data",
        default=str(BASE_DIR / "data"),
        help="数据目录，密码库文件为其中的 vault.db",
    )
    parser.add_argument(
        "--idle-minutes", type=float, default=15.0, help="闲置多少分钟后自动锁定"
    )
    parser.add_argument(
        "--backup-dir",
        default=None,
        help="加密备份目录（默认 %%LOCALAPPDATA%%\\PasswordVault\\backups，故意放在项目目录之外）",
    )
    parser.add_argument("--version", action="version", version=f"密码库 {__version__}")
    args = parser.parse_args(argv)

    db_path = Path(args.data).expanduser().resolve() / "vault.db"
    backup_dir = Path(args.backup_dir).expanduser().resolve() if args.backup_dir else None
    _enable_dpi_awareness()

    try:
        app = PasswordVaultApp(db_path, idle_minutes=args.idle_minutes, backup_dir=backup_dir)
    except Exception as exc:  # noqa: BLE001 - 启动失败要给用户看得懂的提示
        try:
            from tkinter import messagebox

            messagebox.showerror("密码库", f"启动失败：{exc}")
        except Exception:  # noqa: BLE001
            pass
        raise

    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
