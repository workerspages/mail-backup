import os
import datetime
from typing import Optional, List

from fastapi import FastAPI, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Field, Session, create_engine, select
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import uvicorn

# 引入备份核心逻辑 (确保 app/backup_core.py 文件存在)
from app.backup_core import BackupManager

# --- 数据库模型 ---

class Settings(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    # SMTP 配置
    smtp_server: str = "smtp.qq.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    # 面板登录配置
    admin_user: str = "admin"
    admin_password: str = "admin"

class BackupTask(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    path: str
    cron: str  # e.g., "0 4 * * *"
    subject: str
    to_email: Optional[str] = None
    zip_password: Optional[str] = None
    last_run: Optional[str] = "从未"
    status: Optional[str] = "待机"

# --- 初始化 ---

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

# 数据库初始化 (持久化存储在 /data 目录)
sqlite_file_name = "/data/database.db"
if not os.path.exists("/data"):
    os.makedirs("/data")
sqlite_url = f"sqlite:///{sqlite_file_name}"

# check_same_thread=False 是 SQLite 在多线程(FastAPI)环境下的必要参数
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

# 创建表结构
SQLModel.metadata.create_all(engine)

# 调度器初始化
scheduler = BackgroundScheduler()
scheduler.start()

# --- 辅助函数 ---

def get_session():
    with Session(engine) as session:
        yield session

def verify_auth(request: Request):
    """简单的 Cookie 验证"""
    token = request.cookies.get("auth_token")
    if not token:
        return False
    return True

def get_settings(session: Session):
    """
    获取设置。
    逻辑：
    1. 获取数据库记录。
    2. 检查环境变量 PANEL_USER 和 PANEL_PASSWORD。
    3. 如果环境变量存在且与数据库不一致，优先使用环境变量并更新数据库。
    """
    s = session.exec(select(Settings)).first()
    
    # 环境变量 (来自 docker-compose.yml)
    env_user = os.getenv("PANEL_USER")
    env_pass = os.getenv("PANEL_PASSWORD")

    if not s:
        # 初始化默认配置
        s = Settings()
        if env_user: s.admin_user = env_user
        if env_pass: s.admin_password = env_pass
        session.add(s)
        session.commit()
        session.refresh(s)
    else:
        # 同步环境变量到数据库
        changed = False
        if env_user and s.admin_user != env_user:
            s.admin_user = env_user
            changed = True
        if env_pass and s.admin_password != env_pass:
            s.admin_password = env_pass
            changed = True
        
        if changed:
            print(f"System: 检测到环境变量变更，已更新面板账号/密码。")
            session.add(s)
            session.commit()
            session.refresh(s)
            
    return s

def run_backup_job(task_id: int):
    """调度器调用的实际执行函数"""
    # 每次执行任务时重新创建 Session
    with Session(engine) as session:
        task = session.get(BackupTask, task_id)
        settings = get_settings(session)
        
        if not task:
            return

        print(f"Scheduler: 开始执行任务 [{task.name}]")

        # 更新状态为运行中
        task.status = "运行中..."
        session.add(task)
        session.commit()
        session.refresh(task)

        # 准备配置
        smtp_conf = {
            "server": settings.smtp_server,
            "port": settings.smtp_port,
            "user": settings.smtp_user,
            "password": settings.smtp_password
        }
        task_conf = task.dict()
        
        # 执行备份逻辑
        try:
            manager = BackupManager(smtp_conf, task_conf)
            success = manager.run()
            task.status = "成功" if success else "失败"
        except Exception as e:
            print(f"Scheduler Error: {e}")
            task.status = "异常"
        
        # 更新最后运行时间
        task.last_run = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session.add(task)
        session.commit()

def refresh_scheduler():
    """根据数据库重置所有定时任务"""
    scheduler.remove_all_jobs()
    with Session(engine) as session:
        tasks = session.exec(select(BackupTask)).all()
        print(f"Scheduler: 正在重新加载 {len(tasks)} 个定时任务...")
        for task in tasks:
            try:
                # 使用 task.id 作为 job_id，防止重复
                scheduler.add_job(
                    run_backup_job, 
                    CronTrigger.from_crontab(task.cron), 
                    args=[task.id], 
                    id=str(task.id),
                    replace_existing=True
                )
            except Exception as e:
                print(f"Cron Error for task {task.name}: {e}")

# 应用启动时加载任务
refresh_scheduler()

# --- 路由定义 ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: Session = Depends(get_session)):
    if not verify_auth(request):
        return RedirectResponse("/login", status_code=302)
    
    tasks = session.exec(select(BackupTask)).all()
    settings = get_settings(session)
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "tasks": tasks, 
        "settings": settings
    })

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login_action(
    username: str = Form(...),
    password: str = Form(...), 
    session: Session = Depends(get_session)
):
    settings = get_settings(session)
    # 验证账号和密码
    if username == settings.admin_user and password == settings.admin_password:
        response = RedirectResponse("/", status_code=302)
        # 设置简单的 Cookie 标记
        response.set_cookie(key="auth_token", value="logged_in", httponly=True, max_age=86400)
        return response
    
    # 登录失败，带参数跳转
    return RedirectResponse("/login?error=1", status_code=302)

@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("auth_token")
    return response

@app.post("/settings/save")
async def save_settings(
    smtp_server: str = Form(...), 
    smtp_port: int = Form(...),
    smtp_user: str = Form(...), 
    smtp_password: str = Form(...),
    admin_user: str = Form(...),
    admin_password: str = Form(...),
    session: Session = Depends(get_session)
):
    s = get_settings(session)
    s.smtp_server = smtp_server
    s.smtp_port = smtp_port
    s.smtp_user = smtp_user
    s.smtp_password = smtp_password
    s.admin_user = admin_user
    s.admin_password = admin_password
    session.add(s)
    session.commit()
    return RedirectResponse("/", status_code=302)

@app.post("/task/add")
async def add_task(
    name: str = Form(...), 
    path: str = Form(...), 
    cron: str = Form(...),
    subject: str = Form(...), 
    to_email: str = Form(""), 
    zip_password: str = Form(""),
    session: Session = Depends(get_session)
):
    task = BackupTask(
        name=name, 
        path=path, 
        cron=cron, 
        subject=subject, 
        to_email=to_email, 
        zip_password=zip_password
    )
    session.add(task)
    session.commit()
    # 添加任务后刷新调度器
    refresh_scheduler()
    return RedirectResponse("/", status_code=302)

@app.get("/task/delete/{task_id}")
async def delete_task(task_id: int, session: Session = Depends(get_session)):
    task = session.get(BackupTask, task_id)
    if task:
        session.delete(task)
        session.commit()
        refresh_scheduler()
    return RedirectResponse("/", status_code=302)

@app.get("/task/run/{task_id}")
async def run_now(task_id: int, session: Session = Depends(get_session)):
    # 立即异步运行一次任务
    scheduler.add_job(run_backup_job, args=[task_id])
    return RedirectResponse("/", status_code=302)
