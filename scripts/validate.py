#!/usr/bin/env python3
"""Build every profile, check wiring, render the GPU chart, and validate schemas."""
import concurrent.futures
import json
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request
import yaml

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT/'.cache'
SCHEMAS = CACHE/'schemas'
RENDERED = CACHE/'rendered'
KUBE_VERSION = '1.36.0'
EXTERNAL = {'cilium', 'gateway', 'storage-classes', 'storage-cnpg', 'storage-garage'}


def run(*args):
    return subprocess.check_output(args, text=True, cwd=ROOT)


def documents(text):
    return [d for d in yaml.safe_load_all(text) if d]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def substitute(text, settings):
    # This repository only uses plain ${NAME} and Flux's $${NAME} shell escape.
    sentinel = '__FLUX_ESCAPED_DOLLAR__'
    text = text.replace('$${', sentinel+'{')
    def replace(match):
        key = match.group(1)
        require(key in settings, f'Missing Flux substitution: {key}')
        return settings[key]
    text = re.sub(r'\$\{([A-Za-z_][A-Za-z_0-9]*)\}', replace, text)
    return text.replace(sentinel+'{', '${')


def download(url, name):
    path = CACHE/name
    if not path.exists():
        with urllib.request.urlopen(url, timeout=90) as response:
            data = response.read()
        path.write_bytes(data)
    return path.read_text()


def save_schemas(text):
    for d in documents(text):
        if d.get('kind') != 'CustomResourceDefinition':
            continue
        spec = d['spec']
        for version in spec['versions']:
            schema = version.get('schema', {}).get('openAPIV3Schema')
            if schema:
                name = f"{spec['group']}_{spec['names']['kind'].lower()}_{version['name']}.json"
                (SCHEMAS/name).write_text(json.dumps(schema))


def check_wiring(docs):
    keys = [(d['apiVersion'], d['kind'], d['metadata'].get('namespace'), d['metadata']['name']) for d in docs]
    require(len(keys) == len(set(keys)), 'Duplicate resource identity in a rendered target')
    for d in docs:
        kind, name = d['kind'], d['metadata']['name']
        require(kind != 'Secret', f'Plaintext Secret committed: {name}')
        if kind in ('PersistentVolumeClaim', 'Cluster', 'Namespace'):
            require(d['metadata'].get('annotations', {}).get('kustomize.toolkit.fluxcd.io/prune') == 'disabled', f'Unprotected persistent resource: {name}')
        if kind == 'Cluster':
            require(d['spec']['storage']['storageClass'] == 'longhorn-cnpg', 'CNPG class mismatch')
        if kind in ('Deployment', 'Job'):
            pod = d['spec']['template']['spec']
            require(pod.get('automountServiceAccountToken') is False, f'Unnecessary API token: {name}')
            require(not any('hostPath' in v for v in pod.get('volumes', [])), f'Host access: {name}')
            for c in pod.get('containers', []) + pod.get('initContainers', []):
                require('@sha256:' in c['image'], f'Unpinned application image: {name}')
                require(c.get('resources', {}).get('requests'), f'Missing requests: {name}')
                require(c.get('resources', {}).get('limits', {}).get('memory'), f'Missing memory limit: {name}')
                require(not c.get('securityContext', {}).get('privileged'), f'Privileged application: {name}')
            if kind == 'Deployment':
                require(d['spec']['strategy']['type'] == 'Recreate', f'RWO rollout hazard: {name}')
                c = pod['containers'][0]
                require(all(p in c for p in ('startupProbe', 'readinessProbe', 'livenessProbe')), f'Missing probes: {name}')
        if kind == 'Service':
            require(d['spec'].get('type', 'ClusterIP') == 'ClusterIP', f'Unexpected external service: {name}')
            workloads = [w for w in docs if w['kind'] == 'Deployment' and w['metadata'].get('namespace') == d['metadata'].get('namespace') and all(w['spec']['template']['metadata']['labels'].get(k) == v for k,v in d['spec']['selector'].items())]
            require(workloads, f'No backend for Service {name}')
            ports = {p['name'] for w in workloads for c in w['spec']['template']['spec']['containers'] for p in c.get('ports', [])}
            require(all(p['targetPort'] in ports for p in d['spec']['ports']), f'Service port mismatch: {name}')


def check_graph(root):
    children = {d['metadata']['name']: d for d in root if d['kind'] == 'Kustomization' and d['apiVersion'].startswith('kustomize.toolkit')}
    require('postBuild' not in children['ai-addons']['spec'], 'Root must not prematurely substitute child templates')
    def visit(name, trail):
        require(name not in trail, f'Dependency cycle: {trail} -> {name}')
        for dep in children[name]['spec'].get('dependsOn', []):
            target = dep['name']
            require(target in children or target in EXTERNAL, f'Unknown dependency: {target}')
            if target in children:
                visit(target, trail+[name])
    for name in children:
        visit(name, [])
    for name in ('ai-nvidia', 'ai-vllm', 'ai-langflow', 'ai-notebook', 'ai-mlflow'):
        require(children[name]['spec'].get('suspend') is True, f'Heavy component enabled by default: {name}')
    require(children['ai-ollama']['spec']['path'] == './apps/ollama/cpu', 'Default must be CPU compatible')
    return children


def main():
    for tool in ('kustomize', 'kubeconform', 'helm'):
        require(shutil.which(tool), f'Install {tool}; see README.md')
    for directory in (CACHE, SCHEMAS, RENDERED):
        directory.mkdir(parents=True, exist_ok=True)
    settings = yaml.safe_load((ROOT/'clusters/lan/settings.yaml').read_text())['data'] | {'DOMAIN':'internal'}
    root = documents(run('kustomize', 'build', 'clusters/lan'))
    children = check_graph(root)
    paths = sorted({d['spec']['path'].removeprefix('./') for d in children.values()} | {
        'bootstrap', 'apps/ollama/nvidia', 'optional/mlflow-garage', 'optional/litellm-vllm'})
    rendered = {}
    for path in paths:
        raw = run('kustomize', 'build', path)
        output = raw if path in ('bootstrap','clusters/lan') else substitute(raw, settings)
        docs = documents(output)
        check_wiring(docs)
        rendered[path] = docs
        (RENDERED/(path.replace('/', '-')+'.yaml')).write_text(output)
        print(f'Built {path}: {len(docs)} resources', flush=True)
    # Verify route attachment, allowed namespace labels and backend names together.
    all_docs = [d for ds in rendered.values() for d in ds]
    expected_images = set(json.loads((ROOT/'config/images.lock.json').read_text())['images'].values())
    actual_images = {c['image'] for d in all_docs if d['kind'] in ('Deployment','Job')
                     for c in d['spec']['template']['spec'].get('containers', []) +
                     d['spec']['template']['spec'].get('initContainers', [])}
    require(actual_images == expected_images, 'Application image lock differs from manifests')
    namespaces = {d['metadata']['name']: d for d in all_docs if d['kind']=='Namespace'}
    services = {(d['metadata'].get('namespace'),d['metadata']['name']):d for d in all_docs if d['kind']=='Service'}
    for d in all_docs:
        if d['kind'] == 'HTTPRoute':
            ns = d['metadata']['namespace']
            require(namespaces[ns]['metadata']['labels']['elektro.internal/route-scope']=='applications', f'Gateway rejects namespace {ns}')
            require(d['spec']['parentRefs']==[{'name':'internal','namespace':'gateway-system','sectionName':'apps-https'}], 'Wrong Gateway listener')
            for rule in d['spec']['rules']:
                for ref in rule['backendRefs']:
                    svc = services[(ns, ref['name'])]
                    require(ref['port'] in [p['port'] for p in svc['spec']['ports']], 'Route port mismatch')
            require(any(p['kind']=='CiliumNetworkPolicy' and p['metadata']['namespace']==ns and p['spec']['endpointSelector']['matchLabels'].get('app.kubernetes.io/name')==d['metadata']['name'] and p['spec']['ingress'][0]['fromEntities']==['ingress'] for p in all_docs), 'Missing Cilium ingress identity allowance')
    # Render the only Helm chart, using the same pinned version and values as Flux.
    hr = next(d for d in rendered['optional/nvidia'] if d['kind']=='HelmRelease')
    values = CACHE/'nvidia-values.yaml'; values.write_text(yaml.safe_dump(hr['spec']['values']))
    chart = CACHE/'charts'; chart.mkdir(exist_ok=True)
    version = hr['spec']['chart']['spec']['version']
    package = chart/f'nvidia-device-plugin-{version}.tgz'
    if not package.exists():
        run('helm','pull','nvidia-device-plugin','--repo','https://nvidia.github.io/k8s-device-plugin','--version',version,'--destination',str(chart))
    gpu = run('helm','template','nvidia-device-plugin',str(package),'--namespace','ai-gpu-system','--kube-version',KUBE_VERSION,'--values',str(values))
    post = CACHE/'nvidia-post-render'; post.mkdir(exist_ok=True)
    (post/'chart.yaml').write_text(gpu)
    (post/'kustomization.yaml').write_text(yaml.safe_dump({
        'apiVersion':'kustomize.config.k8s.io/v1beta1','kind':'Kustomization',
        'resources':['chart.yaml'],
        'patches':hr['spec']['postRenderers'][0]['kustomize']['patches']}))
    gpu = run('kustomize','build',str(post))
    (RENDERED/'nvidia-chart.yaml').write_text(gpu)
    daemonsets = [d for d in documents(gpu) if d['kind']=='DaemonSet']
    require(len(daemonsets)==1, 'Unexpected GPU operator/NFD/MPS installation')
    pod = daemonsets[0]['spec']['template']['spec']
    require(pod['runtimeClassName']=='nvidia' and pod['nodeSelector']['nvidia.com/gpu.present']=='true', 'GPU plugin scheduling mismatch')
    sources = [
        ('https://github.com/fluxcd/flux2/releases/download/v2.9.5/install.yaml','flux-v2.9.5.yaml'),
        ('https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/v1.30.0/config/crd/bases/postgresql.cnpg.io_clusters.yaml','cnpg-v1.30.0.yaml'),
        ('https://raw.githubusercontent.com/cilium/cilium/v1.20.2/pkg/k8s/apis/cilium.io/client/crds/v2/ciliumnetworkpolicies.yaml','cilium-v1.20.2.yaml'),
        ('https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.1/standard-install.yaml','gateway-v1.6.1.yaml'),
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for text in pool.map(lambda pair:download(*pair), sources):
            save_schemas(text)
    # Validate rendered objects, not Kustomize configuration or unexpanded templates.
    combined = RENDERED/'all.yaml'
    combined.write_text(yaml.safe_dump_all(all_docs+documents(gpu),sort_keys=False))
    print(run('kubeconform','-strict','-summary','-kubernetes-version',KUBE_VERSION,
              '-schema-location',str(SCHEMAS/'{{.Group}}_{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'),
              '-schema-location','default',str(combined)),end='')
    run('bash','-n','scripts/bootstrap.sh','scripts/status.sh')
    run('python3','-m','unittest','discover','-s','tests','-v')
    print('Validation passed. Cluster execution and model quality still require live acceptance checks.')


if __name__ == '__main__':
    main()
