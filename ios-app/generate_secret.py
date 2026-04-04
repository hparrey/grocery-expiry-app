import secrets

# Generate a secure 32-byte random string
session_secret = secrets.token_urlsafe(32)
print(session_secret)