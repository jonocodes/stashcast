#!/usr/bin/env bash
# First time setup script, but can be run every start to ensure dependencies are met

set -e

# Only install packages if --with-packages flag is provided
if [[ "$1" == "--with-packages" ]]; then
    # Upgrade pip and build tools first to avoid setuptools compatibility issues
    pip install --upgrade pip setuptools wheel
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

# ./manage.py collectstatic --noinput

./manage.py list_superusers
