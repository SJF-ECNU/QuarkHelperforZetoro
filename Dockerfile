FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY quarkdav ./quarkdav
COPY plan.md ./plan.md

ENV HOST=0.0.0.0
ENV PORT=5212

EXPOSE 5212

CMD ["python", "-m", "quarkdav.main"]
