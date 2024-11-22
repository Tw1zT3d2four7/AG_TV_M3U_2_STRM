FROM python:3.11-alpine
MAINTAINER jeremy.at.aqqr@hotmail.com>

WORKDIR /app

COPY . ./

RUN apk update
RUN apk upgrade

RUN pip install requests

ENV AGTV_USERNAME=""
ENV AGTV_PASSWORD=""
ENV AGTV_MAX_TV_SHOWS_PAGES=25
ENV TMDB_API_KEY=""
ENV SCAN_INTERVAL=60
ENV DEBUG=false

RUN chmod +x /app/entrypoint.py

ENTRYPOINT ["python3", "/app/entrypoint.py"]
