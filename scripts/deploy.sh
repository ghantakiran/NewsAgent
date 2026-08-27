#!/bin/bash
set -e

echo "=== NewsAgent Deployment Helper ==="
echo ""

# Check required tools
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 required"; exit 1; }

# Generate JWT secret if not set
if [ -z "$JWT_SECRET" ]; then
    export JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "Generated JWT_SECRET: $JWT_SECRET"
    echo "Add this to your deployment environment variables!"
fi

# Check if running locally or in production
if [ "$PORT" = "" ]; then
    PORT=8000
fi

echo ""
echo "Starting NewsAgent API on port $PORT..."
echo "Swagger docs: http://localhost:$PORT/docs"
echo ""

uvicorn backend.main:app --host 0.0.0.0 --port $PORT "$@"
