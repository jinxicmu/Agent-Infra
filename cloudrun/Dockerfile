FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /service
COPY cloudrun/requirements.txt /service/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home service
COPY cloudrun /service/cloudrun
COPY workflows/CAPABILITIES.json workflows/PRESETS.json workflows/parameters.py /service/workflows/
USER 10001
CMD ["sh", "-c", "exec uvicorn cloudrun.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
