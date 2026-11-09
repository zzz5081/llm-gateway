# LLM 调用网关 —— 镜像构建文件
#
# 构建：docker build -t llm-gateway:v1 .

FROM python:3.12-slim

WORKDIR /app

# ★ 先只 COPY 依赖清单，再装包
#   这样改代码时，pip install 这层能命中缓存，build 只要 2-3 秒
COPY requirements.txt .

# ★ pip 用国内镜像源
#   容器是干净环境，不继承宿主机的 pip 配置
#   不换源的话会去 pypi.org，国内速度几十 kB/s，还会下到损坏的文件
#   （--timeout / --retries：网络抖动时自动重试，而不是直接失败）
RUN pip install --no-cache-dir \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --timeout 120 \
        --retries 5 \
        -r requirements.txt

# ★ 代码这层常变，放最后
COPY . .

# 只是文档标注，真正开端口靠 docker run 的 -p
EXPOSE 8000

# ★ --host 0.0.0.0 必须写！
#   默认 uvicorn 只听 127.0.0.1，那只在容器内部可达，端口映射进不来
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
