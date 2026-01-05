# 使用轻量级 Python 镜像
FROM python:3.11-slim

# 设置时区为上海
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 安装系统依赖 (核心是 zip)
RUN apt-get update && apt-get install -y --no-install-recommends \
    zip \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制依赖并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码 (注意：复制的是 app 文件夹到 /app/app)
COPY app /app/app

# 暴露端口
EXPOSE 8000

# 数据卷挂载点 (数据库存放在 /data)
VOLUME ["/data"]

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
