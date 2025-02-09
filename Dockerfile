FROM python:3.8-alpine

WORKDIR /app
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY ./*.py /app/

ENTRYPOINT ["python", "main.py"]
CMD ["schedule"]
