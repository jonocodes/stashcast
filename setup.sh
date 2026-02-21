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

python -c "import nltk; nltk.download('punkt_tab'); nltk.download('stopwords')"

# temp dummy values for initial setup so migrations can run
export SECRET_KEY="dummy"
export ALLOWED_HOSTS="dummy"
export STASHCAST_USER_TOKEN="dummy"

./manage.py migrate

./manage.py list_superusers
