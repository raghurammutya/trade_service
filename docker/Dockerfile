FROM ghcr.io/raghurammutya/base-image:latest

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY trade_service/docker/requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY trade_service/app /app/app

# Set Python path
ENV PYTHONPATH=/app

# Copy and set up entrypoint
COPY trade_service/docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
#CMD ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "--wait-for-client", "-m", "app.main"]
#CMD ["sh", "-c", "python -m debugpy --listen 0.0.0.0:5678 --wait-for-client -m app.main || tail -f /dev/null"]