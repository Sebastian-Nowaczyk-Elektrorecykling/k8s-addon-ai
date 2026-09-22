#!/usr/bin/env bash
set -euo pipefail
kubectl -n flux-system get gitrepository ai-addons
kubectl -n flux-system get kustomizations -l app.kubernetes.io/part-of=ai-addons
for ns in ai-system ai-workflows ai-notebooks ai-tracking; do
  kubectl -n "$ns" get deployments,pods,pvc,httproutes
done
kubectl get clusters.postgresql.cnpg.io -A
