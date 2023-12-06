FROM python:3.10

COPY dist/*.whl /tmp/
RUN python3 -m pip install /tmp/*.whl

CMD [ "legibot" ]
