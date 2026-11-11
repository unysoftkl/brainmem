# brainmem 运行镜像（阶段6）
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
# 安装运行时依赖（含 fastmcp/jieba），-e 便于挂载源码
RUN pip install --no-cache-dir -e .

ENV BRAINMEM_STORAGE=postgres \
    BRAINMEM_PRESET=fast
EXPOSE 8770
# 默认起 MCP Server（HTTP/SSE，端口 8770）；可用环境变量/命令覆盖为 CLI 等
CMD ["python", "-m", "brainmem.interfaces.mcp_server", "--transport", "http"]
