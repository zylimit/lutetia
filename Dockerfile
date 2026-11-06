FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY lutetia ./lutetia
COPY sql ./sql
RUN pip install --no-cache-dir .
ENV STATE_DIR=/data/state
VOLUME ["/data"]
EXPOSE 8080
CMD ["sh", "-c", "lutetia migrate && exec lutetia run"]
