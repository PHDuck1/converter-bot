FROM python:3.7-bullseye

ENV PIP_DISABLE_PIP_VERSION_CHECK 1
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHON_VERSION 3.7

WORKDIR /code/

COPY ./requirements.txt .
RUN pip install -r requirements.txt
COPY . .

CMD [ "python3", "bot.py" ]