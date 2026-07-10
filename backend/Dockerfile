#基础镜像
FROM python:3.12-slim 

#切换到镜像内目录作为工作目录
WORKDIR /app

#
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

#在镜像中执行安装依赖
ARG REQUIREMENTS_FILE=requirements-docker.txt
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r ${REQUIREMENTS_FILE}

#把代码相关文件拷贝到镜像内的工作目录
COPY app ./app
COPY data ./data
COPY scripts ./scripts

#声明镜像提供服务的端口
EXPOSE 8000

#容器运行默认启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
