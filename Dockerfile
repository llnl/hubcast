FROM python:3.12-alpine AS build
WORKDIR /app

RUN apk update && apk add --no-cache \
      build-base python3-dev \
      openldap-dev cyrus-sasl-dev \
      openssl-dev

# copy build deps
COPY pyproject.toml README.md ./
COPY src ./src
COPY logging_config.json ./

# create venv and build hubcast and deps
RUN python -m venv /venv \
 && /venv/bin/pip install --upgrade pip setuptools wheel \
 && /venv/bin/pip install --no-cache-dir /app[ldap]

FROM python:3.12-alpine
WORKDIR /app

RUN apk update && apk add --no-cache openldap cyrus-sasl openssl

COPY --from=build /venv /venv
# hubcast default logging config
COPY logging_config.json ./

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ENV PATH="/venv/bin:$PATH"
ENTRYPOINT ["python", "-m", "hubcast"]
