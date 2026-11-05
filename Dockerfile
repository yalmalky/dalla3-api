FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*
COPY server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY server ./server
ENV PYTHONUNBUFFERED=1
EXPOSE 10000
CMD uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-10000}
