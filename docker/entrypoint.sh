#!/bin/bash
echo "🔁 Waiting for debugger to attach on port 5678..."
python -m debugpy --listen 0.0.0.0:5678 --wait-for-client -m app.main
