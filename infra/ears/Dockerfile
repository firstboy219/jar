# jarvis-ears: local speech recognition (faster-whisper) + speaker verification/diarization (sherpa-onnx).
# Nothing it hears leaves the server.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl bzip2 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Speaker models (small, baked in): CAM++ embeddings (zh/en-trained, language-agnostic enough for voices)
# and the pyannote 3.0 segmentation model for "who spoke when" in meetings.
ARG SR=https://github.com/k2-fsa/sherpa-onnx/releases/download
RUN mkdir -p /srv/speaker && cd /srv/speaker \
 && curl -fsSL -o embed.onnx $SR/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx \
 && curl -fsSL $SR/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2 | tar xj \
 && mv sherpa-onnx-pyannote-segmentation-3-0/model.onnx segment.onnx && rm -rf sherpa-onnx-pyannote-segmentation-3-0 \
 && chmod -R a+rX /srv/speaker
COPY app.py ./
ENV HF_HOME=/models/hf PYTHONUNBUFFERED=1
USER 1000:1000
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
