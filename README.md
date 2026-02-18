# Kubernetes Monitoring Service (Python)

Monitors a Kubernetes cluster (e.g. Docker Desktop enabled k8s) for changes in Pods, Services, and Deployments, then sends an email notification when changes occur.

## Features
- Polls cluster at a configurable interval (default 30s)
- Detects additions/removals and key attribute changes:
  - Pods added/removed/phase changes
  - Service added/removed/port additions/removals
  - Deployment added/removed/replica count changes
- Aggregates changes per poll into a single email
- Safe truncation of oversized email bodies
- Config via environment variables / `.env`

## Quick Start (Windows CMD)

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
REM Edit .env with your credentials
python main.py
```

## Configuration (.env variables)
| Variable | Default | Description |
|----------|---------|-------------|
| SMTP_HOST | smtp.gmail.com | SMTP server host |
| SMTP_PORT | 587 | SMTP server port (TLS) |
| EMAIL_USER | (none) | Sender SMTP username (Gmail address) |
| EMAIL_PASS | (none) | App password (NOT your regular password) |
| EMAIL_SENDER | EMAIL_USER | From email |
| EMAIL_RECEIVER | EMAIL_USER | To email |
| POLL_INTERVAL_SECONDS | 30 | Poll interval seconds |
| KUBE_CONTEXT | (auto) | Specific kube context name (optional) |
| LOG_LEVEL | INFO | Logging level |
| MAX_EMAIL_BODY_LENGTH | 4000 | Truncation length |
| SKIP_INITIAL_EMAIL | true | Suppress first snapshot email to avoid mass 'added' notices |

## Gmail App Password
Use an App Password (https://support.google.com/accounts/answer/185833) and put it in `EMAIL_PASS`.

## Initial Snapshot Behavior
By default the first poll only records baseline state and does not send an email (SKIP_INITIAL_EMAIL=true). Set `SKIP_INITIAL_EMAIL=false` if you want an email summarizing existing resources at startup.

## Running as Background Service
You can use `python main.py` inside a scheduled task or wrap with `start /B`.

## Testing Diff Logic
Run unit tests:
```cmd
pytest -q
```

## Extending
- Add more resource types by extending `ClusterSnapshot` and editing `_snapshot()` & `diff_snapshots()`.
- Convert polling to watch streams if lower latency is required.

## Security Notes
- Avoid committing real credentials. Use `.env` and keep it out of version control.
- Rotate app passwords periodically.

## Troubleshooting
- If kube config not found, ensure Docker Desktop Kubernetes is enabled and `kubectl get pods` works in a terminal.
- Set `KUBE_CONTEXT` if multiple contexts exist (`kubectl config get-contexts`).
- Increase `LOG_LEVEL=DEBUG` for verbose output.
