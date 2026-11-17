FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TZ=America/Bogota
# Escáner de SonarQube (trae su propio Java), verificado por su suma SHA-256.
ARG SCANNER=7.3.0.5189
ARG SCANNER_SHA256=7c201e1f16e64906da8fa7b77b3bda62e9c570f44323db763b4d083e0a1dbcd2
RUN python -c "import glob,hashlib,io,os,urllib.request,zipfile; v=os.environ['SCANNER']; d=urllib.request.urlopen(f'https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-{v}-linux-x64.zip').read(); assert hashlib.sha256(d).hexdigest()==os.environ['SCANNER_SHA256'], 'checksum del escaner no coincide'; zipfile.ZipFile(io.BytesIO(d)).extractall('/opt'); os.rename(f'/opt/sonar-scanner-{v}-linux-x64','/opt/sonar-scanner'); [os.chmod(f,0o755) for f in glob.glob('/opt/sonar-scanner/bin/*')+glob.glob('/opt/sonar-scanner/jre/bin/*')+glob.glob('/opt/sonar-scanner/jre/lib/jspawnhelper')]"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY reviewer reviewer
COPY rubrics rubrics
COPY config config
COPY deploy/metabase_setup.py deploy/sonar_setup.py deploy/verificar_tableros.py deploy/
# Por defecto, el trabajador que atiende la cola de revisiones. El portal usa el mismo
# código con: gunicorn "reviewer.portal:crear_app()"
CMD ["python", "-m", "reviewer", "trabajador"]
