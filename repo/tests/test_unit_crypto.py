"""Unit tests for backend/crypto.py — key management, hashing, encryption, masking."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_key_cache():
    """Clear the module-level _KEY cache so each test gets a fresh key."""
    import backend.crypto as _c
    _c._KEY = None


@pytest.fixture(autouse=True)
def _isolate_crypto(tmp_path, monkeypatch):
    """Point data_dir() into tmp_path and reset the cached key before every test."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _reset_key_cache()
    yield
    _reset_key_cache()


# ---------------------------------------------------------------------------
# load_or_create_key
# ---------------------------------------------------------------------------

class TestLoadOrCreateKey:
    def test_load_or_create_key_creates_new(self, tmp_path):
        from backend.crypto import load_or_create_key
        from backend import config

        key_file = config.key_path()
        assert not key_file.exists()
        key = load_or_create_key()
        assert key_file.exists()
        assert len(key) == 32

    def test_load_or_create_key_reads_existing(self, tmp_path):
        from backend.crypto import load_or_create_key
        from backend import config

        key_file = config.key_path()
        key_file.parent.mkdir(parents=True, exist_ok=True)
        existing = secrets.token_bytes(32)
        key_file.write_bytes(existing)

        key = load_or_create_key()
        assert key == existing

    def test_key_is_32_bytes(self):
        from backend.crypto import load_or_create_key

        key = load_or_create_key()
        assert isinstance(key, bytes)
        assert len(key) == 32


# ---------------------------------------------------------------------------
# hash_password / verify_password
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_hash_password_returns_tuple(self):
        from backend.crypto import hash_password

        result = hash_password("s3cret")
        assert isinstance(result, tuple)
        assert len(result) == 2
        h, salt = result
        assert isinstance(h, bytes)
        assert isinstance(salt, bytes)

    def test_hash_password_deterministic_with_same_salt(self):
        from backend.crypto import hash_password

        salt = secrets.token_bytes(16)
        h1, _ = hash_password("same_pass", salt)
        h2, _ = hash_password("same_pass", salt)
        assert h1 == h2

    def test_hash_password_different_with_different_salt(self):
        from backend.crypto import hash_password

        h1, s1 = hash_password("same_pass")
        h2, s2 = hash_password("same_pass")
        # Salts are independently random so hashes will differ.
        assert s1 != s2
        assert h1 != h2

    def test_verify_password_correct(self):
        from backend.crypto import hash_password, verify_password

        h, salt = hash_password("correct_horse")
        assert verify_password("correct_horse", h, salt) is True

    def test_verify_password_incorrect(self):
        from backend.crypto import hash_password, verify_password

        h, salt = hash_password("correct_horse")
        assert verify_password("wrong_horse", h, salt) is False


# ---------------------------------------------------------------------------
# encrypt_field / decrypt_field
# ---------------------------------------------------------------------------

class TestFieldEncryption:
    def test_encrypt_decrypt_field_roundtrip(self):
        from backend.crypto import encrypt_field, decrypt_field

        original = "Sensitive Data 123!"
        token = encrypt_field(original)
        assert decrypt_field(token) == original

    def test_encrypt_field_none_returns_none(self):
        from backend.crypto import encrypt_field

        assert encrypt_field(None) is None

    def test_encrypt_field_empty_returns_empty(self):
        from backend.crypto import encrypt_field

        assert encrypt_field("") == ""

    def test_encrypt_field_produces_v1_prefix(self):
        from backend.crypto import encrypt_field, HAVE_AESGCM

        token = encrypt_field("hello")
        if HAVE_AESGCM:
            assert token.startswith("v1:")
        else:
            assert token.startswith("v0:")

    def test_decrypt_field_invalid_returns_none(self):
        from backend.crypto import decrypt_field, HAVE_AESGCM

        if HAVE_AESGCM:
            # Corrupted v1 token
            assert decrypt_field("v1:not_valid_base64!!!") is None
        else:
            assert decrypt_field("v0:not_valid_base64!!!") is None

    def test_decrypt_field_cleartext_passthrough(self):
        from backend.crypto import decrypt_field

        assert decrypt_field("plain_value_no_prefix") == "plain_value_no_prefix"


# ---------------------------------------------------------------------------
# encrypt_bytes_at_rest / decrypt_bytes_at_rest
# ---------------------------------------------------------------------------

class TestBytesAtRest:
    def test_encrypt_decrypt_bytes_at_rest_roundtrip(self):
        from backend.crypto import encrypt_bytes_at_rest, decrypt_bytes_at_rest

        raw = b"some binary payload \x00\xff"
        blob = encrypt_bytes_at_rest(raw)
        assert decrypt_bytes_at_rest(blob) == raw

    def test_encrypted_bytes_have_magic(self):
        from backend.crypto import encrypt_bytes_at_rest, HAVE_AESGCM

        blob = encrypt_bytes_at_rest(b"test payload")
        if HAVE_AESGCM:
            assert blob[:7] == b"CRHGC1\x00"
        else:
            assert blob[:7] == b"CRHGC0\x00"


# ---------------------------------------------------------------------------
# encrypt_file_at_rest / decrypt_file_at_rest
# ---------------------------------------------------------------------------

class TestFileAtRest:
    def test_encrypt_decrypt_file_at_rest_roundtrip(self, tmp_path):
        from backend.crypto import encrypt_file_at_rest, decrypt_file_at_rest

        plain_path = tmp_path / "plain.bin"
        enc_path = tmp_path / "encrypted.bin"
        dec_path = tmp_path / "decrypted.bin"

        content = b"Hello, file-level encryption!"
        plain_path.write_bytes(content)

        encrypt_file_at_rest(plain_path, enc_path)
        assert enc_path.exists()
        assert enc_path.read_bytes() != content  # must be transformed

        decrypt_file_at_rest(enc_path, dec_path)
        assert dec_path.read_bytes() == content


# ---------------------------------------------------------------------------
# Masking helpers
# ---------------------------------------------------------------------------

class TestMaskEmail:
    def test_mask_email_standard(self):
        from backend.crypto import mask_email

        assert mask_email("john@example.com") == "j***@example.com"

    def test_mask_email_empty(self):
        from backend.crypto import mask_email

        assert mask_email(None) == ""
        assert mask_email("") == ""

    def test_mask_email_no_at(self):
        from backend.crypto import mask_email

        assert mask_email("noatsign") == "***"


class TestMaskPhone:
    def test_mask_phone_standard(self):
        from backend.crypto import mask_phone

        assert mask_phone("555-867-5309") == "(***) ***-5309"

    def test_mask_phone_empty(self):
        from backend.crypto import mask_phone

        assert mask_phone(None) == ""
        assert mask_phone("") == ""

    def test_mask_phone_short(self):
        from backend.crypto import mask_phone

        assert mask_phone("12") == "***"


class TestMaskSSN:
    def test_mask_ssn_standard(self):
        from backend.crypto import mask_ssn_last4

        assert mask_ssn_last4("1234") == "***-**-1234"

    def test_mask_ssn_empty(self):
        from backend.crypto import mask_ssn_last4

        assert mask_ssn_last4(None) == ""
        assert mask_ssn_last4("") == ""
