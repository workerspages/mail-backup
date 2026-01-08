import os
import smtplib
import datetime
import subprocess
import zipfile
import socket
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

class BackupManager:
    def __init__(self, smtp_config: dict, task_config: dict):
        """
        初始化备份管理器
        :param smtp_config: 包含 server, port, user, password
        :param task_config: 包含 path, subject, to_email, zip_password, name
        """
        self.smtp = smtp_config
        self.task = task_config
        
        # 固定配置
        self.backup_dir = "/tmp"
        # 排除列表 (支持通配符模式由 zip 命令处理)
        self.excludes = ["icon_cache", "trash", "sends", "*.sock", "mysql.sock", "__pycache__"]
        # 分包大小: 45MB (QQ邮箱附件为50M)
        self.chunk_size = 45 * 1024 * 1024

    def log(self, message):
        print(f"[{self.task.get('name', 'Task')}] {message}")

    def run(self):
        """执行备份的主入口"""
        temp_files = []
        try:
            self.log("任务开始...")
            
            # 1. 准备路径和文件名
            source_path = self.task['path']
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = "backup_"
            zip_name = f"{prefix}{timestamp}.zip"
            zip_path = os.path.join(self.backup_dir, zip_name)

            # 2. 压缩
            output = self._zip_dir(source_path, zip_path)
            if not output: 
                return False
            temp_files.append(output)

            # 3. 切割 (如果文件过大)
            parts = self._split_file(output)
            # 将生成的分包文件加入清理列表
            for p in parts:
                if p not in temp_files:
                    temp_files.append(p)

            # 4. 生成恢复工具 (如果进行了分包)
            restore_tool = None
            if len(parts) > 1:
                restore_tool, script_files = self._create_restore_scripts(parts)
                temp_files.extend(script_files)

            # 5. 发送邮件
            self._send_email(parts, restore_tool)
            self.log("任务执行成功")
            return True

        except Exception as e:
            self.log(f"执行失败: {e}")
            traceback.print_exc()
            return False
        finally:
            # 6. 清理临时文件
            self._cleanup(temp_files)

    def _cleanup(self, files):
        """清理临时文件"""
        for f in files:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception as e:
                self.log(f"清理临时文件失败 {f}: {e}")

    def _zip_dir(self, source, output):
        """调用系统 zip 命令压缩"""
        # 路径标准化
        source = os.path.normpath(source)
        if not os.path.exists(source):
            self.log(f"错误: 源目录不存在 -> {source}")
            return None
        
        # 切换到源目录的父目录执行，以保持相对路径结构
        parent_dir = os.path.dirname(source)
        base_name = os.path.basename(source)
        
        # 构建命令: zip -r -q -y ...
        cmd = ["zip", "-r", "-q", "-y"]
        
        # 密码处理
        pwd = self.task.get('zip_password')
        if pwd and pwd.strip():
            cmd.extend(["-P", pwd.strip()])

        cmd.append(output)
        cmd.append(base_name)
        
        # 排除项
        if self.excludes:
            for ex in self.excludes:
                cmd.extend(["-x", f"{base_name}/{ex}/*"])

        try:
            # 调用系统命令
            result = subprocess.run(
                cmd, 
                cwd=parent_dir, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                text=True
            )
            
            # exit code 18 是文件读取警告(如socket)，通常可忽略
            if result.returncode != 0 and result.returncode != 18:
                self.log(f"Zip 命令报错: {result.stderr}")
                return None
            
            if not os.path.exists(output):
                self.log("压缩命令执行完成但文件未生成")
                return None
                
            return output
        except Exception as e:
            self.log(f"压缩过程异常: {e}")
            return None

    def _split_file(self, file_path):
        """物理切割大文件"""
        file_size = os.path.getsize(file_path)
        if file_size <= self.chunk_size:
            return [file_path]
        
        self.log(f"文件大小 ({file_size/1024/1024:.2f}MB) 超过限制，正在切割...")
        parts = []
        part_num = 1
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(self.chunk_size)
                if not chunk: break
                pname = f"{file_path}.{part_num:03d}"
                with open(pname, 'wb') as cf:
                    cf.write(chunk)
                parts.append(pname)
                part_num += 1
        return parts

    def _create_restore_scripts(self, parts):
        """生成 Windows/Linux 恢复脚本"""
        base_names = [os.path.basename(p) for p in parts]
        
        # Windows .bat
        bat_path = os.path.join(self.backup_dir, "windows_restore.bat")
        with open(bat_path, "w", encoding="gbk") as f:
            f.write("@echo off\n")
            f.write("echo 正在合并文件...\n")
            files_str = " + ".join(base_names)
            f.write(f'copy /b {files_str} "full_restored.zip"\n')
            f.write("echo 合并完成\n")
            f.write("pause\n")
        
        # Linux .sh
        sh_path = os.path.join(self.backup_dir, "linux_restore.sh")
        with open(sh_path, "w", encoding="utf-8") as f:
            f.write("#!/bin/bash\n")
            files_str = " ".join(base_names)
            f.write(f'cat {files_str} > full_restored.zip\n')
            f.write('echo "Done."\n')
        
        # 打包脚本
        tool_zip = os.path.join(self.backup_dir, "restore_tool.zip")
        with zipfile.ZipFile(tool_zip, 'w') as zf:
            zf.write(bat_path, "windows_restore.bat")
            zf.write(sh_path, "linux_restore.sh")
            
        return tool_zip, [bat_path, sh_path, tool_zip]

    def _send_email(self, files, tool_path):
        """智能分批发送邮件"""
        batches = []
        current_batch = []
        current_batch_size = 0
        limit = self.chunk_size # 35MB

        # 分组逻辑
        for f in files:
            s = os.path.getsize(f)
            if current_batch_size + s > limit:
                if current_batch: batches.append(current_batch)
                current_batch = [f]
                current_batch_size = s
            else:
                current_batch.append(f)
                current_batch_size += s
        if current_batch: batches.append(current_batch)

        total_emails = len(batches)
        self.log(f"准备发送 {total_emails} 封邮件...")

        for i, batch in enumerate(batches):
            index = i + 1
            msg = MIMEMultipart()
            msg['From'] = self.smtp['user']
            # 如果没填接收人，默认发给自己
            to_addr = self.task.get('to_email')
            if not to_addr:
                to_addr = self.smtp['user']
            msg['To'] = to_addr
            
            # 标题
            subject_base = self.task.get('subject', 'Backup')
            date_str = datetime.date.today().strftime('%Y-%m-%d')
            if total_emails > 1:
                msg['Subject'] = f"{subject_base} [{index}/{total_emails}] - {date_str}"
            else:
                msg['Subject'] = f"{subject_base} - {date_str}"

            # 正文
            body = f"任务: {self.task['name']}\n主机: {socket.gethostname()}\n时间: {datetime.datetime.now()}"
            if total_emails > 1 and index == 1:
                body += "\n\n【提示】附件包含分包文件，请下载所有邮件附件并解压 'restore_tool.zip' 进行合并。"
            
            msg.attach(MIMEText(body, 'plain'))

            # 第一封邮件附带工具
            if index == 1 and tool_path and total_emails > 1:
                batch.insert(0, tool_path)

            # 添加附件
            for fp in batch:
                try:
                    ctype = 'application/octet-stream'
                    with open(fp, "rb") as f:
                        part = MIMEBase(*ctype.split('/'))
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    
                    # 修复 bin 文件问题
                    filename = os.path.basename(fp)
                    part.add_header('Content-Disposition', 'attachment', filename=filename)
                    msg.attach(part)
                except Exception as e:
                    self.log(f"附件添加错误: {e}")

            # 发送动作
            try:
                # SSL 发送
                server = smtplib.SMTP_SSL(self.smtp['server'], int(self.smtp['port']))
                server.login(self.smtp['user'], self.smtp['password'])
                server.sendmail(self.smtp['user'], to_addr, msg.as_string())
                server.quit()
                self.log(f"第 {index} 封邮件发送成功")
            except Exception as e:
                self.log(f"邮件发送失败: {e}")
                # 抛出异常以便外层捕获
                raise e
