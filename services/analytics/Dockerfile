FROM python:3.12-slim
WORKDIR /app
COPY services/analytics/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY shared /app/shared
COPY services/__init__.py /app/services/__init__.py
COPY services/analytics /app/services/analytics
COPY postgres/init/003-temporal-predictions.sql /app/postgres/init/003-temporal-predictions.sql
COPY postgres/init/005-experiment-lineage.sql /app/postgres/init/005-experiment-lineage.sql
COPY contracts/schemas/actual-assignment.schema.json contracts/schemas/actual-exposure.schema.json contracts/schemas/next-renewal-outcome.schema.json /app/contracts/schemas/
EXPOSE 8000
CMD ["sh", "-c", "python -m services.analytics.app.migrate && exec uvicorn services.analytics.app.main:app --host 0.0.0.0 --port 8000"]
