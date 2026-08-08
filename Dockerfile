# syntax=docker/dockerfile:1

FROM python:3.11-slim-bookworm

ENV HOME=/tmp \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp/cache

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libtk8.6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints-baseline.txt ./
RUN python -m pip install --no-cache-dir \
        -r requirements.txt \
        -c constraints-baseline.txt

COPY . .

RUN python -c "import tkinter; print(tkinter.TkVersion)" \
    && python scripts/verify_baseline.py \
    && python -m compileall -q . \
    && mkdir -p /app/_runtime /tmp/cache /tmp/matplotlib \
    && chown -R 1000:1000 /app /tmp/cache /tmp/matplotlib

USER 1000:1000

ENTRYPOINT ["python", "castem_pipeline_gui_scientific.py"]
CMD ["--help"]
