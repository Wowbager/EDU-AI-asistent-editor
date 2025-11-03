FROM python:3.9-slim

RUN apt-get update && apt-get -y upgrade && apt-get install -y gcc g++ python3-dev libevent-dev openssl wget
RUN wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb && \
    apt-get install -y ./wkhtmltox_0.12.6.1-3.bookworm_amd64.deb || true && \
    rm wkhtmltox_0.12.6.1-3.bookworm_amd64.deb

WORKDIR /app
COPY . /app

RUN pip3 install -U pip
RUN pip3 install --no-cache-dir -r requirements.txt
