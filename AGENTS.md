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

## Using docker
You can also run all the commands using the included docker setup, but note that does not work well in Claude Web since that is a container itself.

## Some common commands
- Stash a URL: `./manage.py stash https://example.com/video.mp4`
- Run the dev server, huey, and test media server: `just dev`
- Run tests `./manage.py test` or `just test`

## Claude Web environment setup
When running in Claude Web (Ubuntu container without flox/Docker) follow .claude/commands/claude-web-start.md

## Notes for changes
- Prefer touching only the relevant app (`media/`) or Django settings in `stashcast/`.
- Background tasks are queued; consider the Huey worker when debugging async flows.
- Since flox is a personal detail, dont add it to the readme.
- Run tests when making changes to verify for regressions.
- Keep it DRY and regularly check for code duplication.
