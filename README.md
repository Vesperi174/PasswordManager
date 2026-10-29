# 密码库 · 轻量本地密码管理器

零第三方依赖的桌面密码管理器：Python 标准库 + Tkinter + SQLite。双击 `run.bat` 即可用，
账号密码用主密码加密后保存在本机，不上传任何地方。

## 功能

- **主密码解锁**：忘记无法找回（无后门）。
- **账号 / 邮箱账号** 两种类型分开管理，侧栏可按类型筛选。
- **账号关联**：任意两账号可建立「绑定邮箱 / 主账号 / 子账号 / 恢复邮箱 / 两步验证…」关系，详情页双向展示、点击互跳。
- **邮箱联动**：填邮箱时自动匹配同地址邮箱账号并建立关联；没有时可一键创建邮箱账号并互相绑定。
- **登录网址自动识别**：`@qq.com` → mail.qq.com、`@gmail.com` → mail.google.com 等；不会覆盖手填的网址。
- **账号组**：把 Apex + EA + Steam + 邮箱打包成一行，展开/收起，成员密码各自独立。
- **搜索筛选、收藏、密码生成器**；复制密码 30 秒后自动清除剪贴板；闲置 15 分钟自动锁定。
- **自动加密备份**：解锁和退出时备份到 `%LOCALAPPDATA%\PasswordVault\backups`（保留 10 份），
  数据文件丢失时启动界面可一键恢复。
- **应用内检测更新**：`⋯ → 检测更新…`，在线检查、下载、安装并重启，不用打开 GitHub。

## 快速开始

要求 Python 3.10+（Windows 官方安装包自带 tkinter）。

1. 双击 `run.bat`（无控制台窗口）；或运行 `python app.py`。
2. 首次启动设置主密码（≥8 位，建议 12 位以上并混合大小写、数字、符号）。
3. 点「＋ 新建账号」开始录入，数据保存在 `data/vault.db`。

可选参数：`--data D:\目录` 指定数据目录、`--idle-minutes 5` 调整锁定时间、`--version` 看版本。

## 常用操作

- **关联邮箱**：普通账号填「绑定邮箱」，保存时会提示并自动关联同地址的邮箱账号。
- **登录名就是邮箱**：勾选「账号就是邮箱地址（只同步账号名）」；密码仍各自独立，
  在关联行点「复制密码」可取到对方（邮箱账号）自己的密码。
- **账号组**：`⋯ → 新建账号组…`，勾选成员即可折叠成一行；删除组不会删除账号。
- **检测更新**：`⋯ → 检测更新…` → 有新版就「下载并更新」→「立即重启」。
  更新前自动备份程序文件，失败自动回滚，`data/` 不受影响。

## 安全

| 项目 | 做法 |
| --- | --- |
| 密钥派生 | PBKDF2-HMAC-SHA256，600,000 次迭代 |
| 记录加密 | ChaCha20-Poly1305（RFC 8439），逐条加密；标题、邮箱、备注、组名均不落明文 |
| 主密码 | 从不保存；连续输错 5 次后逐步冷却 |
| 备份 | 自动/手动备份都是加密后的 `.db` |

局限：不防本机内存读取、键盘记录等系统级攻击；导出的 JSON 备份是明文。

## 备份与恢复

- 自动：解锁/退出时备份到 `%LOCALAPPDATA%\PasswordVault\backups`，保留最近 10 份，位于项目目录之外。
- 手动：`⋯ → 备份加密副本…` / 「从备份恢复…」（恢复时需要该备份的主密码）。
- 换电脑：拷走 `data/` 目录即可，主密码不变。

## 目录结构

```
app.py / run.bat / version.json / requirements.txt
pm/     crypto.py  store.py  update.py  util.py  ui_kit.py  gui_app.py  gui_dialogs.py
tools/  selftest.py  store_test.py  gui_test.py
data/   vault.db（运行后自动生成）
```

## 自检 / 打包

```bat
python tools\selftest.py   :: 加密向量（RFC 8439）
python tools\store_test.py :: 数据层（含磁盘无明文、升级与备份）
python tools\gui_test.py   :: 界面交互（真实窗口驱动）

:: 可选：打包成单个 exe（数据存 exe 同级 data\）
pip install pyinstaller && pyinstaller --noconsole --onefile --name 密码库 app.py
```

## 在线更新说明

更新源是 main 分支的 `version.json`（`download_url` 指向 main 归档压缩包）。
发布新版本只需改 `pm/__init__.py` 的版本号 + `version.json` 并 push 到 main，
旧版本用户在应用内即可升级，**不需要 tag 或 Release**。
