FROM docker:27-cli
RUN apk add --no-cache python3 py3-pip docker-cli-compose
WORKDIR /opt/shared-updater
COPY updater.py /opt/shared-updater/updater.py
EXPOSE 8093
CMD ["python3", "/opt/shared-updater/updater.py"]
