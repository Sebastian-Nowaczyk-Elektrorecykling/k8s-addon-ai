# Operations and acceptance

## Credentials

Bootstrap creates random values in the cluster, never in Git. It refuses to
replace existing or incomplete Secrets. Preserve these alongside data backups.

| Namespace | Secret | Keys |
| --- | --- | --- |
| ai-system | webui-auth | email, password, secret-key |
| ai-system | litellm-auth | master-key, salt-key, username, password |
| ai-system | qdrant-auth | api-key |
| ai-system | searxng-auth | secret-key |
| ai-system | vllm-auth | api-key |
| ai-workflows | langflow-auth | username, password, secret-key |
| ai-notebooks | notebook-auth | token |
| ai-tracking | mlflow-auth | username, password, secret-key, basic_auth.ini |
| ai-tracking | mlflow-s3 (Garage profile only) | access-key-id, secret-access-key |

CNPG generates `litellm-db-app`, `langflow-db-app` and `mlflow-db-app` in their
respective namespaces. Deployments consume their `uri` keys. Do not replace
those with unrelated passwords; use CNPG's credential rotation workflow.

Retrieve one credential at a time in a private terminal, for example:

```bash
kubectl -n ai-system get secret litellm-auth -o jsonpath='{.data.password}' | base64 -d
printf '\n'
kubectl -n ai-notebooks get secret notebook-auth -o jsonpath='{.data.token}' | base64 -d
printf '\n'
```

Changing an initial password Secret does not reset a password already stored in
WebUI, Langflow or MLflow's user database. Rotate through their authenticated
account/API controls. Secret env vars are read at startup: restart affected
Deployments after a key rotation. Coordinate Qdrant with WebUI, vLLM with
LiteLLM, and LiteLLM with its clients. Never casually rotate LiteLLM's salt,
Langflow's encryption secret, WebUI's session secret or MLflow's Flask secret.

For externally managed Secrets, create the namespace resources first and supply
the same key names, then apply `kubectl apply -k bootstrap`. The MLflow config
must contain `[mlflow]`, `database_uri = sqlite:////mlflow/auth.db`,
`default_permission = NO_PERMISSIONS`, an explicit administrator username/password
and `authorization_function = mlflow.server.auth:authenticate_request_basic_auth`.

### Scoped client keys

Sign into `https://llm.internal/ui` and create virtual keys limited to
`local-chat` and/or `local-embeddings`. Assign budgets and request/token limits
appropriate to the client. Do not distribute the master key or the WebUI backend
credentials to notebook/workflow authors.

To give WebUI its own restricted key, create a Secret `webui-litellm` in
`ai-system` with key `api-key`, then change `OPENAI_API_KEY`'s Secret reference in
`apps/open-webui/resources.yaml`. Commit/push and verify chat before retiring
the old access path. The LiteLLM master key remains available only to its admin
service. Revoking a virtual key is independent of all other clients.

## First acceptance

```bash
bash scripts/status.sh
kubectl -n ai-system logs job/ollama-model-pull-v1
kubectl -n ai-system exec deployment/ollama -- ollama list
kubectl -n ai-system get cluster litellm-db
kubectl -n ai-system get httproutes open-webui litellm -o yaml
```

Confirm all core Flux children are Ready, the model Job completed, Deployments
are available, PVCs bound, CNPG healthy, and route parent conditions include
`Accepted=True` and `ResolvedRefs=True` at the current generation. Optional
suspended children are expected. If the namespace/route is correct but traffic
is dropped, inspect Cilium policy verdicts: Gateway-to-backend traffic uses the
reserved ingress identity.

With the base CA installed on the client, sign into the chat UI and check:

1. Stream a response using `local-chat` and confirm the stream completes.
2. Upload a small text/PDF document, ask a question whose answer is inside it,
   and check that retrieval cites the uploaded source. Test OCR separately with
   the document languages you need; Tika's installed OCR languages may be limited.
3. Enable the chat's web-search option and verify search results/citations.
4. Restart WebUI and confirm accounts, chat history and uploaded data persist.
5. Confirm anonymous WebUI use and account creation are blocked, and LiteLLM's
   `/v1/models` refuses requests without a valid key. Test a scoped virtual key.

Use [examples/clients.py](../examples/clients.py) from a workstation after setting
`OPENAI_BASE_URL=https://llm.internal/v1` and a scoped `OPENAI_API_KEY`. Python's
HTTPS verification must trust the cluster CA; set `SSL_CERT_FILE` if required.
Do not disable TLS verification as a substitute for distributing the CA.

From a disposable pod in an unrelated namespace, connection attempts to Ollama,
Qdrant, Tika, SearXNG, vLLM and the databases should fail. From WebUI, its required
backends should work. Test these boundaries after changing network policies.

Optional acceptance: create/save/reopen a Langflow flow, persist a notebook under
`work/`, create an MLflow experiment and retrieve an artifact, and exercise
`local-vllm` while observing GPU use. No live cluster tests were run when this
repository was authored.

## Common failures

| Symptom | Check |
| --- | --- |
| Dependency not ready | Exact Flux names in both base repositories; controller Events |
| `CreateContainerConfigError` | Missing Secret or CNPG still initializing; rerun bootstrap only for missing app credentials |
| Pending PVC | Longhorn health, schedulable disks, node capacity and StorageClass |
| Ollama request OOM/slow | Smaller model/context, more RAM, or GPU profile; requests are not peak memory |
| Model Job failed | Registry egress, free model PVC space, model tag and Job logs |
| GPU pod Pending | RuntimeClass, node label, plugin readiness, allocatable GPUs and GPU already reserved |
| Route not accepted | Namespace route-scope label and Gateway `apps-https` listener |
| HTTPS failure | Internal DNS, Gateway health and trusted internal CA |
| WebUI config ignored | This repo sets `ENABLE_PERSISTENT_CONFIG=false`; edit Git, not only the admin UI |
| Search errors | Upstream search engine restrictions/rate limits and SearXNG logs |
| MLflow 401/403 | Credentials and experiment permissions; new users have none |
| MLflow S3 error | Bucket/key grants, Garage endpoint, region and capacity |

The core dependency graph deliberately withholds the UI until model downloads
finish. Inspect `ai-models` first when the first rollout appears stuck.

To retry a failed model pull after repairing the cause:

```bash
kubectl -n ai-system delete job ollama-model-pull-v1
flux reconcile kustomization ai-models --with-source
```

Flux recreates the Job. Completed model downloads remain on the Ollama PVC.
Changing the embedding model changes vector dimensions/meaning: export or back
up the vector data, select the new model and reindex the WebUI knowledge bases.
Simply changing the model name is not a vector migration.

## Backups and recovery

The storage operators being installed does not mean backups exist. Configure
and test an independent backup target before keeping important work here.

| Data | Recovery unit |
| --- | --- |
| WebUI | Consistent SQLite/upload PVC copy, webui-auth, associated Qdrant snapshot and model configuration |
| Qdrant | Native collection snapshots + API key; take copies outside its PVC |
| LiteLLM | CNPG physical/logical backup + litellm-auth, especially the salt key |
| Langflow | CNPG backup + PVC + langflow-auth encryption key |
| Jupyter | Notebook PVC + authentication configuration |
| MLflow | CNPG backup + auth SQLite PVC + artifacts (PVC or Garage bucket) + auth Secret |
| Ollama/vLLM | Weight cache, or an exact model inventory sufficient to re-download |

Use the installed Barman plugin with an explicitly configured ObjectStore,
retention and ScheduledBackup for CNPG. Use application-consistent snapshots or
quiesce SQLite-based services before filesystem backup. Velero, Longhorn backup
targets and Garage bucket replication all require configuration; none is silently
enabled by this add-on. A crash-consistent volume snapshot alone is not proof of
application recoverability.

Restore into an isolated namespace/cluster first. Restore Secrets before starting
applications; restore their data before allowing incoming traffic. Verify logins,
RAG retrieval, virtual keys, notebooks and artifact downloads, not just pod
readiness. Keep the internal CA and a copy of the Git revision in the recovery
plan. One replica of either Longhorn or PostgreSQL is not high availability.

## Upgrades

Read release notes, update the image tag **and digest**, and update
`config/images.lock.json`. Validate and test against a restored dataset before
rolling out database/schema-changing upgrades. Check Open WebUI/Qdrant vector
compatibility and MLflow auth changes in particular. A Git revert does not undo
a database migration; recovery may require restoring a backup with the old image.

Model updates should be deliberate and recorded with the resolved weight digest
from `ollama list` or the Hugging Face revision. Mutable upstream model names are
useful defaults, not sufficient for reproducible evaluations.
