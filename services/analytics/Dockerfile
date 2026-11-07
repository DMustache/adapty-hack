FROM python:3.12-slim
WORKDIR /app
COPY services/analytics/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY shared /app/shared
COPY services/__init__.py /app/services/__init__.py
COPY services/analytics /app/services/analytics
EXPOSE 8000
CMD ["uvicorn", "services.analytics.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
