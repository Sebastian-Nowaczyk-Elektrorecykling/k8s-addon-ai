import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bootstrap', Path(__file__).parents[1]/'scripts/bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class CredentialSafety(unittest.TestCase):
    def test_existing_credentials_are_never_rotated(self):
        with patch.object(bootstrap, 'kubectl', return_value=json.dumps({'data': {'password':'b2xk'}})) as command:
            bootstrap.create_secret('ai-system', 'auth', {'password':'new'})
            self.assertEqual(command.call_count, 1)
            self.assertIn('get', command.call_args.args)

    def test_failed_read_does_not_create_or_overwrite(self):
        with patch.object(bootstrap, 'kubectl', side_effect=RuntimeError('Forbidden')) as command:
            with self.assertRaisesRegex(RuntimeError, 'Forbidden'):
                bootstrap.create_secret('ai-system', 'auth', {'password':'new'})
            self.assertEqual(command.call_count, 1)

    def test_incomplete_existing_secret_stops(self):
        with patch.object(bootstrap, 'kubectl', return_value=json.dumps({'data': {}})) as command:
            with self.assertRaisesRegex(RuntimeError, 'incomplete'):
                bootstrap.create_secret('ai-system', 'auth', {'password':'new'})
            self.assertEqual(command.call_count, 1)

    def test_new_secret_uses_stdin_and_is_not_printed(self):
        with patch.object(bootstrap, 'kubectl', side_effect=['','created']) as command:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                bootstrap.create_secret('ai-system', 'auth', {'password':'sensitive-test-value'})
            self.assertNotIn('sensitive-test-value', out.getvalue())
            self.assertEqual(command.call_args.args, ('create','-f','-'))
            self.assertEqual(json.loads(command.call_args.kwargs['data'])['stringData']['password'], 'sensitive-test-value')


if __name__ == '__main__':
    unittest.main()
