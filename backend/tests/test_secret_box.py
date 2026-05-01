from __future__ import annotations

from unittest import TestCase

from backend.app.core.secret_box import decrypt_secret, encrypt_secret, is_encrypted_secret


class SecretBoxTests(TestCase):
    def test_encrypt_secret_round_trips_and_does_not_store_plaintext(self) -> None:
        encrypted = encrypt_secret("sk-test-value", "stable-test-secret-key")

        self.assertTrue(is_encrypted_secret(encrypted))
        self.assertNotIn("sk-test-value", encrypted)
        self.assertEqual(decrypt_secret(encrypted, "stable-test-secret-key"), "sk-test-value")

    def test_wrong_secret_key_fails_authentication(self) -> None:
        encrypted = encrypt_secret("sk-test-value", "stable-test-secret-key")

        with self.assertRaises(ValueError):
            decrypt_secret(encrypted, "different-test-secret-key")

    def test_plaintext_values_are_left_readable_for_legacy_records(self) -> None:
        self.assertFalse(is_encrypted_secret("legacy-key"))
        self.assertEqual(decrypt_secret("legacy-key", ""), "legacy-key")

    def test_short_secret_key_is_rejected_for_new_encryption(self) -> None:
        with self.assertRaises(RuntimeError):
            encrypt_secret("sk-test-value", "short")
