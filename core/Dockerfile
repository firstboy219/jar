FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 HF_HOME=/srv/models FASTEMBED_CACHE_PATH=/srv/models
# ffmpeg: songs fetched for the owner are converted to MP3 (musiclib.py)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-dev.txt ./
ARG DEV=0
RUN pip install --no-cache-dir -r requirements.txt \
 && if [ "$DEV" = 1 ]; then pip install --no-cache-dir -r requirements-dev.txt; fi
# Bake the local embedding model into the image (no download at runtime, no memory text leaves the server)
ARG EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
RUN python -c "from fastembed import TextEmbedding as T; T('${EMBED_MODEL}', cache_dir='/srv/models')" \
 && chmod -R a+rX /srv/models
COPY app ./app
COPY config ./config
COPY tests ./tests
COPY pytest.ini ./
USER 1000:1000
EXPOSE 8000 8100
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
