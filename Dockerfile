FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build -- --outDir /frontend/dist
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/* && ffmpeg -version && ffprobe -version && ffmpeg -hide_banner -encoders | grep -q libx264
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /frontend/dist ./web
RUN useradd --create-home hys && chown -R hys:hys /app
USER hys
EXPOSE 3000
CMD ["python", "-m", "app.serve"]
