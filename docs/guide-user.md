# User Guide

This guide covers usage of Hubcast to sync repository state between Git forges.

## Initialization

If you've set up a local instance of Hubcast or using it for the first time, we recommend setting up a test repository. To create a test repo on GitHub, click [here](https://github.com/new?name=hubcast-test). Next initialize a local repo on your computer.

```sh
mkdir hubcast-test && cd hubcast-test
git init .
```

If you haven't already, create a repository on the destination forge (like GitLab.com). 

For Hubcast to function properly, the state of both source and destination repos need to be identical before any syncing can occur.

## Configuration

Behavior specific to each repository can be configured via the `hubcast.yml` file.

The following options are available:

- `owner`: the organization or user that owns the repo on the destination forge
- `name`: the name of the destination repository
- `sync_drafts`: if enabled, Hubcast will sync draft PRs/MRs. default: True
- `sync_drafts_msg`: if enabled and `draft_sync=False`, Hubcast will post a message to the source repo explaining why the change was not synced. default: True

For example, if you'd like to sync your repo to `https://gitlab.com/example/hubcast-test`, `owner` would be `example` and `name` would be `hubcast-test`.

To proceed with the default settings for your repo, copy the following contents into `.github/hubcast.yml`:

```yaml
Repo:
  owner: example
  name: hubcast-test
```

Note: Hubcast will search for these settings in the HEAD of the source repository's default branch.

If you'd like to test the CI job status syncing, add a job in `.gitlab-ci.yml`.

```yaml
build-job:
  stage: build
  script:
    - echo "Hello, $GITLAB_USER_LOGIN!"
```

To ensure the source and destination repos have the same state, commit the changes and push to the two remotes:

```sh
git add . && git commit -m "init"
git remote add gh git@github.com:example/hubcast-test.git
git remote add gl git@gitlab.com:example/hubcast-test.git
git push gh main && git push gl main
```

## Installation

Now that the source and destination repos are properly configured, we can install Hubcast into the source repository.

### GitHub as a source forge
The administrator of your Hubcast instance created a [GitHub App](https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app). 
Inquire with them about the availability of the app and whether it belongs to an organization or user account. 
See the [admin guide](/docs/guide-admin.md#github-as-a-source-forge) for more details.

The app can be installed by a maintainer of the source repository.

## Usage
With Hubcast configured and installed, we can start using it to sync repository state and receive CI job status on the source repository.

Any changes to PRs/MRs and branches will be automatically synced by Hubcast if they are initiated by an authorized user.

To be an authorized user, they must be in the Hubcast instance account map AND have write permissions to the destination repository.

For example, if you want to sync a branch from GitHub → GitLab.com, your GitLab account must be registered in the mapping and be a member of the repository.

> [!NOTE]
> Hubcast requires users to be assigned to the GitLab **developer** role to automatically sync commits to the destination forge.
> If any unallowed action is performed, Hubcast will post a failed status check notifying users about unsuccessful syncs.
> Review the [GitLab user roles](https://docs.gitlab.com/user/permissions) documentation for details on the permissions needed to perform repository actions.

### Webhook Setup

After installing Hubcast on your repository, the first push to the default branch will trigger webhook setup on the destination repository. This webhook allows CI status to be reported back to the source forge.

**Important:** Webhook creation requires the GitLab **maintainer** role. If the first push to the default branch is performed by a user with only the developer role:
- Branch sync will succeed
- Webhook will not be created
- CI status will not be reported back

To resolve this, have a user with the maintainer role push to the default branch; an empty commit is sufficient.

If you expect contributions from users who aren't members of the destination repository or don't have accounts on the destination forge, Hubcast enables you to approve their requests via a bot-like interface.

### Hubcast bot
Depending on the setup of your Hubcast installation, you can request assistance from the bot by tagging an account (e.g., `@lc-hubcast help`) or the default `/hubcast help` in a PR/MR comment.

> [!TIP]
> Check with your Hubcast administrator to confirm the correct bot prefix for your instance.

The bot supports the following commands:
- `@{bot} help` - Display available commands and usage information
- `@{bot} approve` - Sync this pull request to the destination forge and trigger a new pipeline (requires maintainer permissions)
- `@{bot} run pipeline` - Request a new run of the GitLab CI pipeline
- `@{bot} restart failed jobs` - Restart any failed jobs in the latest CI pipeline

Replace `@{bot}` with your instance's bot user (e.g., `@lc-hubcast`) or use `/hubcast` if no bot user is configured.

#### Approval
To securely sync commits from external collaborators, approvals require links to a commit hash. You can comment your approval on a PR review:

![A GitHub pull request review; the user has written a comment `@lc-hubcast approve` to sync the user's contributions.](/docs/img/approve-comment.png)
