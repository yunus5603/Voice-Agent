# Deploy to Google Cloud Run

The repository ships a production [`Dockerfile`](../Dockerfile): a two-stage
build with uv, a non-root user, and a `/healthz` endpoint. Cloud Run supports
WebSockets out of the box.

## 1. One-time setup

```bash
export PROJECT_ID=your-project
export REGION=us-central1
gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com

# Store the Gemini key in Secret Manager, never in the image or the repo.
printf '%s' "$GEMINI_API_KEY" | gcloud secrets create gemini-api-key --data-file=-
```

Grant the Cloud Run runtime service account access to the secret
(`roles/secretmanager.secretAccessor`).

## 2. Deploy from source

```bash
gcloud run deploy adk-voice-agent \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
  --set-env-vars MAX_ACTIVE_SESSIONS=10 \
  --timeout 3600 \
  --concurrency 20 \
  --max-instances 2
```

- `--timeout 3600` lets a WebSocket stay open for up to an hour.
- `--max-instances` and `MAX_ACTIVE_SESSIONS` together cap your Gemini spend.
- Live sessions are in memory, so a reconnect may land on another instance.
  Keep `--max-instances 1` if you want session resumption to always work, or
  add session affinity (`--session-affinity`).

## 3. Allow the public origin

The WebSocket only accepts allowlisted origins. After the first deploy, set the
service URL:

```bash
URL=$(gcloud run services describe adk-voice-agent --region "$REGION" --format 'value(status.url)')
gcloud run services update adk-voice-agent --region "$REGION" \
  --update-env-vars "^@^WS_ALLOWED_ORIGINS=$URL"
```

Open the URL, paste a job description, and start an interview. The browser needs
HTTPS for microphone access, which Cloud Run provides.

## 4. Watch it

```bash
gcloud run services logs read adk-voice-agent --region "$REGION" | grep turn_metrics
```

## Before a real launch

This deploy is fine for a demo. For real users, add authentication (for
example Identity-Aware Proxy), per-user rate limits, durable session storage,
and alerts on error rate and `response_ms`.

## Run the container locally

```bash
docker build -t adk-voice-agent .
docker run --rm -p 8080:8080 --env-file .env \
  -e WS_ALLOWED_ORIGINS=http://localhost:8080 adk-voice-agent
```
