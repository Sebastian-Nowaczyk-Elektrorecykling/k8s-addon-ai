# Profiles and integrations

## Reconciliation

The `ai-addons` root owns the source, settings and child Flux objects. It has no
post-build substitution: each child expands `cluster-settings` and `ai-settings`
when rendering its own workloads. This avoids consuming template variables too
early. Core sequencing is:

| Child | Depends on |
| --- | --- |
| `ai-foundation` | Existing `cilium` |
| `ai-databases` | Foundation, existing CNPG and storage classes |
| `ai-ollama` | Foundation, storage classes |
| `ai-models` | Ollama; pulls the chat and embedding models |
| `ai-qdrant` | Foundation, storage classes |
| `ai-search`, `ai-documents` | Foundation |
| `ai-litellm` | Database and completed model pull |
| `ai-webui` | LiteLLM, Qdrant, search, document extraction, storage |
| `ai-routes` | WebUI and existing Gateway |

The model Job has a two-hour limit and no TTL, so Flux does not repeatedly
download models. Its force annotation allows replacement when its immutable
template changes. Updating model settings recreates the Job and updates the
relevant pod templates. Old weights are not automatically deleted.

Do not edit a rendered `.cache/` file. ConfigMaps for LiteLLM and SearXNG are
generated with name hashes so config changes restart their consumers.

## Visual workflows, notebooks and tracking

The optional Flux objects already exist but are suspended. In
`clusters/lan/optional.yaml`, change `suspend: true` to `suspend: false` for any of:

| Child | Adds | Additional PVC capacity | Memory requests / limits, approximately |
| --- | --- | --- | --- |
| `ai-langflow` | Langflow + CNPG | 5 + 10 GiB | 1.25 / 5 GiB |
| `ai-notebook` | JupyterLab/SciPy | 20 GiB | 0.5 / 4 GiB |
| `ai-mlflow` | MLflow + CNPG | 20 + 10 GiB | 0.5 / 3 GiB |

Commit/push, then inspect `bash scripts/status.sh`. Optional credentials are
created by bootstrap even while their services are suspended.

For Langflow's OpenAI component or a notebook SDK, use:

```text
Base URL: http://litellm.ai-system.svc.cluster.local:4000/v1
Model:    local-chat
API key:  a dedicated LiteLLM virtual key restricted to the required models
```

Use `local-embeddings` with an embeddings component. The workflow namespace is
allowed to reach LiteLLM, not the private Ollama or WebUI vector store. Create a
separate Qdrant collection/service and explicit policy before sharing vector
storage with arbitrary workflows. Credentials saved in Langflow are protected
by its persistent secret key; preserve that Secret with the database.

The notebook has no mounted API master key, no cluster token, and no host mounts.
Install the required client libraries into the workspace deliberately; no pip
install runs at pod startup. Save notebooks under `/home/jovyan/work`.

MLflow clients can use `http://mlflow.ai-tracking.svc.cluster.local:5000` from the
notebook/workflow namespaces, with a dedicated MLflow username and password.
Create users and grant experiment/model permissions through the MLflow auth API.
New users have `NO_PERMISSIONS`; its initial administrator creates resources and
grants access. Both PostgreSQL tracking state and the PVC-backed auth database
must be backed up. Artifact serving goes through the authenticated tracking
server. [examples/clients.py](../examples/clients.py) exercises the local LLM API.

## NVIDIA acceleration for Ollama

1. Prepare the GPU host with the base repository's NVIDIA workflow and verify
   `nvidia-smi` on the host. Check `kubectl get runtimeclass nvidia`. Restart k3s
   after installing the toolkit if needed so its containerd discovers the runtime.
2. Label only GPU workers that passed those checks:

   ```bash
   kubectl label node YOUR_GPU_WORKER nvidia.com/gpu.present=true
   ```

3. Unsuspend `ai-nvidia` in `clusters/lan/optional.yaml`, commit/push, and wait for
   the device plugin. There is no GPU Operator, NFD, driver install or runtime
   replacement. The namespace permits the host access required by the plugin.
4. Verify a node advertises `nvidia.com/gpu` in `kubectl describe node`.
5. Change `ai-ollama.spec.path` to `./apps/ollama/nvidia` in `clusters/lan/core.yaml`
   and append `{name: ai-nvidia}` to its `dependsOn`. Commit/push.

The overlay requests one whole NVIDIA GPU, uses `runtimeClassName: nvidia`,
retains the model PVC, and raises the memory limit to 16 GiB. It tolerates a
`nvidia.com/gpu` NoSchedule taint, not control-plane taints. Small-model GPU use
depends on the device, driver and available VRAM; verify with an actual request
and `ollama ps`. AMD/Intel-specific device plugins are not installed.

To return to CPU, restore the CPU path and remove that GPU dependency. Leave
the device plugin running if other GPU workloads need it.

## vLLM

Complete the GPU prerequisite steps, then:

1. Unsuspend `ai-vllm` as well as `ai-nvidia`.
2. Review `AI_VLLM_MODEL` (default `Qwen/Qwen3-4B`), available VRAM, CUDA/driver
   compatibility and the limits in `optional/vllm/resources.yaml`. Budget one
   GPU, 4 GiB host memory requested / 16 GiB limit and a 50 GiB weight cache.
   Expect to need around 12–16 GiB VRAM for the sample model and KV cache; measure
   on your GPU. New vLLM releases may not support older GPU architectures.
3. Change `ai-litellm.spec.path` to `./optional/litellm-vllm` and append
   `{name: ai-vllm}` to its dependencies. Commit/push.

The API then lists `local-vllm`. Access is mediated by LiteLLM and the backend's
own API key. A one-hour startup probe accommodates the initial download.
For gated models, obtain access and add a separate `HF_TOKEN` Secret reference;
the default public model needs none. No `trust_remote_code` flag is enabled.

Ollama CPU + vLLM GPU can coexist on one GPU. Ollama GPU + vLLM GPU each reserve
one device: with only one allocatable GPU, one pod stays Pending. Do not enable
sharing simply to suppress that scheduling signal.

## Garage artifacts for MLflow

The default MLflow profile works with its PVC artifact directory. To use the
existing Garage instead:

1. Create an `ai-mlflow` bucket and a dedicated read/write key in Garage, following
   the storage repository's operations guide. The endpoint is
   `http://garage.garage.svc.cluster.local:3900`, region `garage`.
2. Create `mlflow-s3` in `ai-tracking` with keys `access-key-id` and
   `secret-access-key` through your secret manager or `kubectl` locally. Never
   commit them or pass them to notebook clients.
3. Change `ai-mlflow.spec.path` to `./optional/mlflow-garage`, and append
   `{name: storage-garage}` to its dependencies. Unsuspend it and commit/push.

The server proxies artifacts to `s3://ai-mlflow`. An independent artifact backup
still matters: Garage's initial deployment is in the same failure domain. Use
this profile before creating experiments. Existing experiments retain their
artifact locations; changing the destination does not migrate old artifacts.
The PVC is retained for MLflow authentication state in either profile.

## Cloud providers and observability

Add provider-specific Secrets and entries in `apps/litellm/config.yaml` using
`os.environ/KEY_NAME`. Mount only the keys needed by LiteLLM. Keep models and
virtual-key budgets explicit. The vLLM overlay replaces this config; update its
copy too if that profile is active. Read the provider's data handling and billing
terms before sending organizational content. No cloud provider is configured.

LiteLLM's UI supplies request usage/spend accounting; MLflow adds experiment and
trace tools when enabled. Flux conditions, Events and pod logs provide deployment
health. No second Prometheus/Grafana stack is installed. If one already exists,
add ServiceMonitor/PodMonitor resources in its repository with matching namespace
selectors and NetworkPolicy access; Qdrant exposes `/metrics` on 6333, vLLM on
8000, and CNPG exposes its own metrics. Verify authentication requirements before
scraping. Do not expose raw metrics through the user Gateway.

## Disabling and removing

`suspend: true` pauses reconciliation; it **does not stop or uninstall pods**.
To stop a service, scale its Deployment to zero in Git first, reconcile, and
then suspend its child if necessary. Database/storage shutdown needs its own
maintenance plan. Retain required dependencies while consumers run.

Deleting a child or root Flux object orphans its managed resources. Removing an
application resource from an active child's manifest prunes it except for
protected PVCs, namespaces and CNPG Clusters. Explicit data deletion is manual
after verified backups. The Longhorn StorageClasses use `Delete` reclaim policy:
manually deleting a PVC can destroy its data.
