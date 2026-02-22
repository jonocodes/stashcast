# Stage 1: Extract git info (lightweight, only used at build time)
FROM alpine:3.21 AS git-info
RUN apk add --no-cache git jq
WORKDIR /src
COPY .git .git
RUN jq -n \
    --arg sha "$(git rev-parse HEAD 2>/dev/null)" \
    --arg msg "$(git log -1 --pretty=%s 2>/dev/null)" \
    '{commit_sha: $sha, commit_message: $msg, branch: ""}' \
    > /git_info.json 2>/dev/null || \
    echo '{"commit_sha": "", "commit_message": "", "branch": ""}' > /git_info.json

# Stage 2: Main application image
FROM python:3.13-slim

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
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg yt-dlp just sqlite3 && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --upgrade pip

# Copy the Django project  and install dependencies
COPY requirements.txt  /app/

# run this command to install all dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Django project to the container
COPY . /app/

# Copy git info from the first stage (outside /app so volume mounts don't hide it)
COPY --from=git-info /git_info.json /etc/git_info.json

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
CMD ["bash", "-c", "./setup.sh && python manage.py runserver 0.0.0.0:8000"]
