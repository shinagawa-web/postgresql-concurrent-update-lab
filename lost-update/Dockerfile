FROM python:3.12-slim
WORKDIR /app
RUN pip install "psycopg[binary]" psutil
COPY run.py .
ENTRYPOINT ["python3", "run.py"]
