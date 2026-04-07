# Repository Authentication Strategy

How `code-autonomy` authenticates to GitHub, Bitbucket Cloud, and Bitbucket
Server / Data Center for cloning, pushing, and creating pull requests.

This document covers:

1. The authentication models supported per provider
2. The internal `TokenProvider` abstraction
3. How to enable each mode (config + secrets)
4. AWS deployment notes (Secrets Manager, ECS task wiring)
5. Commit attribution (real user vs. bot)
6. Decision matrix and recommended setup

---

## 1. Why this exists

The agent runs as a long-lived service inside an AWS Fargate container. It
clones repos, makes commits, pushes branches, and creates PRs — often on
behalf of many different users, sometimes triggered by background jobs (Jira
batch runs, scheduled migrations) when no human is online.

A naive approach — store one Personal Access Token (PAT) per user, use it for
everything — has several operational problems:

- **PATs expire**, and rotation is manual; jobs silently break
- **PATs are user-scoped**, so background work has no clear identity
- **Per-user storage** multiplies secret management burden
- **Rate limits are per-token**, so heavy users hit GitHub's 5,000 req/hr cap
- **Offboarding** leaves dangling credentials

The right answer differs per provider, because each VCS exposes a different
"app-style" auth model. This codebase abstracts those differences behind a
single `TokenProvider` interface so service code never needs provider-specific
auth branches.

---

## 2. Auth models per provider

| Provider                          | App-style auth                                                | Static fallback                                  | Token TTL  |
| --------------------------------- | ------------------------------------------------------------- | ------------------------------------------------ | ---------- |
| **GitHub.com**                    | GitHub App (JWT → installation token)                         | Fine-grained PAT                                 | 1 hour     |
| **GitHub Enterprise Server**      | Same GitHub App model (override `api_base_url`)               | PAT                                              | 1 hour     |
| **Bitbucket Cloud**               | OAuth 2.0 Consumer (client-credentials grant, workspace-installed) | HTTP access token (Bearer) or app password (Basic) | 2 hours    |
| **Bitbucket Server / Data Center**| **None** — no App concept exists                              | Project-scoped HTTP access token                 | Long-lived |

### Key asymmetries

- **Bitbucket Server has no App equivalent.** You're stuck with long-lived
  tokens. Mitigate by using a *project-scoped* HTTP access token (created by
  an admin), storing it in AWS Secrets Manager, and rotating it on a 90-day
  cycle (manually or via a rotation Lambda).
- **Bitbucket Cloud OAuth Consumers** authenticate as the *consumer*, not as
  a user. Per-installation isolation is workspace-level only. Per-repo
  scoping requires repository access tokens, which are also static.
- **Bitbucket Cloud OAuth has tighter rate limits** than GitHub (1,000 req/hr
  per IP vs. 5,000+ per installation). Aggressive caching may be needed for
  high-volume workflows.

---

## 3. The `TokenProvider` abstraction

All credential acquisition flows through `src/platform/token_provider.py`:

```python
class TokenProvider(ABC):
    @abstractmethod
    def get_token(self) -> str: ...

    def get_auth_header(self) -> str:
        return f"Bearer {self.get_token()}"  # Override for Basic auth
```

Three concrete implementations live in `src/platform/`:

| Class                              | File                                                | Purpose                               |
| ---------------------------------- | --------------------------------------------------- | ------------------------------------- |
| `StaticTokenProvider`              | `token_provider.py`                                 | Wraps a static PAT / HTTP access token |
| `BasicAuthTokenProvider`           | `token_provider.py`                                 | Username + password (BB Cloud app pwd) |
| `GitHubAppTokenProvider`           | `providers/github_app.py`                           | JWT → installation token, 55-min cache |
| `BitbucketCloudOAuthProvider`      | `providers/bitbucket_cloud_oauth.py`                | Client-credentials grant, 2h cache    |

The refreshing providers (`GitHubAppTokenProvider`, `BitbucketCloudOAuthProvider`)
cache their tokens internally and refresh ~5 minutes before expiry. They are
thread-safe.

### Resolution: `auth_resolver.get_token_provider()`

Service code never instantiates providers directly. Instead:

```python
from src.platform.auth_resolver import get_token_provider

provider = get_token_provider("github", config)
clone_repo(repo_url, target_dir, branch, auth_token=provider)
pr = GitHubPR(provider).create_pull_request(...)
```

`get_token_provider()` inspects the config dict and:

- Returns a `GitHubAppTokenProvider` if `[github_app].enabled = true`
- Returns a `BitbucketCloudOAuthProvider` if `[bitbucket_oauth].enabled = true`
- Otherwise returns a `StaticTokenProvider` wrapping the configured PAT /
  HTTP access token (existing behavior)

This means **enabling App auth is a config-only change** — no service code
needs to know which mode is active.

### Backwards compatibility

`git_ops.py`, `pr_platform.py`, and `bitbucket_server.py` all accept a
`TokenSource`, which is a `Union[TokenProvider, str, Callable[[], str], None]`.
Existing callers that pass plain strings continue to work unchanged — the
string is wrapped in a `StaticTokenProvider` via `coerce_provider()`.

---

## 4. Configuration

### GitHub App

```ini
[github_app]
enabled = true
app_id = 123456
installation_id = 78901234
# Provide the PEM private key via ONE of:
private_key_env = GITHUB_APP_PRIVATE_KEY        # recommended for AWS
# private_key_path = /run/secrets/github-app-key.pem
# private_key       = -----BEGIN RSA PRIVATE KEY-----...   # inline (avoid)

# For GitHub Enterprise Server only:
# api_base_url = https://ghe.example.com/api/v3
```

**Setup:**

1. Register a GitHub App at <https://github.com/settings/apps/new>
   (or your org's developer settings).
2. Required permissions:
   - Contents: **Read & write**
   - Pull requests: **Read & write**
   - Metadata: **Read**
3. Generate a private key (`.pem`). Store the contents in AWS Secrets Manager.
4. Install the App on the org / repos that the agent should access.
5. Note the numeric **App ID** (App settings page) and **Installation ID**
   (URL of the installation page, or `GET /app/installations`).

### Bitbucket Cloud OAuth

```ini
[bitbucket_oauth]
enabled = true
client_key = abc123def456
client_secret_env = BITBUCKET_OAUTH_CLIENT_SECRET
```

**Setup:**

1. Workspace settings → **OAuth consumers** → Add consumer.
2. Required scopes:
   - Repositories: **Read**, **Write**
   - Pull requests: **Read**, **Write**
3. **Important:** check "This is a private consumer" — required for the
   client-credentials grant.
4. Copy the Key and Secret. Store the secret in AWS Secrets Manager.

### Bitbucket Server / Data Center

No `[bitbucket_server_auth]` section exists because there is nothing to
configure beyond the static token. Use:

```bash
export BITBUCKET_HTTP_ACCESS_TOKEN=<project-scoped HTTP access token>
```

Or, in `[bitbucket]`:

```ini
[bitbucket]
enabled = true
base_url = https://bitbucket.example.com
user_token = <token>          # or leave empty and use the env var above
```

**Best practices for the static token:**

- Create it as a **project-scoped** HTTP access token, not a personal one
- Grant only `REPO_WRITE` and `PROJECT_READ`
- Rotate every 90 days; track rotation in your secrets management system
- Store in AWS Secrets Manager with an automatic rotation Lambda if possible

---

## 5. AWS deployment

### Secrets Manager layout

| Secret name                                  | Contents                              | Used by                               |
| -------------------------------------------- | ------------------------------------- | ------------------------------------- |
| `code-autonomy/github-app-key`               | PEM private key (text)                | `GitHubAppTokenProvider`              |
| `code-autonomy/bitbucket-oauth-secret`       | OAuth Consumer secret                 | `BitbucketCloudOAuthProvider`         |
| `code-autonomy/bitbucket-server-token`       | HTTP access token                     | `StaticTokenProvider` (BB Server)     |
| `code-autonomy/github-pat` *(legacy)*        | Personal access token (fallback)      | `StaticTokenProvider` (GitHub)        |

### ECS task definition wiring

In `deploy/ecs-task-definition.json`, add to the container's `secrets` array:

```json
{
  "name": "GITHUB_APP_PRIVATE_KEY",
  "valueFrom": "arn:aws:secretsmanager:us-east-1:ACCOUNT:secret:code-autonomy/github-app-key"
},
{
  "name": "BITBUCKET_OAUTH_CLIENT_SECRET",
  "valueFrom": "arn:aws:secretsmanager:us-east-1:ACCOUNT:secret:code-autonomy/bitbucket-oauth-secret"
},
{
  "name": "BITBUCKET_HTTP_ACCESS_TOKEN",
  "valueFrom": "arn:aws:secretsmanager:us-east-1:ACCOUNT:secret:code-autonomy/bitbucket-server-token"
}
```

And to `environment` (non-secret values):

```json
{ "name": "GITHUB_APP_ID", "value": "123456" },
{ "name": "GITHUB_APP_INSTALLATION_ID", "value": "78901234" }
```

The execution role needs `secretsmanager:GetSecretValue` on each of those
ARNs (least-privilege — do **not** use `*`).

### Token refresh in long-running tasks

The refreshing providers handle expiry transparently — every call to
`provider.get_token()` returns either a cached or freshly-fetched token. No
background thread is needed. The only cost is the per-refresh API call (one
extra HTTPS request per ~55 minutes for GitHub App, per ~115 minutes for
Bitbucket Cloud OAuth).

---

## 6. Commit attribution

When the agent uses an App / OAuth Consumer for transport, every action
appears under that bot identity in the audit log. To preserve human
attribution in `git log`, override the commit author per session:

```python
stage_and_commit(
    repo_dir,
    message=commit_message,
    author_name=session.user.display_name,
    author_email=session.user.email,
)
```

GitHub will then show: *"jane committed, code-autonomy[bot] pushed"*. The PR
itself is opened by the bot — mention the requesting user in the PR body for
clarity.

If your compliance regime requires **GPG-signed commits as the real user**,
you cannot use App tokens for the push — you must use the user's own OAuth
token or PAT. In practice, very few enterprise setups require this.

---

## 7. Decision matrix

| Need                                         | Recommended approach                                                |
| -------------------------------------------- | ------------------------------------------------------------------- |
| Production multi-user GitHub deployment      | **GitHub App** (`[github_app].enabled = true`)                      |
| Production multi-user Bitbucket Cloud        | **OAuth Consumer** (`[bitbucket_oauth].enabled = true`)             |
| Bitbucket Server / Data Center (any scale)   | **Project-scoped HTTP access token** + 90-day rotation              |
| Background / scheduled jobs                  | App / OAuth Consumer (no human user available)                      |
| Single-developer dev / POC                   | Static PAT (existing behavior, no config changes needed)            |
| Strict per-user commit attribution           | App / OAuth + commit author override (`git config user.email`)      |
| Compliance with GPG-signed user commits      | User's own PAT or OAuth (cannot use App tokens for transport)       |

---

## 8. File map

| File                                                          | Role                                                          |
| ------------------------------------------------------------- | ------------------------------------------------------------- |
| `src/platform/token_provider.py`                              | `TokenProvider` ABC, `StaticTokenProvider`, `BasicAuthTokenProvider`, `coerce_provider()` |
| `src/platform/providers/github_app.py`                        | `GitHubAppTokenProvider` (JWT → installation token)           |
| `src/platform/providers/bitbucket_cloud_oauth.py`             | `BitbucketCloudOAuthProvider` (client-credentials grant)      |
| `src/platform/auth_resolver.py`                               | `get_token_provider(platform, config)` factory                |
| `src/platform/git_ops.py`                                     | `clone_repo`, `push_branch`, `list_remote_branches` accept `TokenSource` |
| `src/platform/pr_platform.py`                                 | `GitHubPR`, `BitbucketPR` accept `TokenSource`                |
| `src/platform/bitbucket_server.py`                            | `BitbucketServerClient`, `BitbucketServerPR` accept `TokenSource` |
| `src/config_loader.py`                                        | Parses `[github_app]` and `[bitbucket_oauth]` sections        |
| `config.example.ini`                                          | Documented examples for both new sections                     |

---

## 9. Operational notes

- **Rate limits:** GitHub App tokens give 5,000–15,000 requests/hour per
  installation. Bitbucket Cloud OAuth is 1,000/hour per IP — much tighter.
  Plan caching accordingly.
- **Token refresh failures:** If GitHub or Bitbucket returns a non-2xx during
  token exchange, the provider raises `RuntimeError`. Wrap callers in retry
  logic if needed (the existing circuit breaker in `src/llm_client.py`
  patterns can be reused).
- **Clock skew:** `GitHubAppTokenProvider` back-dates JWT `iat` by 60 seconds
  to tolerate clock drift. Container clocks should still sync via NTP.
- **PEM key format:** GitHub Apps generate PKCS#1 RSA keys. PyJWT with the
  `[crypto]` extra handles them natively. Don't convert to PKCS#8 unless
  required by your secret store.
- **Required dependency:** `pyjwt[crypto]>=2.8.0` must be in
  `requirements.txt` for GitHub App auth to work. Add it before enabling
  `[github_app]`.

---

## 10. Migration checklist

To adopt App-based auth on an existing deployment:

- [ ] Add `pyjwt[crypto]>=2.8.0` to `requirements.txt`
- [ ] Register a GitHub App / Bitbucket OAuth Consumer
- [ ] Store the private key / client secret in AWS Secrets Manager
- [ ] Update `deploy/ecs-task-definition.json` with new secret references
- [ ] Set `[github_app].enabled = true` (or `[bitbucket_oauth].enabled = true`)
      in `config.ini`
- [ ] Verify the new auth path locally with a test repo
- [ ] Roll out to one ECS task first; check CloudWatch logs for the
      "Refreshing GitHub App installation token" message
- [ ] Update commit attribution code to pass per-session user identity
- [ ] Decommission the old PAT after a grace period
