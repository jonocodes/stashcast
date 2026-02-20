set shell := ["bash", "-c"]

# set dotenv-load

# setenv := '. ".envrc"'

# show list of commands
help:
    just --list

# setup the db etc
setup:
    ./setup.sh

# install python dependencies and then the db
setup-with-packages:
    ./setup.sh --with-packages

# clean up dev dependencies
clean:
    rm -rf __pycache__

# remove all the data
clean-data:
    # rm -rf data
    rm -rf data_docker
    just setup

# lint, test, chcek translations
pre-commit:
    just lint
    just test
    ./scripts/check_translations.py

# run the django server
dev-web:
    honcho start web

# run the server, the worker, and demo data server
dev:
    exec honcho start

# run the dev services in docker
dev-docker *args:
    docker compose up --build {{ args }}

# kill the local dev process by port in case it's running detached
kill:
    lsof -i tcp:8000 -t | xargs kill

# run linting and auto-fixing
lint:
    ruff format
    ruff check --fix --unsafe-fixes

# create a superuser with username 'admin' and password 'admin' for testing/dev
create-admin-dummy:
    DJANGO_SUPERUSER_PASSWORD=admin ./manage.py createsuperuser --username admin --email "" --noinput

# create or update a test superuser (idempotent, safe to re-run)
create-test-user username="test" password="test":
    ./manage.py create_test_user {{ username }} {{ password }}

# run tests
test *args:
    pytest {{ args }}

# alias for django manage command
manage *args:
    ./manage.py {{ args }}

# alias to manage
m *args:
    ./manage.py {{ args }}

# alias to run commands in docker
docker-run *args:
    docker compose run web {{ args }}
