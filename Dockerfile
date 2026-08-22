FROM python:3.13-slim

# Git info passed as build args (no .git directory needed)
ARG GIT_COMMIT_SHA=""
ARG GIT_COMMIT_MSG=""
ARG GIT_BRANCH=""

# Create the app directory
RUN mkdir /app

# Set the working directory inside the container
WORKDIR /app

# Set environment variables
# Prevents Python from writing pyc files to disk
ENV PYTHONDONTWRITEBYTECODE=1
#Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

# Install system dependencies
# Note: the apt yt-dlp package is only a CLI convenience; the app uses the
# (much newer) pip package from requirements.txt.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg yt-dlp just sqlite3 curl unzip && \
    rm -rf /var/lib/apt/lists/*

# Install Deno: yt-dlp needs a JavaScript runtime to solve YouTube's player
# challenges. Without one, extraction falls back to clients whose stream URLs
# are commonly rejected with "HTTP Error 403: Forbidden".
ARG DENO_VERSION=v2.9.5
RUN case "$(dpkg --print-architecture)" in \
        amd64) DENO_ARCH=x86_64-unknown-linux-gnu ;; \
        arm64) DENO_ARCH=aarch64-unknown-linux-gnu ;; \
        *) echo "Unsupported architecture: $(dpkg --print-architecture)" && exit 1 ;; \
    esac && \
    curl -fsSL -o /tmp/deno.zip \
        "https://github.com/denoland/deno/releases/download/${DENO_VERSION}/deno-${DENO_ARCH}.zip" && \
    unzip -q /tmp/deno.zip -d /usr/local/bin && \
    rm /tmp/deno.zip && \
    chmod +x /usr/local/bin/deno && \
    deno --version

# Upgrade pip
RUN pip install --upgrade pip

# Copy the Django project  and install dependencies
COPY requirements.txt  /app/

# run this command to install all dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Django project to the container
COPY . /app/

# Write git info (outside /app so volume mounts don't hide it)
RUN printf '{"commit_sha": "%s", "commit_message": "%s", "branch": "%s"}\n' \
    "$GIT_COMMIT_SHA" "$GIT_COMMIT_MSG" "$GIT_BRANCH" > /etc/git_info.json

# Expose the Django port
EXPOSE 8000

# temp env vars so collectstatic works
# ENV SECRET_KEY="dummy"
# ENV ALLOWED_HOSTS="dummy"
# ENV STASHCAST_USER_TOKEN="dummy"
RUN SECRET_KEY="dummy" ALLOWED_HOSTS="dummy" STASHCAST_USER_TOKEN="dummy" python manage.py collectstatic --noinput

# Make setup executable (contains migrations/NLTK data)
RUN chmod +x setup.sh

# Run setup (migrations, NLTK) and start Django server
CMD ["bash", "-c", "pwd && ls -la && ./setup.sh && python manage.py runserver 0.0.0.0:8000"]
