FROM python:3.11-alpine

MAINTAINER jeremy.at.aqqr@hotmail.com>

WORKDIR /app

COPY . ./
# Install dependencies system-wide and create a virtual environment

RUN python3 -m venv /venv  # Create virtual environment
RUN /venv/bin/pip install --upgrade pip  # Upgrade pip
RUN /venv/bin/pip install -r requirements.txt  # Install dependencies inside venv
RUN apk update
RUN apk upgrade

# Set the virtual environment path for running the app
ENV PATH="/venv/bin:$PATH"

ENV AGTV_USERNAME=""
ENV AGTV_PASSWORD=""
ENV AGTV_MAX_TV_SHOWS_PAGES=25
ENV TMDB_API_KEY=""
ENV SCAN_INTERVAL=60
ENV DEBUG=false

RUN chmod +x /app/entrypoint.py

ENTRYPOINT ["python3", "/app/entrypoint.py"]
