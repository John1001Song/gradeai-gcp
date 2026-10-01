FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /srv

COPY requirements.txt requirements-gcp.txt ./
RUN pip install --no-cache-dir -r requirements-gcp.txt

COPY app ./app

# Cloud Run sets $PORT. Run as a non-root user.
RUN useradd --uid 10001 --no-create-home gradeai
USER gradeai
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
