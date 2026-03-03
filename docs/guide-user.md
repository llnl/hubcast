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
- `draft_sync`: if enabled, Hubcast will sync draft PRs/MRs. default: True
- `draft_sync_msg`: if enabled and `draft_sync=False`, Hubcast will post a message to the source repo explaining why the change was not synced. default: True

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

If you expect contributions from users who aren't maintainers or who don't have accounts on the destination forge, Hubcast enables you to approve their requests via a bot-like interface.

### Hubcast bot
Depending on the setup of your Hubcast installation, you can request assistance from the bot by tagging an account (e.g., `@lc-hubcast help`) or the default `/hubcast help` in a PR/MR comment.

The bot can perform the following actions:
- Approve requests by non-maintainers: this will sync the PR/MR to the destination forge with the identity of the approver.
- Retry the GitLab CI pipeline

#### Approval
To securely sync commits from external collaborators, approvals require links to a commit hash. You can comment your approval on a PR review:

![A GitHub pull request review; the user has written a comment `@lc-hubcast approve` to sync the user's contributions.](/docs/img/approve-comment.png)
