# Agent Guide (StashCast)

## Project summary
- Django single-user web app for stashing online media and exposing it as podcast feeds.
- Background work handled by Huey (with sqlite); downloads via yt-dlp; optional ffmpeg transcoding.

## Key paths
- `stashcast/`: Django project settings and URLs.
- `media/`: App code, models, views, templates, tasks.
- `demo_data/`: Sample media for the local test server.
- `data_docker/`: Runtime data when using Docker.

## Run locally (no Docker)
I often use flox for managing my environment. This means you will need to run `flox activate` to enter the python environment with all the dependencies. You can also execute one off like so: `flox activate -- ./manage.py check`.

Since flox is a personal detail, dont add it to the readme.

```bash
python -m venv venv
source venv/bin/activate
just setup-with-packages
./manage.py createsuperuser
just dev
```

## Common commands
- Stash a URL: `./manage.py stash https://example.com/video.mp4`
- Transcode only: `./manage.py transcode https://example.com/video.mp4 --outdir ./output`
- Summarize subtitles: `./manage.py summarize demo_data/carpool/subtitles.vtt`
- Dev server only: `./manage.py runserver`
- Huey worker: `./manage.py run_huey`
- Test media server: `python test_server.py`

## Tests
```bash
pip install -r requirements-dev.txt
coverage run -m pytest
coverage report -m
```

## Notes for changes
- Prefer touching only the relevant app (`media/`) or Django settings in `stashcast/`.
- Background tasks are queued; consider the Huey worker when debugging async flows.
- Run tests when making changes to verify for regressions.
- Keep it DRY and regularly check for code duplication.
