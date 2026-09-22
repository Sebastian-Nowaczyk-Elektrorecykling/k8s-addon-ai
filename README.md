# AI add-ons for Elektro Kubernetes

A self-hosted AI suite reconciled by Flux, attached as a third Git source to
[minimum-k8s-net-elektro](https://github.com/Sebastian-Nowaczyk-Elektrorecykling/minimum-k8s-net-elektro)
and [k8s-addon-storage](https://github.com/Sebastian-Nowaczyk-Elektrorecykling/k8s-addon-storage).
It reuses Cilium, the internal HTTPS Gateway, Longhorn and CloudNativePG. No
changes to those repositories or second Flux installation are needed.

## Included

| Component | Version | Default | Purpose |
| --- | --- | --- | --- |
| Ollama | 0.34.2 | On, CPU | Local chat and embedding models; optional NVIDIA profile |
| Open WebUI | 0.11.4 | On | Authenticated chat, document RAG and web search |
| LiteLLM | 1.101.0 | On | OpenAI-compatible API, virtual keys, model routing and usage accounting |
| Qdrant | 1.19.1 | On | Persistent, API-key-protected vector store for Open WebUI |
| SearXNG | 2026.9.22-019460e07 | On | Private JSON search backend for chat |
| Apache Tika | 3.3.1.0-full | On | Document extraction, including bundled OCR tooling |
| Langflow | 1.12.2 | Opt-in | Authenticated visual AI workflows and agents |
| JupyterLab / SciPy notebook | Lab 4.6.3 | Opt-in | Persistent, token-protected Python workspace |
| MLflow | 3.16.1-full | Opt-in | Experiments, traces, evaluations, registry and artifacts |
| vLLM | 0.30.0 | Opt-in | GPU model serving behind LiteLLM |
| NVIDIA device plugin | chart 0.20.0 | Opt-in | Advertises GPUs prepared by the base host scripts |

Application images are pinned to registry-verified digests in
[config/images.lock.json](config/images.lock.json). This is an initial integration,
validated by rendering and schema checks, **not yet exercised on a live cluster**.

The default downloads `qwen3:1.7b` for chat and `nomic-embed-text:v1.5` for
embeddings, then exposes them as `local-chat` and `local-embeddings`. Model tags
are configurable and upstream-mutable; they are not immutable weight digests.
No paid provider, GPU, public ingress, or external API key is required.

## Install

Prerequisites:

- The base `cilium` and `gateway` and storage `storage-classes` and `storage-cnpg`
  Flux Kustomizations must be Ready in `flux-system`.
- `longhorn` and `longhorn-cnpg` StorageClasses must be usable. The storage repo's
  defaults have one replica. They do not protect against disk/node loss.
- At least one schedulable worker/hybrid; dedicated controller taints are not
  tolerated by these application workloads. Plan roughly **4 GiB of requested
  RAM, 1.1 CPU requested and 80 GiB of provisioned storage** for the core. Core
  memory limits total approximately 19 GiB; requests are not peak requirements.
  Start with 12–16 GiB of available worker RAM for the small CPU model, then
  measure usage. Leave capacity for Kubernetes and the storage add-on.
- Internal wildcard DNS and the base cluster CA trusted on client machines.
- Outbound HTTPS access to image/model registries; search additionally needs
  Internet access. Initial image/model downloads can take considerable time.
- Python 3.11+, `kubectl`, a suitable kubeconfig, and permission to create the
  add-on resources and Secrets. On a k3s host, use its cluster-admin kubeconfig.

```bash
git clone https://github.com/Sebastian-Nowaczyk-Elektrorecykling/k8s-addon-ai.git
cd k8s-addon-ai
kubectl config current-context
bash scripts/bootstrap.sh --admin-email you@example.com
```

The script checks dependencies, creates missing credentials without printing
them, preserves existing Secrets, attaches Flux, and waits for the core. Reruns
do not reset passwords. `--skip-wait` returns after attachment. Secrets can also
be supplied through an external secret manager; names and keys are documented
in [operations](docs/operations.md). No secret values belong in Git.

Flux deploys the committed `main` branch, **not local edits**. Commit and push
configuration changes first. For a fork, edit `bootstrap/source.yaml`; a private
source also needs a read-only Git credential Secret and `spec.secretRef`.

| URL with the base domain `internal` | Login |
| --- | --- |
| `https://chat.internal` | Email supplied at bootstrap and generated WebUI password |
| `https://llm.internal/ui` | LiteLLM `admin` and generated password |
| `https://llm.internal/v1` | Bearer API key; create scoped virtual keys in LiteLLM |
| `https://flows.internal` | Optional Langflow `admin` and generated password |
| `https://notebook.internal` | Optional Jupyter token |
| `https://mlflow.internal` | Optional MLflow `admin` and generated password |

Retrieve the initial chat password locally:

```bash
kubectl -n ai-system get secret webui-auth -o jsonpath='{.data.password}' | base64 -d
printf '\n'
```

Use the login screen, then create additional accounts as administrator. Public
sign-up is disabled. Change initial passwords through each application's account
controls; bootstrap credentials only initialize new user databases.

## Configuration and optional services

Edit [clusters/lan/settings.yaml](clusters/lan/settings.yaml) for storage and model
choices. The domain comes from the existing `cluster-settings` ConfigMap; this
repository does not own it. See [profiles](docs/profiles.md) for exact activation
steps, hardware requirements and Garage S3 integration.

For Langflow, JupyterLab or MLflow, set that component's `spec.suspend: false` in
[clusters/lan/optional.yaml](clusters/lan/optional.yaml), commit, and push. They
have isolated namespaces and application authentication. JupyterLab is one
trusted user's workspace, not a multi-tenant JupyterHub deployment.

Ollama can be switched to its NVIDIA overlay. vLLM is a separate opt-in deployment
with a corresponding LiteLLM overlay. Enabling both GPU servers requires two
allocatable GPUs unless you explicitly design GPU sharing. This repo does not
install host drivers, replace the base container runtime, or enable time slicing.

## Data and security boundaries

- WebUI's SQLite database/uploads, models, vectors, notebooks and artifacts use
  Longhorn PVCs. LiteLLM and optional Langflow/MLflow use separate single-instance
  CNPG databases on `longhorn-cnpg`; the existing operator supplies its PostgreSQL
  image and generates each application's database Secret.
- PVCs, CNPG Clusters and namespaces carry Flux prune protection. Child Flux
  objects use `deletionPolicy: Orphan`. Ordinary application resources can be
  pruned, but uninstalling the root does not wipe data. This is not a backup.
- No backup schedules are installed. Follow [operations](docs/operations.md)
  before storing irreplaceable data; the storage add-on also starts without
  configured backups.
- Only authenticated frontends/API Gateway have HTTPS routes. Ollama, Qdrant,
  Tika, SearXNG and vLLM remain ClusterIP-only with explicit ingress policies.
  Gateway policies allow Cilium's reserved `ingress` identity, not merely pods
  in `gateway-system`. No application receives a Kubernetes service account token.
- Egress is allowed: model downloads, web retrieval and provider calls need it.
  This is not an egress sandbox. Workflow/notebook authors must be trusted;
  their code can reach the network. Do not give them administrative API keys.
- WebUI's trusted backend initially uses the LiteLLM master key. Give other
  clients scoped virtual keys. See the procedure to replace WebUI's key in
  [operations](docs/operations.md). Cloud providers require an explicit config
  change and credentials; none receive data by default. Search queries do leave
  the cluster through upstream search engines.
- Application databases are single-replica baselines. There is no claim of HA,
  production hardening, or audited multi-tenant isolation.

## Validate

Install Python 3.11+, Kustomize 5.7.1, Helm 3.19.0 and kubeconform 0.7.0:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python3 scripts/validate.py
```

Validation builds every active and optional profile, renders the pinned NVIDIA
chart, validates against Kubernetes 1.36 and pinned Flux/Cilium/Gateway/CNPG CRDs,
checks dependency cycles and service/route wiring, and tests credential
preservation. It downloads charts/schemas into `.cache/`, never contacts a cluster,
and runs in GitHub Actions. Live acceptance includes streamed chat, document RAG,
search, authentication, network policy and storage recovery; see operations.

Upstream release/configuration references and inspected base revisions are in
[docs/sources.md](docs/sources.md).
