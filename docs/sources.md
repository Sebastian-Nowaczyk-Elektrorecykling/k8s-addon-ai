# Source and compatibility notes

Inspected on 2026-09-22:

- Base cluster commit [`41126b0`](https://github.com/Sebastian-Nowaczyk-Elektrorecykling/minimum-k8s-net-elektro/commit/41126b04c18c18a3c192843e18b05cda8843c700):
  k3s 1.36.4, Flux 2.9.5, Cilium 1.20.2, Gateway API 1.6.1. Gateway
  `gateway-system/internal`, listener `apps-https`, namespace label
  `elektro.internal/route-scope=applications`, domain from `cluster-settings`.
- Storage commit [`f11ddf0`](https://github.com/Sebastian-Nowaczyk-Elektrorecykling/k8s-addon-storage/commit/f11ddf0910058ff7c336e52fabb18ea9e838d988):
  Longhorn classes `longhorn` and `longhorn-cnpg`, CNPG 1.30.0 and Garage endpoint
  `http://garage.garage.svc.cluster.local:3900`.

Primary upstream references:

- [Ollama Docker](https://docs.ollama.com/docker) and
  [0.34.2 release](https://github.com/ollama/ollama/releases/tag/v0.34.2).
- [Open WebUI configuration](https://docs.openwebui.com/reference/env-configuration/)
  and [0.11.4 release](https://github.com/open-webui/open-webui/releases/tag/v0.11.4).
- [LiteLLM configuration](https://docs.litellm.ai/docs/proxy/configs),
  [virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys) and
  [1.101.0 release](https://github.com/BerriAI/litellm/releases/tag/v1.101.0).
- [Qdrant 1.19.1](https://github.com/qdrant/qdrant/releases/tag/v1.19.1).
- [SearXNG container](https://docs.searxng.org/admin/installation-docker.html) and
  [server settings](https://docs.searxng.org/admin/settings/settings_server.html).
- [Apache Tika official images](https://hub.docker.com/r/apache/tika/tags).
- [Langflow environment](https://docs.langflow.org/environment-variables) and
  [1.12.2 image build](https://github.com/langflow-ai/langflow/blob/v1.12.2/docker/build_and_push.Dockerfile).
- [Jupyter Docker Stacks](https://jupyter-docker-stacks.readthedocs.io/en/latest/)
  and [official registry](https://quay.io/repository/jupyter/scipy-notebook).
- [MLflow 3.16.1](https://github.com/mlflow/mlflow/releases/tag/v3.16.1),
  [full image dependencies](https://github.com/mlflow/mlflow/blob/v3.16.1/docker/Dockerfile.full)
  and [authentication config](https://github.com/mlflow/mlflow/blob/v3.16.1/mlflow/server/auth/basic_auth.ini).
- [vLLM Kubernetes](https://docs.vllm.ai/en/latest/deployment/k8s/) and
  [0.30.0 release](https://github.com/vllm-project/vllm/releases/tag/v0.30.0).
- [NVIDIA 0.20.0 Helm values](https://github.com/NVIDIA/k8s-device-plugin/blob/v0.20.0/deployments/helm/nvidia-device-plugin/values.yaml).

Registry manifests were queried to resolve all committed application digests.
Tagged CNPG operator defaults remain controlled by the storage repository.
Hardware compatibility, upstream license terms (including models), performance
and application behavior must be assessed for the intended deployment. The
software suite is broad without installing overlapping Kubernetes distributions,
multiple GPU operators, an entire Kubeflow stack, or duplicate storage/monitoring
infrastructure.
