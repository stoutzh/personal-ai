import unittest
from unittest.mock import patch
from sdk_credentials import identity, read_key, CredentialError


class CredentialTests(unittest.TestCase):
    provider = {'endpoint': 'https://example.invalid/chat/completions', 'api_key_env': 'TEST_API_KEY'}

    def test_environment_takes_precedence(self):
        with patch.dict('os.environ', {'TEST_API_KEY': 'test-value'}, clear=True), patch('sdk_credentials.Keychain', side_effect=AssertionError('must not access Keychain')):
            self.assertEqual(read_key(self.provider), 'test-value')

    def test_keychain_fallback_and_access_denied(self):
        with patch.dict('os.environ', {}, clear=True), patch('sdk_credentials.sys.platform', 'darwin'), patch('sdk_credentials.Keychain') as vault:
            vault.return_value.read.return_value = 'stored-value'
            self.assertEqual(read_key(self.provider), 'stored-value')
            vault.return_value.read.assert_called_with(self.provider)
            vault.return_value.read.side_effect = CredentialError('denied')
            with self.assertRaises(CredentialError):
                read_key(self.provider)

    def test_different_endpoint_does_not_reuse_credential(self):
        self.assertNotEqual(identity(self.provider), identity({**self.provider, 'endpoint': 'https://other.invalid/chat/completions'}))
        self.assertNotEqual(identity(self.provider), identity({**self.provider, 'api_key_env': 'OTHER_KEY'}))


if __name__ == '__main__':
    unittest.main()
