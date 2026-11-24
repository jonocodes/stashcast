#!/usr/bin/env bash

# Application setup script. Get dependencies and set up database. You should probably run bootstrap.sh first.

set -e

# Only install packages if --with-packages flag is provided
if [[ "$1" == "--with-packages" ]]; then
    pip install -r requirements.txt
else
    echo "Skipping package installation (use --with-packages to install dependencies)"
fi

export STASHCAST_DATA_DIR=${STASHCAST_DATA_DIR:=data}
export NLTK_DATA=${NLTK_DATA:=$STASHCAST_DATA_DIR}

echo "Using STASHCAST_DATA_DIR: $STASHCAST_DATA_DIR"
echo "Using NLTK_DATA: $NLTK_DATA"

# Only download NLTK data that is missing (the Docker image ships it already)
python - <<'PY'
import os
import nltk

for resource, package in [('tokenizers/punkt_tab', 'punkt_tab'), ('corpora/stopwords', 'stopwords')]:
    try:
        nltk.data.find(resource)
    except LookupError:
        nltk.download(package, download_dir=os.environ['NLTK_DATA'])
PY

# temp dummy values for initial setup so migrations can run
export SECRET_KEY="dummy"
export ALLOWED_HOSTS="dummy"
export STASHCAST_USER_TOKEN="dummy"

./manage.py migrate

# for demo environment, keys off env vars
./manage.py create_demo_user || echo demo user not created

# for branch preview environment, keys off env vars
./manage.py create_test_user || echo test user not created

./manage.py list_superusers
