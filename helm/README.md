# Hubcast Helm Chart

Helm chart for deploying Hubcast, a GitHub to GitLab mirroring application, to Kubernetes or OpenShift.

## Prerequisites

- [ ] Kubernetes 1.19+ or OpenShift 4.x cluster
- [ ] Helm 3.0+ installed
- [ ] `kubectl` or `oc` CLI configured
- [ ] GitHub App with webhook and private key
- [ ] GitLab repository with webhook and access token
- [ ] Container access to `ghcr.io/llnl/hubcast`

## Quick Start (5 minutes)

### 1. Prepare Configuration

Create a values file with your application settings (no secrets):

```yaml
# my-values.yaml
hubcast:
  accountMapType: "file"

  github:
    appId: "123456"
    botUser: "/hubcast"

  gitlab:
    url: "https://gitlab.com"
    tokenType: "impersonation"
    callbackUrl: "https://hubcast.example.com/v1/events/dest/gitlab"

  accountMap:
    users:
      github_user1: gitlab_user1
      github_user2: gitlab_user2
```

### 2. Create Secrets

**IMPORTANT:** Never commit secrets to git or include them in values.yaml files. Use external secret management instead.

Create a Kubernetes secret with the required credentials using files (to avoid exposing secrets in bash history):

```bash
# Create secret from files containing your credentials
# Each file should contain only the secret value (no quotes or extra whitespace)
kubectl create secret generic hubcast-secrets \
  --from-file=HC_GH_WEBHOOK_SECRET=github-webhook-secret.txt \
  --from-file=HC_GH_PRIVATE_KEY=github-app.pem \
  --from-file=HC_GL_WEBHOOK_SECRET=gitlab-webhook-secret.txt \
  --from-file=HC_GL_TOKEN=gitlab-token.txt

# Remember to securely delete the temporary files after creating the secret
```

> [!WARNING]
> **Avoid trailing newlines in secret files!** Secret files should contain only the secret value without trailing newlines, which can cause authentication failures. Remove them with:
> ```bash
> echo -n "$(cat github-webhook-secret.txt)" > github-webhook-secret.txt
> ```

> [!NOTE]
> Secret keys must use `HC_` prefixes to match environment variable names since the chart uses `envFrom`.

### 3. Install

**Kubernetes:**
```bash
helm install hubcast . \
  -f my-values.yaml \
  --set existingSecret=hubcast-secrets
```

**OpenShift:**
```bash
# With file-based account mapping
helm install hubcast . \
  -f values-openshift.yaml \
  -f my-values.yaml \
  --set existingSecret=hubcast-secrets

# With LDAP account mapping
helm install hubcast . \
  -f values-openshift-ldap.yaml \
  -f my-values.yaml \
  --set existingSecret=hubcast-secrets
```

### 3. Verify

```bash
# Check pod status
kubectl get pods -l app.kubernetes.io/name=hubcast

# View logs
kubectl logs -l app.kubernetes.io/name=hubcast --tail=50

# Test locally
kubectl port-forward service/hubcast 8080:80
curl http://localhost:8080/health
```

## Secret Management

### Option 1: External Secrets with kubectl (Recommended)

Create secrets externally using `kubectl` from files (avoids bash history exposure):

```bash
# Create secret from files containing your credentials
kubectl create secret generic hubcast-secrets \
  --from-file=HC_GH_WEBHOOK_SECRET=github-webhook-secret.txt \
  --from-file=HC_GH_PRIVATE_KEY=github-app.pem \
  --from-file=HC_GL_WEBHOOK_SECRET=gitlab-webhook-secret.txt \
  --from-file=HC_GL_TOKEN=gitlab-token.txt

# Install referencing the external secret
helm install hubcast . \
  -f my-values.yaml \
  --set existingSecret=hubcast-secrets
```

**Note:** Secret keys must use `HC_` prefixes to match environment variable names since the chart uses `envFrom`.

### Option 2: Values File (Not Recommended)

**WARNING:** Only use this for local testing. Never commit secrets to version control.

Create `my-values.yaml` with configuration and secrets:

```yaml
# my-values.yaml
hubcast:
  github:
    appId: "123456"
  gitlab:
    url: "https://gitlab.com"
    callbackUrl: "https://hubcast.example.com/v1/events/dest/gitlab"

secrets:
  githubWebhookSecret: "your-secret"
  githubPrivateKey: |
    -----BEGIN RSA PRIVATE KEY-----
    your-private-key-here
    -----END RSA PRIVATE KEY-----
  gitlabWebhookSecret: "your-secret"
  gitlabToken: "your-token"
```

Then install:

```bash
helm install hubcast . -f my-values.yaml
```

## Configuration

### Required Values

| Parameter | Description | Example |
|-----------|-------------|---------|
| `hubcast.github.appId` | GitHub App ID | `"123456"` |
| `hubcast.gitlab.url` | GitLab instance URL | `"https://gitlab.com"` |
| `hubcast.gitlab.callbackUrl` | GitLab event callback URL | `"https://hubcast.example.com/v1/events/dest/gitlab"` |
| `hubcast.accountMap.users` | User mappings, required when `hubcast.accountMapType` is `"file"` | `{github_user: gitlab_user}` |
| `hubcast.ldap.*` | LDAP settings, required when `hubcast.accountMapType` is `"ldap"` | See LDAP example below |
| `secrets.githubWebhookSecret` | GitHub webhook secret | `""` |
| `secrets.githubPrivateKey` | GitHub App private key | `""` |
| `secrets.gitlabWebhookSecret` | GitLab webhook secret | `""` |
| `secrets.gitlabToken` | GitLab access token | `""` |

### Key Configuration Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.repository` | Container image | `ghcr.io/llnl/hubcast` |
| `image.tag` | Image tag | `""` (uses appVersion) |
| `image.digest` | Image digest (overrides tag) | `""` |
| `replicaCount` | Number of replicas | `1` |
| `hubcast.port` | Application port | `8080` |
| `hubcast.accountMapType` | `"file"` or `"ldap"` | `"file"` |
| `service.type` | Service type | `ClusterIP` |
| `service.targetPort` | Service target port name or number | `http` |
| `ingress.enabled` | Enable Kubernetes Ingress | `false` |
| `route.enabled` | Enable OpenShift Route | `false` |
| `resources.limits.cpu` | CPU limit | `500m` |
| `resources.limits.memory` | Memory limit | `512Mi` |
| `existingSecret` | Use existing secret | `""` |

See `values.yaml` for all available options.

### Environment-Specific Configuration

Use overlay files for different environments:

```bash
# Development
helm install hubcast . -f my-dev-values.yaml

# Production with digest pinning
helm install hubcast . \
  -f my-prod-values.yaml \
  --set image.digest="sha256:abc123..."
```

### Immutable Deployments (Production)

Use image digests instead of tags for immutable deployments:

```yaml
image:
  repository: ghcr.io/llnl/hubcast
  digest: "sha256:abcdef123456..."
  # digest takes precedence over tag
```

### LDAP Account Mapping

For large organizations, can use an LDAP AccountMap instead of a file account mapping:

```yaml
hubcast:
  accountMapType: "ldap"
  ldap:
    uri: "ldap://ldap.example.com:389"
    base: "ou=users,dc=example,dc=com"
    input: "uid"
    output: "gitlabUsername"
    scope: 2
    bindDn: "cn=hubcast,ou=services,dc=example,dc=com"

secrets:
  ldapBindPassword: "your-bind-password"
```

### External Access

**Kubernetes (Ingress):**
```yaml
ingress:
  enabled: true
  className: "nginx"
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
  hosts:
    - host: hubcast.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: hubcast-tls
      hosts:
        - hubcast.example.com
```

**OpenShift (Route):**
```yaml
route:
  enabled: true
  hosts:
    - hubcast.apps.your-cluster.com
  tls:
    enabled: true
    termination: edge
```

**Multiple Routes (e.g., for alternate hostnames):**
```yaml
route:
  enabled: true
  hosts:
    - hubcast.apps.your-cluster.com       # Primary route: "hubcast"
    - hubcast.example.com                 # Alt route: "hubcast-alt-1"
  tls:
    enabled: true
    termination: edge
```

Each host will get its own Route object pointing to the same Service. The first host creates a route named `hubcast`, and additional hosts create routes named `hubcast-alt-1`, `hubcast-alt-2`, etc.

## Operations

### Upgrading

```bash
# Upgrade to new version
helm upgrade hubcast . -f my-values.yaml

# Upgrade with new image
helm upgrade hubcast . \
  -f my-values.yaml \
  --set image.tag="1.1.0"

# View upgrade history
helm history hubcast
```

### Rollback

```bash
# Rollback to previous version
helm rollback hubcast

# Rollback to specific revision
helm rollback hubcast 2
```

### Uninstalling

```bash
helm uninstall hubcast
```

## OpenShift Deployment

OpenShift has specific requirements:

1. **Dynamic UID assignment** - Use `values-openshift.yaml` which sets `runAsUser: null`
2. **Routes instead of Ingress** - Set `route.enabled=true`
3. **Security context constraints** - Chart is compatible with `restricted` SCC

```bash
# Install on OpenShift
helm install hubcast . -f values-openshift.yaml -f my-secrets.yaml
```

## Troubleshooting

### Pod not starting

```bash
# Check events
kubectl describe pod -l app.kubernetes.io/name=hubcast

# Check logs
kubectl logs -l app.kubernetes.io/name=hubcast

# Verify secrets exist
kubectl get secret hubcast-secrets
kubectl describe secret hubcast-secrets
```

### Webhooks not working

```bash
# Check if route/ingress is accessible
curl https://hubcast.example.com/health

# Check logs for webhook errors
kubectl logs -l app.kubernetes.io/name=hubcast | grep -i webhook

# Verify webhook secrets match
kubectl get secret hubcast-secrets -o jsonpath='{.data.HC_GH_WEBHOOK_SECRET}' | base64 -d
```

### Configuration issues

```bash
# Check environment variables in pod
kubectl exec -it deployment/hubcast -- env | grep HC_

# Check mounted config
kubectl get configmap hubcast -o yaml
```

## Security Best Practices

1. **Use external secrets** - Never commit secrets to git
2. **Pin image digests** - Use immutable deployments in production
3. **Use TLS** - Always enable HTTPS for external access
4. **Limit permissions** - Use restrictive security contexts
5. **Regular updates** - Keep container images patched

## Support

- **Documentation**: https://github.com/llnl/hubcast
- **Issues**: https://github.com/llnl/hubcast/issues
- **Discussions**: https://github.com/llnl/hubcast/discussions

## License

See LICENSE file in the repository root.
