FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib STEELMIND_OUTPUT_ROOT=/data/runs \
    STEELMIND_FONT=/app/src/steelmind_export/assets/fonts/NotoSansCJKsc-Regular.otf \
    STEELMIND_FONT_FAMILY="Noto Sans CJK SC"
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer fonts-noto-cjk libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-deps . \
    && useradd -m -u 10001 steelmind && mkdir -p /data/runs \
    && chown -R steelmind:steelmind /data
USER steelmind
EXPOSE 8000
CMD ["uvicorn", "steelmind_export.api:app", "--host", "0.0.0.0", "--port", "8000"]
