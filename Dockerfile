FROM --platform=linux/amd64 python:3.11-slim
WORKDIR /app
COPY pyproject.toml .
COPY src ./src
COPY evals ./evals
# Railway runs CPU-only. Install the CPU wheel first so sentence-transformers does
# not resolve the much larger CUDA distribution from PyPI.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==2.2.2+cpu"
RUN pip install --no-cache-dir .
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
CMD ["sh", "-c", "uvicorn voice_rag.app:app --host ${API_HOST:-0.0.0.0} --port ${PORT:-${API_PORT:-8000}}"]
