# docker build -t locust_exporter .
# docker run -p 9191:9191 -e EXPORTER_PORT=9191 -e LOCUST_HOST=http://localhost:8080 -v ./:/dir locust_exporter
FROM python:3.11-slim

RUN pip install prometheus_client requests

COPY LocustExporter.py /app/LocustExporter.py
COPY config.json /app/config.json

WORKDIR /app

#CMD ["python", "LocustExporter.py", "--config", "config.json"]
CMD ["python", "LocustExporter.py"]