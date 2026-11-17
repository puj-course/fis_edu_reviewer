FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TZ=America/Bogota
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY reviewer reviewer
COPY rubrics rubrics
COPY config config
COPY deploy/metabase_setup.py deploy/verificar_tableros.py deploy/
# Por defecto, el trabajador que atiende la cola de revisiones. El portal usa el mismo
# código con: gunicorn "reviewer.portal:crear_app()"
CMD ["python", "-m", "reviewer", "trabajador"]
