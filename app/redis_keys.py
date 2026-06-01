"""Centralised Redis key factory.

All Redis keys go through this module so that:
- Staging and production never collide (ENV prefix)
- Renaming a key pattern is a single-line change
- Tests can inspect exact key names
"""
import os

_ENV = os.environ.get('ENV', 'dev')
_P = f'{_ENV}:'          # e.g. "prod:", "dev:", "test:"

# User location state (geohash per user)
GEO_USER = f'{_P}user_geo:'       # + user_id  →  geohash
GEO_CELL = f'{_P}geo_cell:'       # + geohash  →  SET of user_ids

# Heartbeat / Dead Man's Switch
HB = f'{_P}user_hb:'              # + user_id  →  status string

# Auth / refresh token revocation
REFRESH_JTI = f'{_P}refresh_jti:' # + jti      →  user_id

# JWKS public-key caches (provider identity tokens)
JWKS_APPLE = f'{_P}jwks:apple'
JWKS_GOOGLE = f'{_P}jwks:google'

# Alarm rate-limiting (one per user per window)
ALARM_RATE = f'{_P}alarm_rate:'    # + user_id  →  '1' (with TTL)
