# syntax=docker/dockerfile:1
FROM python:3.12-slim

# uv resolves and installs from the lockfile, so the image carries exactly the versions
# that were tested — pip against floating lower bounds could ship something newer.
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv

WORKDIR /srv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/srv/.venv \
    PATH="/srv/.venv/bin:$PATH"

# Dependencies first, so editing app code doesn't invalidate the install layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
