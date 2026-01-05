# 🛡️ Mail Backup (Docker 邮件备份专家)

[![Docker Image Size](https://img.shields.io/docker/image-size/your_dockerhub_username/mail-backup-pro?style=flat-square&logo=docker)](https://hub.docker.com/r/your_dockerhub_username/mail-backup-pro)
[![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/your_username/repo_name/docker-image.yml?style=flat-square&logo=github)](https://github.com/your_username/repo_name/actions)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)

**Mail Backup** 是一个现代化、可视化的服务器数据备份解决方案。它能够定时打包您指定的 Docker 容器数据或任意主机目录，通过 **智能分包** 技术绕过邮件附件大小限制，安全加密并发送到您的邮箱。

再也不用担心服务器数据丢失，也无需复杂的命令行脚本，一切尽在优雅的 Web 面板中掌控。

![Dashboard Screenshot](https://via.placeholder.com/1200x600?text=Dashboard+Preview+Image)
*(建议在此处替换为您实际的面板截图)*

## ✨ 核心特性

*   **🎨 现代化 Web 面板**：基于 FastAPI + TailwindCSS + DaisyUI 构建，提供美观的暗黑模式 UI，操作丝滑。
*   **📦 智能分包发送**：自动将大文件切割为 35MB 的小块，完美绕过 QQ/Gmail 等邮箱 50MB 附件限制。
*   **🧩 傻瓜式恢复**：每次备份的首封邮件会自动附带 `restore_tool.zip`，内含 Windows/Linux 一键合并脚本，双击即可还原数据。
*   **🔒 安全加密**：支持为 ZIP 压缩包设置密码，保障数据在传输过程中的安全。
*   **📂 全盘备份能力**：通过 `/host` 映射技术，容器内可直接备份宿主机的任意目录（如 `/home`, `/etc`, `/var` 等）。
*   **⚡ 灵活调度**：支持标准的 Cron 表达式（如 `0 4 * * *`），精确控制每个任务的备份时间。
*   **🛠️ 热修改任务**：随时调整备份路径、时间或备注，无需重启容器。
*   **🐳 Docker 原生**：通过环境变量管理面板账号，配置即代码，部署简单。

## 🚀 快速部署 (Docker Compose)

### 1. 准备工作
确保您的服务器已安装 Docker 和 Docker Compose。

### 2. 创建 `docker-compose.yml`
在服务器任意目录（如 `/root/docker-mail-backup`）创建文件并写入以下内容：

```yaml
version: '3.8'

services:
  mail-backup:
    image: ghcr.io/workerspages/mail-backup:latest
    container_name: mail-backup
    restart: always
    ports:
      - "8000:8000"
    volumes:
      # 1. 映射宿主机根目录(只读)，以便备份任何文件
      - /:/host:ro
      # 也可以只映射备份目录
      # - /docker/vaultwarden:/docker/vaultwarden
      
      # 2. 数据库持久化(必须，否则重启后任务丢失)
      - ./data:/data
    environment:
      - TZ=Asia/Shanghai
      # --- 面板登录设置 (由此处控制) ---
      - PANEL_USER=admin
      - PANEL_PASSWORD=MySecretPassword2026
```

### 3. 启动服务
```bash
docker-compose up -d
```

### 4. 访问面板
在浏览器输入 `http://您的服务器IP:8000`。
*   **默认账号**: `admin`
*   **默认密码**: `ChangeMe123` (或您在 YAML 中设置的密码)

---

## 📖 使用指南

### 第一步：配置发件邮箱
1.  登录面板后，点击顶部右上角的 **“⚙️ 全局设置”**。
2.  填写 SMTP 信息（以 QQ 邮箱为例）：
    *   **服务器**: `smtp.qq.com`
    *   **端口**: `465`
    *   **发件邮箱**: `123456@qq.com`
    *   **密码/授权码**: 注意是邮箱的 **SMTP 授权码**，不是登录密码。
3.  点击保存。

### 第二步：添加备份任务
点击左侧的 **“➕ 新建备份任务”**。

*   **任务名称**: 给任务起个名字，如 `Vaultwarden`。
*   **容器内路径**: **⚠️ 关键点！**
    *   由于我们挂载了 `/:/host`，如果您想备份宿主机的 `/data/docker_data/web`，
    *   此处必须填写：**`/host/data/docker_data/web`**
*   **Cron 表达式**: 设置备份频率。
    *   每天凌晨 4 点: `0 4 * * *`
    *   每周一凌晨 3 点: `0 3 * * 1`
*   **压缩密码**: 选填，留空则不加密。
*   **接收邮箱**: 选填，留空则发给发件人自己。

### 第三步：数据恢复
当您收到备份邮件时，如果是大文件，可能会收到多封邮件（如 `[1/3]`, `[2/3]`, `[3/3]`）。

1.  **下载** 所有邮件的附件到电脑同一个文件夹。
2.  找到第一封邮件中的 **`restore_tool.zip`** 并解压。
3.  **Windows 用户**: 双击运行 `windows_restore.bat`。
4.  **Linux 用户**: 运行 `bash linux_restore.sh`。
5.  脚本会自动将所有分包（`.001`, `.002`...）合并为一个完整的 `.zip` 文件。
6.  解压该 ZIP 文件（如有密码请输入）即可恢复数据。

---

## ⚙️ 环境变量说明

| 变量名 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `TZ` | `Asia/Shanghai` | 容器时区设置 |
| `PANEL_USER` | `admin` | 面板登录用户名 |
| `PANEL_PASSWORD` | `admin` | 面板登录密码 |

> **⚠️ 注意**：`PANEL_PASSWORD` 的优先级高于面板内的数据库设置。如果在 `docker-compose.yml` 中设置了密码，每次重启容器都会覆盖面板内修改的密码。建议始终通过修改 YAML 文件来管理密码。

---

## 🛠️ 开发与构建

本项目使用 **GitHub Actions** 自动构建并推送到 Docker Hub / GHCR。

### 技术栈
*   **Backend**: Python 3.11, FastAPI, APScheduler, SQLModel (SQLite)
*   **Frontend**: Jinja2 Templates, TailwindCSS, DaisyUI (CDN)
*   **System Tools**: Linux `zip` / `unzip` command

### 本地运行 (开发模式)
```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## ❓ 常见问题 (FAQ)

**Q: 为什么提示 "No such device or address" 错误？**
A: 这通常是因为备份目录中包含了 Socket 文件或损坏的软链接。目前的版本已经加上了 `-y` 参数，zip 会自动处理软链接，通常不会再报错。

**Q: 为什么收到的附件是 `.bin` 格式？**
A: 这是旧版本的 Bug。最新版已经修复了 MIME Header 设置，现在的附件名应该是正常的 `xxx.zip.001`。

**Q: 邮件发送失败？**
A: 请检查：
1. SMTP 授权码是否正确（不是 QQ 登录密码）。
2. 附件是否过大（虽然有分包，但如果单包设置超过 50MB 依然会失败，默认已设为安全的 35MB）。
3. 服务器防火墙是否允许访问 465 端口。

---

## 📄 License

MIT License © 2026 Your Name

---

*如果不喜欢繁琐的运维，这就是你最优雅的备份伴侣。*
