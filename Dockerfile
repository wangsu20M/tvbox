FROM python:3.12-slim

WORKDIR /app

COPY vod_service.py /app/
COPY data/vod_catalog.json /app/data/vod_catalog.json

EXPOSE 8765

CMD ["python", "vod_service.py", "--host", "0.0.0.0", "--port", "8765"]
