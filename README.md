# TamilTTS Studio

Convert Tamil essays (with embedded English) into high-quality MP3 audio using Google Cloud Text-to-Speech.

---

## Architecture

```
Browser -> Nginx (HTTPS) -> FastAPI (port 8000)
                                |
                           Redis Queue
                                |
                         Celery Worker
                                |
                      Google Cloud TTS API
                                |
                      ffmpeg (stitch + normalize)
                                |
              /var/lib/tamiltts/outputs/{job_id}/output.mp3
```

---

## Deployment

### 1. System dependencies

```bash
sudo apt update && sudo apt install -y \
  python3.11 python3.11-venv python3-pip \
  postgresql postgresql-contrib \
  redis-server \
  ffmpeg \
  nginx \
  certbot python3-certbot-nginx
```

### 2. Create system user and directories

```bash
sudo useradd --system --shell /bin/bash --create-home --home /opt/tamiltts tamiltts
sudo mkdir -p /var/lib/tamiltts/outputs /etc/tamiltts
sudo chown -R tamiltts:tamiltts /var/lib/tamiltts /opt/tamiltts
```

### 3. PostgreSQL database

```bash
sudo -u postgres psql <<EOF
CREATE USER tamiltts WITH PASSWORD 'strongpassword';
CREATE DATABASE tamiltts OWNER tamiltts;
EOF
```

### 4. Deploy application code

```bash
sudo rsync -av tamiltts/ /opt/tamiltts/
cd /opt/tamiltts
sudo -u tamiltts python3.11 -m venv venv
sudo -u tamiltts venv/bin/pip install -r requirements.txt
```

### 5. Configure environment

```bash
sudo cp deploy/.env.example /etc/tamiltts/.env
sudo nano /etc/tamiltts/.env   # Fill in all values
sudo chmod 640 /etc/tamiltts/.env
sudo chown root:tamiltts /etc/tamiltts/.env
```

Generate a strong SECRET_KEY:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 6. GCP Service Account Key

```bash
sudo cp your-gcp-key.json /etc/tamiltts/gcp-key.json
sudo chown root:tamiltts /etc/tamiltts/gcp-key.json
sudo chmod 640 /etc/tamiltts/gcp-key.json
```

Enable the API in GCP:
```bash
gcloud services enable texttospeech.googleapis.com
```

Required IAM role: `Cloud Text-to-Speech API User`

### 7. Run database migration

```bash
sudo -u tamiltts bash -c "
  set -a; source /etc/tamiltts/.env; set +a
  psql \$DATABASE_URL -f /opt/tamiltts/migrations/001_initial.sql
"
```

### 8. Create first user

```bash
sudo -u tamiltts bash -c "
  set -a; source /etc/tamiltts/.env; set +a
  cd /opt/tamiltts
  venv/bin/python scripts/create_user.py \
    --email admin@example.com \
    --password 'YourStrongPassword' \
    --admin
"
```

### 9. Install systemd services

```bash
sudo cp deploy/tamiltts-web.service    /etc/systemd/system/
sudo cp deploy/tamiltts-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tamiltts-web tamiltts-worker
sudo systemctl start  tamiltts-web tamiltts-worker
sudo systemctl status tamiltts-web tamiltts-worker
```

### 10. Configure Nginx

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/tamiltts
# Edit: replace yourdomain.com
sudo nano /etc/nginx/sites-available/tamiltts
sudo ln -s /etc/nginx/sites-available/tamiltts /etc/nginx/sites-enabled/tamiltts
sudo nginx -t && sudo systemctl reload nginx
```

### 11. HTTPS with Let's Encrypt

```bash
sudo certbot --nginx -d yourdomain.com
```

---

## Production Hardening

### Firewall
```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### Redis (localhost only)
Edit `/etc/redis/redis.conf`:
```
bind 127.0.0.1 ::1
requirepass your-redis-password
```
Update `.env`: `REDIS_URL=redis://:your-redis-password@localhost:6379/0`

---

## Operations

### View logs
```bash
journalctl -u tamiltts-web    -f
journalctl -u tamiltts-worker -f
```

### Restart services
```bash
sudo systemctl restart tamiltts-web tamiltts-worker
```

### Backup database
```bash
sudo -u postgres pg_dump tamiltts | gzip > tamiltts_$(date +%Y%m%d).sql.gz
```

### Rotate SECRET_KEY
1. `python3 -c "import secrets; print(secrets.token_hex(32))"`
2. Update `/etc/tamiltts/.env`
3. `sudo systemctl restart tamiltts-web`
4. All sessions invalidated — users must re-login.

### Revoke a share link (CLI)
```bash
sudo -u tamiltts bash -c "
  set -a; source /etc/tamiltts/.env; set +a
  cd /opt/tamiltts
  venv/bin/python - <<'EOF'
from app.database import SessionLocal
from app.models import ShareToken
db = SessionLocal()
token = db.query(ShareToken).filter(ShareToken.token == 'TOKEN_HERE').first()
if token:
    token.is_active = False
    db.commit()
    print('Revoked')
else:
    print('Not found')
db.close()
EOF
"
```

### Purge old jobs
```bash
sudo -u tamiltts bash -c "
  set -a; source /etc/tamiltts/.env; set +a
  cd /opt/tamiltts && venv/bin/python scripts/purge_old_jobs.py --days 30
"
```

Add to crontab (`crontab -u tamiltts -e`):
```
0 3 * * * set -a; source /etc/tamiltts/.env; set +a; cd /opt/tamiltts && venv/bin/python scripts/purge_old_jobs.py --days 30
```

### Add a new user
```bash
sudo -u tamiltts bash -c "
  set -a; source /etc/tamiltts/.env; set +a
  cd /opt/tamiltts
  venv/bin/python scripts/create_user.py --email user@example.com --password 'pass'
"
```

### Disable a user (psql)
```sql
UPDATE users SET is_active = FALSE WHERE email = 'user@example.com';
```

---

## Voice Mode Reference

| Mode                 | Google Voice      | Notes                          |
|----------------------|-------------------|--------------------------------|
| Male Newsreader      | ta-IN-Wavenet-D   | WaveNet quality, neutral/formal |
| Male Conversational  | ta-IN-Standard-B  | Standard quality, relaxed       |
| Female Newsreader    | ta-IN-Wavenet-A   | WaveNet quality, clear/formal   |
| Female Conversational| ta-IN-Standard-A  | Standard quality, warm          |

> Google TTS does not provide explicit newsreader/conversational style modes for ta-IN.
> WaveNet voices approximate formal/newsreader style via higher acoustic quality.

## Mixed Language Handling

English words in Tamil text are auto-detected via regex and wrapped with
`<lang xml:lang="en-US">` SSML tags, allowing the ta-IN voice to attempt
correct English phonology for those spans. Results vary — this is the best
available approach with the current Google TTS API.
