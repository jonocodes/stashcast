# Use the official Python runtime image
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
    apt-get install -y --no-install-recommends ffmpeg yt-dlp just && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --upgrade pip 

# Copy the Django project  and install dependencies
COPY requirements.txt  /app/

# run this command to install all dependencies 
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Django project to the container
COPY . /app/

# Expose the Django port
EXPOSE 8000

# Make setup executable (contains migrations/NLTK data)
RUN chmod +x setup.sh

# Run setup (migrations, NLTK) and start Django server
CMD ["bash", "-c", "./setup.sh && python manage.py runserver 0.0.0.0:8000"]
