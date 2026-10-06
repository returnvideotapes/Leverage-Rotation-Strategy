FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY core/ ./core/
COPY utils/ ./utils/
COPY config.py .
COPY main.py .

CMD ["python", "main.py"]