#!/bin/sh
set -eu

SECRET_FILE=/app/data/runtime-secrets

if [ -z "${SECRET_KEY:-}" ] || [ -z "${TOTP_ENCRYPTION_KEY:-}" ]; then
    if [ -f "$SECRET_FILE" ]; then
        # The file is created by this script and is writable only by miniroom.
        . "$SECRET_FILE"
    else
        umask 077
        : "${SECRET_KEY:=$(openssl rand -base64 64 | tr -d '\n')}"
        : "${TOTP_ENCRYPTION_KEY:=$(openssl rand -base64 32 | tr '/+' '_-' | tr -d '\n')}"
        printf "SECRET_KEY='%s'\nTOTP_ENCRYPTION_KEY='%s'\n" \
            "$SECRET_KEY" "$TOTP_ENCRYPTION_KEY" > "$SECRET_FILE"
        chmod 600 "$SECRET_FILE"
    fi
fi

export SECRET_KEY TOTP_ENCRYPTION_KEY
exec "$@"
