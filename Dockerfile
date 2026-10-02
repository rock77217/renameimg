FROM python:3.12-slim-trixie

# 下載慢時可改用較近的鏡像站：--build-arg DEBIAN_MIRROR=http://ftp.tw.debian.org
ARG DEBIAN_MIRROR=""

# Debian 的 ffmpeg 已內建 libx265；tzdata 提供 Asia/Taipei 等時區資料
RUN if [ -n "$DEBIAN_MIRROR" ]; then \
        sed -i "s|http://deb.debian.org/debian$|$DEBIAN_MIRROR/debian|" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libimage-exiftool-perl tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TMPDIR=/work

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install . \
    && mkdir -p /work /reports \
    && chmod 1777 /work /reports

# 報告預設寫到 /reports，轉檔暫存在 /work；兩者都建議掛載出來
WORKDIR /reports
ENTRYPOINT ["renameimg"]
CMD ["--help"]
