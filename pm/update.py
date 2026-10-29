"""在线更新：检查新版本、下载并替换程序文件（保留 data/）。

服务端约定：仓库根目录放一个 ``version.json``::

    {
      "version": "1.1.0",
      "released_at": "2026-10-28",
      "download_url": "https://github.com/<user>/<repo>/archive/refs/tags/v1.1.0.zip",
      "notes": ["本次更新内容……", "……"]
    }

应用启动后（或点「检测更新」时）拉取它，比较版本号；发现新版本就下载 zip，
解压后只替换程序文件（app.py / pm / tools / 文档等），**绝不触碰 data/ 数据目录**。
替换前会先把当前程序文件打包备份到 ``data/backups/update-backup-*.zip``，
替换失败会自动回滚。

注意：更新包来自官方仓库的 HTTPS 下载地址，属于"信任源"更新；
主密码与账号数据全部在本地 data/ 里，不会被上传。
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from . import __version__

#: 版本信息的多个来源，按顺序尝试（raw 最快；API 作为兜底；raw 重定向地址再兜底）
MANIFEST_SOURCES = (
    "https://raw.githubusercontent.com/Vesperi174/PasswordManager/main/version.json",
    "https://api.github.com/repos/Vesperi174/PasswordManager/contents/version.json",
    "https://github.com/Vesperi174/PasswordManager/raw/main/version.json",
)

USER_AGENT = f"PasswordManager/{__version__}"

#: 更新时绝不覆盖/备份的内容（数据、版本库、临时目录）
IGNORED_NAMES = {
    "data",
    ".git",
    ".tmp",
    ".venv",
    "venv",
    "build",
    "dist",
    "node_modules",
    "__pycache__",
}

#: 允许删除"新版本里已不存在"的旧文件的目录（避免误删用户自己的文件）
MANAGED_DIRS = ("pm", "tools")


def parse_version(text: str) -> tuple[int, ...]:
    """把 ``1.1.0`` / ``v1.1.0`` / ``1.1.0-beta`` 解析成可比较的数字元组。"""
    parts: list[int] = []
    for piece in re.split(r"[.+\-]", str(text or "").strip().lstrip("vV")):
        piece = piece.strip()
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts) or (0,)


def is_newer(remote_version: str, current_version: str = __version__) -> bool:
    return parse_version(remote_version) > parse_version(current_version)


def app_dir() -> Path:
    """程序所在目录（打包成 exe 时为 exe 所在目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _load_manifest_payload(payload: str) -> dict:
    """解析版本信息；兼容 GitHub API contents 返回的 base64 外壳。"""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict) and data.get("encoding") == "base64" and data.get("content"):
        data = json.loads(base64.b64decode(data["content"]).decode("utf-8"))
    if not isinstance(data, dict) or not data.get("version"):
        raise ValueError("更新信息格式不正确")
    if not data.get("download_url"):
        raise ValueError("更新信息缺少下载地址")
    return data


def _fetch_manifest_once(url: str, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github.raw+json, application/json, */*",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    return _load_manifest_payload(payload)


def fetch_manifest(url: str | None = None, timeout: float = 15.0) -> dict:
    """读取最新版本信息。

    * ``url`` 为空时按 :data:`MANIFEST_SOURCES` 顺序尝试多个地址（raw → API → 网页 raw），
      任一成功即可，避免某个域名被墙/被代理拦截导致无法检测更新；
    * 单独传入 ``url`` 时只尝试该地址。
    """
    sources = (url,) if url else MANIFEST_SOURCES
    last_error: Exception | None = None
    for source in sources:
        try:
            return _fetch_manifest_once(source, timeout)
        except Exception as exc:  # noqa: BLE001 - 换下一个来源继续尝试
            last_error = exc
    raise RuntimeError(f"无法获取更新信息：{last_error}") from last_error


def download_zip(url: str, dest: Path, *, timeout: float = 120.0, progress=None) -> Path:
    """下载更新包到 ``dest``；``progress`` 会以 0~1 的比例被回调。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response, open(dest, "wb") as target:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            target.write(chunk)
            received += len(chunk)
            if progress is not None and total > 0:
                progress(min(1.0, received / total))
    return dest


def _zip_root(names: list[str]) -> str:
    """GitHub archive 的 zip 有一个顶层目录，返回它。"""
    first = names[0]
    return first.split("/", 1)[0]


def backup_program_files(app_dir_path: Path | None = None) -> Path:
    """把当前程序文件打包备份到 ``data/backups/update-backup-*.zip``。"""
    base = Path(app_dir_path or app_dir())
    backup_dir = base / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"update-backup-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(base.iterdir()):
            if item.name in IGNORED_NAMES:
                continue
            if item.is_file():
                archive.write(item, item.name)
                continue
            for path in item.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    archive.write(path, path.relative_to(base).as_posix())
    return target


def restore_program_files(backup_path: Path, app_dir_path: Path | None = None) -> None:
    """用备份 zip 覆盖回程序文件（回滚用）。"""
    base = Path(app_dir_path or app_dir())
    with zipfile.ZipFile(backup_path) as archive:
        archive.extractall(base)


def apply_update(zip_path: Path, app_dir_path: Path | None = None) -> Path:
    """用更新包替换程序文件，返回备份 zip 路径；失败会自动回滚并抛出异常。"""
    base = Path(app_dir_path or app_dir())
    zip_path = Path(zip_path)
    backup = backup_program_files(base)

    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = [name for name in archive.namelist() if name and not name.endswith("/")]
            if not names:
                raise ValueError("更新包是空的")
            root = _zip_root(names) + "/"
            members = [name for name in names if name.startswith(root)]
            if not members:
                raise ValueError("更新包结构不正确（缺少顶层目录）")

            plan: list[tuple[str, str]] = []
            new_paths: set[str] = set()
            for name in members:
                relative = name[len(root):]
                if not relative:
                    continue
                top = relative.split("/", 1)[0]
                if top in IGNORED_NAMES or "__pycache__" in relative.split("/"):
                    continue
                new_paths.add(relative)
                plan.append((name, relative))

            # 清理旧版本里已经被删除的源文件（只处理受管目录）
            for managed in MANAGED_DIRS:
                directory = base / managed
                if not directory.is_dir():
                    continue
                for path in directory.rglob("*"):
                    if path.is_file():
                        relative = path.relative_to(base).as_posix()
                        if relative not in new_paths:
                            try:
                                path.unlink()
                            except OSError:
                                pass
                for path in sorted(
                    (p for p in directory.rglob("*") if p.is_dir()),
                    key=lambda p: len(p.parts),
                    reverse=True,
                ):
                    try:
                        if not any(path.iterdir()):
                            path.rmdir()
                    except OSError:
                        pass

            for name, relative in plan:
                target = base / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, open(target, "wb") as destination:
                    shutil.copyfileobj(source, destination)
    except Exception:
        try:
            restore_program_files(backup, base)
        except Exception:  # noqa: BLE001 - 回滚失败时至少保留异常信息
            pass
        raise

    return backup


def restart_app() -> None:
    """启动一个新实例后由调用方退出当前进程。"""
    if getattr(sys, "frozen", False):
        command = [sys.executable, *sys.argv[1:]]
        cwd = str(Path(sys.executable).resolve().parent)
    else:
        command = [sys.executable, str(app_dir() / "app.py"), *sys.argv[1:]]
        cwd = str(app_dir())
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        subprocess.Popen(command, cwd=cwd, close_fds=True, creationflags=flags)
    else:
        subprocess.Popen(command, cwd=cwd, close_fds=True, start_new_session=True)
