#!/usr/bin/env bash
# First time setup script, but can be run every start to ensure dependencies are met

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

./manage.py migrate

./manage.py list_superusers
