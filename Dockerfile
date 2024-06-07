FROM python:3.11-alpine
ADD src /d20
ADD requirements.txt .
RUN pip install -r requirements.txt
CMD ["python", "/d20/run.py"]