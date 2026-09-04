FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx "websockets==12.0" \
    "openai>=1.40" azure-identity python-multipart
WORKDIR /app
COPY core.py main.py /app/
COPY skills /app/skills
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
