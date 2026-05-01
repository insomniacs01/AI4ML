from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


ENCRYPTED_SECRET_PREFIX = "enc:v1:"
_SALT_BYTES = 16
_NONCE_BYTES = 16
_MAC_BYTES = 32
_PBKDF2_ITERATIONS = 200_000


def is_encrypted_secret(value: str | None) -> bool:
    return isinstance(value, str) and value.startswith(ENCRYPTED_SECRET_PREFIX)


def encrypt_secret(plaintext: str, secret_key: str) -> str:
    normalized = plaintext.strip()
    if not normalized:
        raise ValueError("secret value is empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    enc_key, mac_key = _derive_keys(secret_key, salt)
    ciphertext = _xor_bytes(normalized.encode("utf-8"), _keystream(enc_key, nonce))
    mac = hmac.new(mac_key, b"v1" + salt + nonce + ciphertext, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(salt + nonce + mac + ciphertext).decode("ascii")
    return f"{ENCRYPTED_SECRET_PREFIX}{token}"


def decrypt_secret(value: str, secret_key: str) -> str:
    if not is_encrypted_secret(value):
        return value
    _require_secret_key(secret_key)
    encoded = value.removeprefix(ENCRYPTED_SECRET_PREFIX)
    try:
        payload = base64.urlsafe_b64decode(encoded.encode("ascii"))
    except Exception as exc:
        raise ValueError("encrypted secret payload is not valid base64") from exc
    minimum_size = _SALT_BYTES + _NONCE_BYTES + _MAC_BYTES + 1
    if len(payload) < minimum_size:
        raise ValueError("encrypted secret payload is too short")
    salt = payload[:_SALT_BYTES]
    nonce = payload[_SALT_BYTES:_SALT_BYTES + _NONCE_BYTES]
    mac = payload[_SALT_BYTES + _NONCE_BYTES:_SALT_BYTES + _NONCE_BYTES + _MAC_BYTES]
    ciphertext = payload[_SALT_BYTES + _NONCE_BYTES + _MAC_BYTES:]
    enc_key, mac_key = _derive_keys(secret_key, salt)
    expected_mac = hmac.new(mac_key, b"v1" + salt + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected_mac):
        raise ValueError("encrypted secret authentication failed")
    plaintext = _xor_bytes(ciphertext, _keystream(enc_key, nonce))
    return plaintext.decode("utf-8")


def _derive_keys(secret_key: str, salt: bytes) -> tuple[bytes, bytes]:
    _require_secret_key(secret_key)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        secret_key.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
        dklen=64,
    )
    return derived[:32], derived[32:]


def _require_secret_key(secret_key: str) -> None:
    if len((secret_key or "").encode("utf-8")) < 16:
        raise RuntimeError("AI4ML_CONNECTOR_SECRET_KEY must be set to at least 16 bytes before storing encrypted connector keys.")


def _keystream(key: bytes, nonce: bytes):
    counter = 0
    while True:
        yield from hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1


def _xor_bytes(payload: bytes, stream) -> bytes:
    return bytes(byte ^ next(stream) for byte in payload)
