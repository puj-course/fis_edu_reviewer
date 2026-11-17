FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY reviewer reviewer
COPY rubrics rubrics
COPY config config
COPY deploy/ciclo.sh deploy/metabase_setup.py deploy/verificar_tableros.py deploy/
RUN sed -i 's/\r$//' deploy/ciclo.sh && chmod +x deploy/ciclo.sh
ENV TZ=America/Bogota
CMD ["/app/deploy/ciclo.sh"]
