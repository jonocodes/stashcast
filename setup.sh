#!/usr/bin/env bash
# First time setup script, but can be run every start to ensure dependencies are met

set -e

# Activate venv if present and not already active (optional for containers)
if [ -z "$VIRTUAL_ENV" ] && [ -f "venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
fi


export STASHCAST_DATA_DIR=${STASHCAST_DATA_DIR:=data}
export NLTK_DATA=${NLTK_DATA:=$STASHCAST_DATA_DIR}

echo "Using STASHCAST_DATA_DIR: $STASHCAST_DATA_DIR"
echo "Using NLTK_DATA: $NLTK_DATA"

python -c "import nltk; nltk.download('punkt_tab'); nltk.download('stopwords')"

./manage.py migrate

./manage.py list_superusers
