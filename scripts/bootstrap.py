#!/usr/bin/env python3
"""Attach this repository to an existing cluster; never overwrite credentials."""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def kubectl(*args, data=None):
    result = subprocess.run(['kubectl', *args], input=data, text=True,
                            capture_output=True, check=False)
    if result.returncode:
        # Do not print request payloads: they may contain credentials.
        raise RuntimeError(f"kubectl {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def create_secret(namespace, name, values):
    existing = kubectl('-n', namespace, 'get', 'secret', name,
                       '--ignore-not-found', '-o', 'json')
    if existing.strip():
        keys = json.loads(existing).get('data', {})
        missing = set(values) - set(keys)
        if missing or any(not keys[k] for k in values if k in keys):
            raise RuntimeError(f'{namespace}/{name} is incomplete; repair it explicitly.')
        print(f'Preserved {namespace}/{name}')
        return
    payload = {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
               'metadata': {'name': name, 'namespace': namespace}, 'stringData': values}
    kubectl('create', '-f', '-', data=json.dumps(payload))
    print(f'Created {namespace}/{name}')


def token():
    return secrets.token_urlsafe(32)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admin-email', help='Initial Open WebUI administrator email')
    parser.add_argument('--skip-wait', action='store_true', help='Attach Flux without waiting for AI readiness')
    args = parser.parse_args()
    print('Context:', kubectl('config', 'current-context').strip())
    for name in ('cilium', 'gateway', 'storage-classes', 'storage-cnpg'):
        kubectl('-n', 'flux-system', 'wait', 'kustomization/'+name,
                '--for=condition=ready', '--timeout=60s')
    for name in ('longhorn', 'longhorn-cnpg'):
        kubectl('get', 'storageclass', name)
    settings = json.loads(kubectl('-n', 'flux-system', 'get', 'configmap',
                                 'cluster-settings', '-o', 'json'))['data']
    domain = settings['DOMAIN']
    email = args.admin_email or 'admin@'+domain
    if '@' not in email or any(c.isspace() for c in email):
        raise RuntimeError('Provide a valid administrator email.')
    kubectl('apply', '-k', str(ROOT/'infrastructure/foundation'))
    create_secret('ai-system', 'webui-auth', {
        'email': email, 'password': token(), 'secret-key': token()})
    create_secret('ai-system', 'litellm-auth', {
        'master-key': 'sk-'+token(), 'salt-key': token(),
        'username': 'admin', 'password': token()})
    create_secret('ai-system', 'qdrant-auth', {'api-key': token()})
    create_secret('ai-system', 'searxng-auth', {'secret-key': token()})
    create_secret('ai-system', 'vllm-auth', {'api-key': token()})
    create_secret('ai-workflows', 'langflow-auth', {
        'username': 'admin', 'password': token(), 'secret-key': token()})
    create_secret('ai-notebooks', 'notebook-auth', {'token': token()})
    password = token()
    auth_config = ('[mlflow]\n'
                   'default_permission = NO_PERMISSIONS\n'
                   'database_uri = sqlite:////mlflow/auth.db\n'
                   'admin_username = admin\n'
                   f'admin_password = {password}\n'
                   'authorization_function = mlflow.server.auth:authenticate_request_basic_auth\n')
    create_secret('ai-tracking', 'mlflow-auth', {
        'username': 'admin', 'password': password, 'secret-key': token(),
        'basic_auth.ini': auth_config})
    kubectl('apply', '-k', str(ROOT/'bootstrap'))
    if not args.skip_wait:
        kubectl('-n', 'flux-system', 'wait', 'gitrepository/ai-addons',
                '--for=condition=ready', '--timeout=5m')
        kubectl('-n', 'flux-system', 'wait', 'kustomization/ai-addons',
                '--for=condition=ready', '--timeout=5m')
        for name in ('ai-foundation', 'ai-databases', 'ai-ollama', 'ai-models',
                     'ai-qdrant', 'ai-search', 'ai-documents', 'ai-litellm',
                     'ai-webui', 'ai-routes'):
            kubectl('-n', 'flux-system', 'wait', 'kustomization/'+name,
                    '--for=condition=ready', '--timeout=120m')
    print(f'Flux attached. Chat URL: https://chat.{domain}')
    print('Read docs/operations.md for credential retrieval and live acceptance checks.')
    print('Only committed changes on bootstrap/source.yaml\'s branch are deployed.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, KeyError, FileNotFoundError) as error:
        print(f'Bootstrap stopped: {error}', file=sys.stderr)
        sys.exit(1)
