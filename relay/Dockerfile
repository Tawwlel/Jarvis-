FROM python:3.12-slim
RUN pip install --no-cache-dir aiohttp
WORKDIR /app
COPY server.py .
COPY static static
VOLUME /data
EXPOSE 8080
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8080", "--db", "/data/relay.db"]
