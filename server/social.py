"""Verify Apple / Google identity tokens (RS256 JWTs) against the providers' JWKS."""
import time

import httpx
from jose import jwt

_CACHE: dict[str, tuple[float, dict]] = {}
APPLE_JWKS = "https://appleid.apple.com/auth/keys"
GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"


def _jwks(url: str) -> dict:
    hit = _CACHE.get(url)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    r = httpx.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    _CACHE[url] = (time.time(), data)
    return data


def _verify(token: str, url: str, audiences: list[str], issuers: list[str]) -> dict:
    if not audiences:
        raise ValueError("provider disabled")
    kid = jwt.get_unverified_header(token).get("kid")
    keys = _jwks(url)["keys"]
    key = next((k for k in keys if k.get("kid") == kid), None)
    if key is None:  # rotated keys: refresh once
        _CACHE.pop(url, None)
        key = next((k for k in _jwks(url)["keys"] if k.get("kid") == kid), None)
    if key is None:
        raise ValueError("unknown signing key")
    claims = jwt.decode(token, key, algorithms=["RS256"], options={"verify_aud": False, "verify_at_hash": False})
    if claims.get("iss") not in issuers:
        raise ValueError("bad issuer")
    aud = claims.get("aud")
    if (aud if isinstance(aud, str) else None) not in audiences and not (isinstance(aud, list) and set(aud) & set(audiences)):
        raise ValueError("bad audience")
    return claims


def verify_apple(token: str, audiences: list[str]) -> dict:
    return _verify(token, APPLE_JWKS, audiences, ["https://appleid.apple.com"])


def verify_google(token: str, audiences: list[str]) -> dict:
    return _verify(token, GOOGLE_JWKS, audiences, ["https://accounts.google.com", "accounts.google.com"])
