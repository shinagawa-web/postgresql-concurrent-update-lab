FROM python:3.12-slim
WORKDIR /app
RUN pip install "psycopg[binary]"
COPY run.py .
ENTRYPOINT ["python3", "run.py"]
