FROM python:3.12-alpine
WORKDIR /app
COPY . .
EXPOSE 8080
# Listen on all interfaces so Fargate can reach the container
CMD ["python", "-m", "http.server", "8080", "--bind", "0.0.0.0"]
