FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY entropy/ ./entropy/
COPY rng.py .

EXPOSE 8000

CMD ["uvicorn", "rng:app", "--host", "0.0.0.0", "--port", "8000"]
