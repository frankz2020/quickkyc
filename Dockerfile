# Use Python 3.8 slim base image
FROM python:3.8-slim

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create tmp directory
RUN mkdir -p tmp

# Set environment variables
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Expose port
EXPOSE 8080

# Run the application
CMD ["python", "app.py"]