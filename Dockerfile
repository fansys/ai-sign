FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
LABEL org.opencontainers.image.title="sign" \
      org.opencontainers.image.description="AI 工具自动签到服务" \
      org.opencontainers.image.source="https://github.com/fansys/ai-sign"
ENV TZ=Asia/Shanghai UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    SIGN_DATA_DIR=/data SIGN_SCRIPTS_DIR=/data/scripts SIGN_BUILTIN_SCRIPTS_DIR=/srv/scripts-builtin \
    PATH="/srv/backend/.venv/bin:$PATH"
WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/app ./app
COPY scripts /srv/scripts-builtin
COPY frontend /srv/frontend
COPY cli/pyproject.toml /srv/cli/pyproject.toml
COPY cli/signcli /srv/cli/signcli
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8000/healthz',timeout=3)" || exit 1
# 单进程：API + 调度器 + Runner 同进程，不要开多 worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
