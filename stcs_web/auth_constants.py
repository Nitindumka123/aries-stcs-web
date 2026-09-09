# Authentication constants for the STCS web application.

# Token expiration in minutes
ACCESS_TOKEN_EXPIRE_MINUTES = 120  # 2 hours

# Session cookie name
SESSION_COOKIE_NAME = "stcs_session"

# Default session secret (override via environment variable SESSION_SECRET)
# This must be kept secret and rotated regularly in production.
DEFAULT_SESSION_SECRET = "stcs-session-secret-change-me-for-production"

# Default development user credentials (environment variables override these)
# These are for local development only - passwords are hashed in production.
ADMIN_USERNAME_DEFAULT = "Admin"
SCIENTIST_USERNAME_DEFAULT = "Scientist1"

# Password hashing: bcrypt (cost factor auto-tuned by bcrypt.gensalt())
# Format: $2b$<cost>$<salt><hash>

# Password validation minimum length
MIN_PASSWORD_LENGTH = 6

# Rate limiting settings (login attempts per minute)
LOGIN_RATE_LIMIT_PER_MINUTE = 5

# CORS origins (development)
CORS_ORIGINS_DEVELOPMENT = ["http://localhost:8000", "http://127.0.0.1:8000"]

# Production CORS origins should be set via environment variable
# CORS_ORIGINS_PRODUCTION = os.environ.get("CORS_ORIGINS_PRODUCTION", "")