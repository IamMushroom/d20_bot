# d20-bot Helm chart

Chart deploys the Telegram bot and, by default, Core with a persistent SQLite volume and
the master web panel.

## Install

For experiments, secrets can be passed directly:

```shell
helm upgrade --install d20 ./charts/d20-bot \
  --set-string secrets.telegramToken='<telegram-token>' \
  --set-string secrets.coreToken='<long-random-secret>'
```

For a real installation, create the Secret separately:

```shell
kubectl create secret generic d20-secrets \
  --from-literal=D20_BOT_TG_TOKEN='<telegram-token>' \
  --from-literal=D20_BOT_CORE_TOKEN='<long-random-secret>'

helm upgrade --install d20 ./charts/d20-bot \
  --set existingSecret=d20-secrets
```

To expose the panel, configure `core.webBaseUrl` and Ingress together:

```yaml
core:
  webBaseUrl: https://d20.example

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: d20.example
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: d20-tls
      hosts:
        - d20.example
```

Standalone dice bot without Core or a PVC:

```shell
helm upgrade --install d20 ./charts/d20-bot \
  --set core.enabled=false \
  --set-string secrets.telegramToken='<telegram-token>'
```

SQLite requires a single Core writer. Keep `core.replicaCount: 1` when persistence is enabled.
The bot also defaults to one replica because Telegram long polling must not run concurrently
with the same token.
