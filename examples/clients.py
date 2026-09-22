#!/usr/bin/env python3
"""Smoke-test a scoped LiteLLM client key; no SDK dependency or saved credentials."""
import json
import os
import urllib.request

base = os.environ.get('OPENAI_BASE_URL', 'https://llm.internal/v1').rstrip('/')
key = os.environ['OPENAI_API_KEY']


def request(path, payload=None):
    req = urllib.request.Request(base+path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization':'Bearer '+key, 'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=600) as response:
        return json.load(response)


print('Models:', [m['id'] for m in request('/models')['data']])
response = request('/chat/completions', {
    'model':'local-chat', 'messages':[{'role':'user','content':'Explain RAG in two sentences.'}],
    'max_tokens':200})
print(response['choices'][0]['message']['content'])
embedding = request('/embeddings', {'model':'local-embeddings','input':'Electronics recycling'})
print('Embedding dimensions:', len(embedding['data'][0]['embedding']))
