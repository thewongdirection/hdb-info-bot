FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY hdb_bot ./hdb_bot

ENV RUN_MODE=webhook
ENV PORT=8080
EXPOSE 8080

CMD ["python", "-m", "hdb_bot.main"]
