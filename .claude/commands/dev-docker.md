---
name: dev-docker
description: Start the application with all dependencies
---

Make sure to have 'docker' and 'just' installed.

Run these commands in order:

Setup the db

```bash
just docker-run just setup
```

Create admin user for development (admin:admin)

```bash
just docker-run just create-admin-dummy
```

Start services:
```bash
docker compose up

or

just dev-docker
```

Wait for "Server running on port 8000"
