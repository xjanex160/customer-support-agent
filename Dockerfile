##
## Customer Support Agent Dockerfile
##
## Purpose:
## - Containerize the FastAPI application and its dependencies.
##
## Author: Ebube Imoh
## Last Modified: 2025-11-19
##
## Dependencies:
## - Base images: `ghcr.io/astral-sh/uv`, `python:3.9-slim`
## - `uv` for faster, reproducible Python installs
##
## Performance Considerations:
## - Use slim base image to reduce attack surface and size.
## - Consider multi-stage builds with app bytecode compilation for faster cold starts.
##
## Security Considerations:
## - Avoid baking secrets into the image; supply via environment/secret managers.
## - Ensure `requirements.txt` is vetted; prefer pinned versions for reproducibility.

FROM ghcr.io/astral-sh/uv:latest AS uv

FROM python:3.9-slim

# Copy uv binary from the official image for dependency installs
COPY --from=uv /uv /bin/uv

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

# Copy application code
COPY . .

EXPOSE 8000

# Run the FastAPI app via uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
