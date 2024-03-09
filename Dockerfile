FROM python:3.7-slim-buster
RUN pip install pytelegrambotapi flask pymongo mongomock pydantic

ADD . /app
WORKDIR /app
RUN pip install -r requirements.txt
EXPOSE 5000

CMD ["python", "main.py"]
