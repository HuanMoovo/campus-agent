FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt requirements-ai.txt ./
ARG INSTALL_VECTOR=false
RUN if [ "$INSTALL_VECTOR" = "true" ]; then pip install --no-cache-dir -r requirements-ai.txt; else pip install --no-cache-dir -r requirements.txt; fi
COPY app ./app
RUN useradd --create-home campus && mkdir -p /app/data /home/campus/.cache && chown -R campus:campus /app /home/campus/.cache
USER campus
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
