FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py secure_app.py VERSION ./
RUN mkdir -p /config /fallback/work /fallback/personal
EXPOSE 8092
CMD ["uvicorn","secure_app:app","--host","0.0.0.0","--port","8092"]
