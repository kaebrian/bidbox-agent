FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "mcp[cli]>=2.2.0"
COPY main.py .
ENV BIDBOX_TRANSPORT=streamable-http BIDBOX_HOST=0.0.0.0 BIDBOX_PORT=8000
EXPOSE 8000
CMD ["python", "main.py"]
