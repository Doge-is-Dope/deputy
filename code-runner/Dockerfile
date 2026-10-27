# The code runner: where the coding agent's commands run (server.py). It has no network, so the libraries a task may
# need are installed here; compose.yaml runs it read-only, as a user without privileges, with its working folders in
# memory.
FROM python:3.15-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install --no-cache-dir numpy==2.5.4 pandas==3.1.0 openpyxl==3.1.5 \
    && useradd --uid 1000 --no-create-home --home-dir /workspace runner

COPY server.py /opt/code-runner/server.py
USER runner
WORKDIR /workspace
EXPOSE 8080
CMD ["python", "-I", "/opt/code-runner/server.py"]
