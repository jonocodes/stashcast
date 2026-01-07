set shell := ["bash", "-c"]

set dotenv-load

setenv := '. ".envrc"'

# show list of commands
help:
    just --list

# install python dependencies
setup:
    ./setup.sh

# clean up dev dependencies
clean:
    rm -rf __pycache__

# run the django server
dev:
    ./manage.py runserver 0.0.0.0:8000

# run the server and the worker
dev-stack:
    echo running dev server at http://0.0.0.0:8000
    exec honcho start

# kill the local dev process by port in case it's running detached
kill:
    lsof -i tcp:8000 -t | xargs kill

# run linting and auto-fixing
lint:
    ruff format
    ruff check --fix --unsafe-fixes

# run tests
test *args:
    ./manage.py test {{ args }}

# alias for django manage command
manage *args:
    ./manage.py {{ args }}
