# QA Engine - Environment Variables Template
# Copy this file to .env and fill in your actual values
# DO NOT commit .env file to version control

# ================ FLASK CONFIGURATION ================
# Required: Secret key for Flask sessions (generate a secure random string)
FLASK_SECRET_KEY=your-very-secure-secret-key-here-change-this

# Required: Admin password for accessing the application
QA_PASSWORD=your-admin-password-here

# Optional: Enable debug mode (only for development)
FLASK_DEBUG=False

# Optional: Flask environment
FLASK_ENV=production

# ================ AI PROVIDER API KEYS ================
# At least one AI provider API key is required

# Anthropic Claude API Key (recommended)
# Get from: https://console.anthropic.com/
ANTHROPIC_API_KEY=sk-ant-api03-your-anthropic-key-here

# OpenAI API Key (alternative)
# Get from: https://platform.openai.com/api-keys
OPENAI_API_KEY=sk-your-openai-key-here

# ================ DATABASE CONFIGURATION ================
# Optional: If using a database (currently using file-based storage)
# DATABASE_URL=sqlite:///qa_engine.db
# POSTGRES_URL=postgresql://user:password@localhost/qa_engine

# ================ FILE STORAGE ================
# Optional: Custom paths for file storage
# UPLOAD_FOLDER=/path/to/uploads
# RESULTS_FOLDER=/path/to/results
# TEMP_FOLDER=/path/to/temp

# Maximum file size (in bytes)
MAX_CONTENT_LENGTH=16777216  # 16MB

# ================ SECURITY SETTINGS ================
# Optional: Additional security settings
# SESSION_COOKIE_SECURE=True  # Only send cookies over HTTPS
# SESSION_COOKIE_HTTPONLY=True  # Prevent JavaScript access to cookies
# PERMANENT_SESSION_LIFETIME=3600  # Session timeout in seconds

# ================ AI MODEL CONFIGURATION ================
# Default AI provider (anthropic or openai)
DEFAULT_AI_PROVIDER=anthropic

# Default model names
ANTHROPIC_MODEL=claude-3-7-sonnet-20250219
OPENAI_MODEL=gpt-4o

# API request timeout (seconds)
API_TIMEOUT=120

# ================ APPLICATION SETTINGS ================
# Application name and version
APP_NAME=QA Engine
APP_VERSION=2.0.0

# Default language for analysis
DEFAULT_LANGUAGE=en

# Supported file extensions (comma-separated)
ALLOWED_EXTENSIONS=txt,csv,log,docx

# ================ LOGGING CONFIGURATION ================
# Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=INFO

# Log file path
# LOG_FILE=/var/log/qa_engine.log

# ================ RATE LIMITING ================
# Optional: API rate limiting settings
# RATE_LIMIT_PER_MINUTE=60
# RATE_LIMIT_PER_HOUR=1000

# ================ MONITORING & ANALYTICS ================
# Optional: Integration with monitoring services
# SENTRY_DSN=your-sentry-dsn-here
# GOOGLE_ANALYTICS_ID=your-ga-id-here

# ================ EMAIL CONFIGURATION ================
# Optional: Email settings for notifications
# MAIL_SERVER=smtp.gmail.com
# MAIL_PORT=587
# MAIL_USE_TLS=True
# MAIL_USERNAME=your-email@gmail.com
# MAIL_PASSWORD=your-app-password
# MAIL_DEFAULT_SENDER=your-email@gmail.com

# ================ BACKUP SETTINGS ================
# Optional: Backup configuration
# BACKUP_SCHEDULE=daily
# BACKUP_RETENTION_DAYS=30
# BACKUP_PATH=/path/to/backups

# ================ DEVELOPMENT SETTINGS ================
# Only for development environment

# Debug toolbar
# DEBUG_TB_ENABLED=True
# DEBUG_TB_INTERCEPT_REDIRECTS=False

# Profiling
# PROFILE=True
# PROFILE_DIR=/tmp/qa_engine_profiles

# ================ DEPLOYMENT SETTINGS ================
# Only for production deployment

# Server configuration
# HOST=0.0.0.0
# PORT=5001

# Worker processes (for gunicorn)
# WORKERS=4
# WORKER_CLASS=sync
# WORKER_CONNECTIONS=1000

# ================ EXAMPLE VALUES ================
# Here are some example values to help you get started:

# Example Flask secret key (generate your own!):
# FLASK_SECRET_KEY=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0

# Example admin password:
# QA_PASSWORD=SecureAdmin123!

# Example Anthropic API key format:
# ANTHROPIC_API_KEY=sk-ant-api03-abcd1234...

# Example OpenAI API key format:
# OPENAI_API_KEY=sk-abcd1234...

# ================ SECURITY NOTES ================
# IMPORTANT SECURITY REMINDERS:
# 1. Never commit the actual .env file to version control
# 2. Use strong, unique passwords and API keys
# 3. Regularly rotate API keys and passwords
# 4. In production, consider using environment-specific secret management
# 5. Limit API key permissions to minimum required scope
# 6. Monitor API usage for unusual activity
# 7. Enable 2FA on your AI provider accounts

# ================ GETTING API KEYS ================
# Anthropic Claude:
# 1. Go to https://console.anthropic.com/
# 2. Sign up or log in
# 3. Navigate to API Keys section
# 4. Create a new API key
# 5. Copy the key (starts with sk-ant-api03-)

# OpenAI:
# 1. Go to https://platform.openai.com/
# 2. Sign up or log in  
# 3. Navigate to API Keys section
# 4. Create a new API key
# 5. Copy the key (starts with sk-)

# ================ GENERATING SECURE KEYS ================
# You can generate secure keys using:
# Python: python -c "import secrets; print(secrets.token_urlsafe(32))"
# OpenSSL: openssl rand -base64 32
# Online: https://randomkeygen.com/ (use Fort Knox Passwords)