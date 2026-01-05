from fastapi import FastAPI, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Field, Session, create_engine, select
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from typing import Optional, List
import uvicorn
import secrets
from app.backup_core import BackupManager

# --- 数据库模型 ---
class Settings(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    smtp_server: str = "smtp.qq.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    admin_password: str = "admin" # 默认登录密码

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
# app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 数据库
sqlite_file_name = "/data/database.db" # 映射到 Docker 卷
if not os.path.exists("/data"): os.makedirs("/data")
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url)
SQLModel.metadata.create_all(engine)

# 调度器
scheduler = BackgroundScheduler()
scheduler.start()

# --- 辅助函数 ---
def get_session():
    with Session(engine) as session:
        yield session

def verify_auth(request: Request):
    token = request.cookies.get("auth_token")
    if not token: return False
    # 这里为了演示简单，直接用 cookie 标记，实际应校验 Session/JWT
    return True

def get_settings(session):
    s = session.exec(select(Settings)).first()
    if not s:
        s = Settings()
        session.add(s)
        session.commit()
        session.refresh(s)
    return s

def run_backup_job(task_id: int):
    """调度器调用的实际执行函数"""
    with Session(engine) as session:
        task = session.get(BackupTask, task_id)
        settings = get_settings(session)
        if not task: return

        # 更新状态
        task.status = "运行中..."
        session.add(task)
        session.commit()

        # 准备配置
        smtp_conf = {
            "server": settings.smtp_server,
            "port": settings.smtp_port,
            "user": settings.smtp_user,
            "password": settings.smtp_password
        }
        task_conf = task.dict()
        
        # 执行
        manager = BackupManager(smtp_conf, task_conf)
        success = manager.run()

        # 更新结果
        task.status = "成功" if success else "失败"
        task.last_run = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session.add(task)
        session.commit()

def refresh_scheduler():
    """根据数据库重置所有定时任务"""
    scheduler.remove_all_jobs()
    with Session(engine) as session:
        tasks = session.exec(select(BackupTask)).all()
        for task in tasks:
            try:
                scheduler.add_job(
                    run_backup_job, 
                    CronTrigger.from_crontab(task.cron), 
                    args=[task.id], 
                    id=str(task.id)
                )
            except Exception as e:
                print(f"Cron Error for {task.name}: {e}")

# 初始化时加载任务
refresh_scheduler()

# --- 路由 ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: Session = Depends(get_session)):
    if not verify_auth(request): return RedirectResponse("/login", status_code=302)
    tasks = session.exec(select(BackupTask)).all()
    settings = get_settings(session)
    return templates.TemplateResponse("dashboard.html", {"request": request, "tasks": tasks, "settings": settings})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login_action(password: str = Form(...), session: Session = Depends(get_session)):
    settings = get_settings(session)
    if password == settings.admin_password:
        response = RedirectResponse("/", status_code=302)
        response.set_cookie(key="auth_token", value="logged_in", httponly=True)
        return response
    return RedirectResponse("/login?error=1", status_code=302)

@app.post("/settings/save")
async def save_settings(
    smtp_server: str = Form(...), smtp_port: int = Form(...),
    smtp_user: str = Form(...), smtp_password: str = Form(...),
    admin_password: str = Form(...),
    session: Session = Depends(get_session)
):
    s = get_settings(session)
    s.smtp_server = smtp_server
    s.smtp_port = smtp_port
    s.smtp_user = smtp_user
    s.smtp_password = smtp_password
    s.admin_password = admin_password
    session.add(s)
    session.commit()
    return RedirectResponse("/", status_code=302)

@app.post("/task/add")
async def add_task(
    name: str = Form(...), path: str = Form(...), cron: str = Form(...),
    subject: str = Form(...), to_email: str = Form(""), zip_password: str = Form(""),
    session: Session = Depends(get_session)
):
    task = BackupTask(name=name, path=path, cron=cron, subject=subject, to_email=to_email, zip_password=zip_password)
    session.add(task)
    session.commit()
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
    # 异步立即执行
    scheduler.add_job(run_backup_job, args=[task_id])
    return RedirectResponse("/", status_code=302)
