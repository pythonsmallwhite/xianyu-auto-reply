# 快速更新用的叠加构建（scripts/update-server.sh 默认使用）
# 以已有的同服务镜像为底座（已包含系统依赖、Python 依赖和 Chromium），删除旧源码后复制当前源码，
# 只补装 pyproject 中尚未满足的 Python 依赖；浏览器已存在时 playwright install 不会下载，也不执行 apt。
# 需要刷新底座（例如升级系统依赖或 Playwright）时用 FULL_BUILD=1 走各服务自己的 Dockerfile。
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG SERVICE
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_DEFAULT_TIMEOUT=120
ARG PLAYWRIGHT_DOWNLOAD_HOST=https://registry.npmmirror.com/-/binary/playwright

WORKDIR /app
RUN test -n "$SERVICE" && rm -rf /app/common "/app/$SERVICE" /app/launcher
COPY common /app/common
COPY ${SERVICE} /app/${SERVICE}
COPY launcher /app/launcher

RUN python -c "import os, tomllib; s = os.environ['SERVICE']; deps = tomllib.load(open('/app/%s/pyproject.toml' % s, 'rb')).get('project', {}).get('dependencies', []); open('/tmp/requirements.txt', 'w').write(chr(10).join(deps))" \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && python -m playwright install chromium \
    && if python -c "import patchright" 2>/dev/null; then python -m patchright install chromium; fi \
    && mkdir -p "/app/$SERVICE/logs"
