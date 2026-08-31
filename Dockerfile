FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制脚本和配置文件
COPY uimLogin.py .
COPY logConfig.py .
COPY ttLogin.py .
COPY ttEnroll.py .

# 创建空的日志配置需要的目录结构等（如果需要）
# 默认使用 UTC，如果需要使用北京时间，可以取消下面注释
RUN ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && echo 'Asia/Shanghai' > /etc/timezone

# 设置默认启动命令
CMD ["python", "ttEnroll.py"]
