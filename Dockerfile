FROM python:3.12-slim
WORKDIR /app
RUN pip install "psycopg[binary]" psutil
COPY lost-update/run.py .
COPY hold-time/ hold-time/
ENTRYPOINT ["python3", "run.py"]
