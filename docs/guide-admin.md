# Administrator Guide

This guide covers deployment and operation of a Hubcast instance.

Administrators configure Hubcast to connect Git forges, manage account mappings, and support users syncing repositories and CI results. 

Before proceeding, identify the two Git forges:
- the **source forge**, where contributors collaborate
- the **destination forge**, where CI pipelines are executed

Administrator access to the destination forge is highly recommended but not required.

Hubcast is typically deployed as a long-running service behind a reverse proxy and receives inbound webhooks from both forges.

See Hubcast's [architecture documentation](/docs/ARCHITECTURE.md) for details on the trust model and identity management.

We'll first configure the source and destination forges to emit events triggered by user actions (pushes, pull requests, comments, etc.) and allow Hubcast sufficient permission to read/write to the repositories.

---

## GitHub as a source forge

Hubcast uses the [GitHub App](https://docs.github.com/en/apps/using-github-apps/about-using-github-apps) feature to monitor repositories for changes and respond to events. To create an app, we'll need a webhook URL and webhook secret.

If you're deploying Hubcast in production, the webhook will be a link to your Hubcast instance (e.g., `https://hubcast.example.com/v1/events/src/github`).

> [!NOTE]
> If you're working in a development environment, check out our [developer documentation](docs/guide-developer.md).

Create a strong, password-like string for the webhook secret. 

You can do this quickly with OpenSSL:

```sh
openssl rand -base64 25 | tr -d "="
```

Hubcast will use this to verify webhooks came from GitHub.

With the webhook URL and secret, follow [GitHub's app registration guide](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app) with the following settings.

> [!NOTE]
> The app will require the following permissions:
> - repo contents: read
> - pull requests: read and write (to comment on PRs)
> - checks: read and write (to post CI status from the destination forge)
> - issues: read (to read PR comments)
>
> Subscribe to the `push`, `pull request`, and `issue comments` events.

The registration flow will ask [where the app can be installed](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/making-a-github-app-public-or-private). We recommend keeping the app private, as making the app publicly installable may result in external actors attempting to mirror their repositories to your configured destination forge. A private app can be configured to be owned by a GitHub organization, allowing it to be installed by any repository in that namespace.

Once your app is created, go to `Private Keys` -> `Generate a private key`, which will download a file with the `*.pem` extension. Save this file, we'll use it later when configuring the Hubcast instance.

With the GitHub App configured, all repositories that install this app will notify the Hubcast instance of any state change that requires a sync.

## GitLab as a destination forge

Hubcast supports mirroring to any GitLab instance as the destination forge. In order to perform actions such as writing to the repository, syncing CI status, and configuring webhooks, Hubcast will need access to certain permissions. Administrator access to the GitLab destination forge is required.

[Impersonation tokens](https://docs.gitlab.com/api/rest/authentication/#impersonation-tokens): GitLab supports the creation of these tokens to downscope actions to a certain user account. 

For instance, GitHub user `test123` submits a pull request to a test repository. Hubcast's account mapper resolves the user on the destination GitLab forge. Hubcast will then create an impersonation token for that user, sync the changes in the PR to the destination, and forward any CI job status back to Hubcast for processing.

Any permissions or roles held by the user on the destination will define the possible actions. For example, if the user does not have write permissions to the destination repository, Hubcast will not be able to perform a sync on behalf of that account.

To enable this functionality, an administrator on the GitLab forge creates a [personal access token](https://docs.gitlab.com/user/profile/personal_access_tokens/) with the `api` scope.

## Account maps

Hubcast comes with account mappers by default. When a user on the source forge performs an action, Hubcast will perform a lookup of the user.

If the account map returns the user's identifier on the destination forge, Hubcast will continue with the requested action.

If the user is not present in the account map, Hubcast won't perform the action. As documented in the user guide, users with sufficient permissions can act as an "approver" and ensure that Hubcast fulfills the request.

### File mapper

Create a YAML file that links the username on the source forge to the username on the destination.

Example contents:

```yaml
Users:
  source_username: destination_username
```

### LDAP mapper

If your organization hosts an LDAP server with information about user accounts, you can use attributes to manage mappings. For example, your organization may manage a GitLab instance where you want to run CI jobs. The LDAP server could store the user's account ID on the destination forge (the GitLab instance) and their username on the source forge (e.g., GitHub.com).

When an internal user submits a PR to a GitHub repo, the account map will find the corresponding account on the destination forge and process the sync.

It is up to your organization how to propagate the source forge identities; the LDAP server will need an attribute like `githubId` to perform the mapping.

## Configuration

Hubcast is configured via environment variables. The full set of current options are documented below.

### General settings

- `HC_PORT`: port for Hubcast to listen on. default: `8080`.
- `HC_LOGGING_CONFIG_PATH`: logging configuration path; the file should be in JSON and in [dictConfig](https://docs.python.org/3/library/logging.config.html#logging.config.dictConfig) format. See `/logging_config.json` for an example.

### Account map settings

For details on how to configure each option, see the [account map](#account-maps) documentation.

- `HC_ACCOUNT_MAP_TYPE`: options: `file`, `ldap`

If using the `file` map:

- `HC_ACCOUNT_MAP_PATH`: a path to the YAML file mapping usernames between source and destination forges

If using the `ldap` map:

- `HC_LDAP_MAP_URI`: the URI of the LDAP instance (e.g., ``)
- `HC_LDAP_MAP_BASE`: the base of the LDAP instance (e.g., ``)
- `HC_LDAP_MAP_INPUT`: the user's source forge user id (e.g. `githubId`)
- `HC_LDAP_MAP_OUTPUT`: the user's destination forge user id (e.g., `uid`)
- `HC_LDAP_MAP_SCOPE`: the [scope of the LDAP search](https://ldap.com/the-ldap-search-operation), specified numerically. options: base (0), one (1), and sub (2).
- `HC_LDAP_MAP_BIND_DN`: the name of the bind distinguished name (optional)
- `HC_LDAP_MAP_BIND_PASSWORD`: the bind password (optional)

If no bind credentials are specified, the mapper will attempt a SASL/GSSAPI (e.g., Kerberos) bind.

### Source forge settings

#### GitHub

- `HC_GH_APP_IDENTIFIER`: the GitHub App ID (provided after creation)
- `HC_GH_PRIVATE_KEY`: the contents of the app private key file, do not strip any newlines from this string
- `HC_GH_SECRET`: the webhook secret set during the creation of the GitHub App
- `HC_GH_BOT_USER`: users can tag an account to perform actions within the context of a pull request (e.g., `@lc-hubcast help`). if this is not specified, the prefix will default to `/hubcast`

### Destination forge settings (GitLab)

- `HC_GL_URL`: the URL of the GitLab instance (e.g., `https://gitlab.com`)
- `HC_GL_TOKEN_TYPE`: options: `impersonation` (default) or `single`. see [details](#gitlab-as-a-destination-forge) on each token type.
- `HC_GL_TOKEN`: the value of the token -- the scope will depend on the type of token created

Hubcast will create a webhook for each repository to report CI results back to the source forge.

- `HC_GL_SECRET`: choose a secure, password-like string for webhook verification
- `HC_GL_CALLBACK_URL`: the URL Hubcast will receive events from (e.g., `https://hubcast.example.com/v1/events/dest/gitlab`)

## Running

Hubcast can be run as a standalone Python application or through your favorite container engine.

Before running, ensure all required configuration variables are defined and propagated to the environment.

```bash
git clone https://github.com/llnl/hubcast.git && cd hubcast
pip install .
python -m hubcast
```

```bash
podman run ghcr.io/llnl/hubcast:latest
```

## Testing with a repository

Now that Hubcast is configured for use, follow the [user guide](/docs/guide-user.md) to set up a repository to test the Hubcast instance.
