---
name: claude-web-start
description: Start the application with all dependencies
---

These instructions are specifically for bootstrapping the bare vm/container that Claude Code Web runs in - which looks like Ubuntu 22.04 LTS.

Setup the ubuntu environment

```bash
./bootstrap.sh
```

Setup the db and make an admin user for development

```bash
cp .env.example .env

just setup

DJANGO_SUPERUSER_USERNAME=admin \
DJANGO_SUPERUSER_PASSWORD=password123 \
DJANGO_SUPERUSER_EMAIL="" \
python manage.py createsuperuser --noinput

```

Start services
```bash
just dev
```

Wait for "Server running on port 8000"
