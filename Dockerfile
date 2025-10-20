FROM python:3.10-slim-bookworm 

RUN apt update && apt upgrade -y

WORKDIR /usr/src/app

COPY . .

RUN pip3 install --upgrade pip && pip3 install -r requirements.txt

CMD gunicorn app:app & python3 main.py
