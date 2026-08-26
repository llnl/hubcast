# User Guide

This guide covers usage of Hubcast to sync repository state between Git forges.

First, identify the source and destination repositories Hubcast will be syncing.

## Configuration

Hubcast settings for each repository are defined in the `hubcast.yml` file. Create this file at `.github/hubcast.yml` in your GitHub repository:

```yaml
Repo:
  # Required: organization or user that owns the repo on the destination forge
  dest_org: example

  # Required: name of the destination repository
  dest_name: hubcast-test

  # Optional: name of the CI check as reported back to GitHub (default: gitlab-ci)
  check_name: gitlab-ci

  # Optional: granularity of CI statuses reported to GitHub (default: [pipeline])
  # The overall pipeline status is always reported, in addition to any other types listed here.
  # Available types: pipeline, child-pipelines, jobs
  # You can mix and match any combination of these types
  # Examples:
  #   [pipeline] - overall pipeline status only (default behavior)
  #   [child-pipelines] - child pipeline statuses, plus overall pipeline status
  #   [jobs] - individual job statuses, plus overall pipeline status
  #   [child-pipelines, jobs] - child pipeline and job statuses, plus overall pipeline status
  check_types: [pipeline]

  # Optional: delete branches from destination when source PR is closed (default: true)
  delete_closed: true

  # Optional: sync draft PRs/MRs (default: true)
  # regardless of this setting, a draft PR can still be synced manually with `approve`
  sync_drafts: true

  # Optional: post message when draft sync is disabled (default: true)
  sync_drafts_msg: true

  # Optional: create GitLab MRs from GitHub PRs
  # allows developers to create synthetic merge commits using GitLab's merged results pipelines feature
  create_mr: false
```

A minimal configuration requires only `dest_org` and `dest_name`:

```yaml
Repo:
  dest_org: example
  dest_name: hubcast-test
```

> [!TIP]
> Hubcast will always search for its settings in the HEAD of the source repository's default branch.
> 
> This means that Hubcast won't perform syncing on the initial PR used to add the configuration file. 
> 
> Also, if you open a PR to edit the Hubcast configuration file, you will not be able to preview the settings change in the PR web view.
> 
> This restriction is in place for security purposes.

## Installation

Now that the source and destination repos are properly configured, we can install Hubcast into the source repository.

### GitHub as a source forge
The administrator of your Hubcast instance created a [GitHub App](https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app).
Inquire with them about the availability of the app and whether it belongs to an organization or user account.
See the [admin guide](/docs/guide-admin.md#github-as-a-source-forge) for more details.

The app can be installed by a maintainer of the source repository.

## Preparing the destination repository

Hubcast requires your destination repository to be configured with certain settings in order to facilitate secure mirroring and to help you avoid permissions issues.

### User roles

Because Hubcast links identities between the source and destination forges, both accounts must have similar permissions on each repository.

Members of your development team should be assigned to at least the GitLab **developer** role for Hubcast to automatically mirror contributions to the destination repository.

If you do not want to add users to your destination repository or the user does not have an account, you can mirror commits [on their behalf](/docs/guide-user.md#approval).

If an unallowed action is performed, Hubcast will post a failed status check notifying users about unsuccessful actions.

### Changes to Hubcast configuration

Hubcast propagates changes from the `hubcast.yml` file to a webhook on the destination repository. This webhook allows CI status to be reported back to the source forge.

Webhook creation requires the GitLab **maintainer** role. In other words, all changes to the `hubcast.yml` file must be merged/pushed by a user with the maintainer role on the destination repository.

If changes to Hubcast's configuration are pushed by a user without the maintainer role, Hubcast will continue to mirror commits between the source and destination repository, but any CI status may not be reported back to the source repo.

To resolve this without making changes to the configuration, a user with the maintainer role can push to the default branch with `[hubcast config]` in the commit message; an empty commit is sufficient.

### Branch protection rules

Hubcast may mirror changes via a force push, depending on the state of your repositories. To avoid issues, you may wish to disable the default force push branch protection rules on the destination repository.

## Hubcast bot
Depending on the setup of your Hubcast installation, you can request assistance from the bot by tagging an account (e.g., `@lc-hubcast help`) or the default `/hubcast help` in a PR/MR comment.

> [!TIP]
> Check with your Hubcast administrator to confirm the correct bot prefix for your instance.

The bot supports the following commands:
- `@{bot} help` - Display available commands and usage information
- `@{bot} approve` - Mirror this PR to the destination repo; Hubcast will push commits and run pipelines on behalf of the commenter
- `@{bot} restart pipeline` - Request a restart of the latest GitLab CI pipeline
- `@{bot} restart failed jobs` - Restart any failed jobs in the latest CI pipeline

Replace `@{bot}` with your instance's bot user (e.g., `@lc-hubcast`) or use `/hubcast` if no bot user is configured.

### Approval
To securely mirror changes from external collaborators, approvals must be done via commenting on a PR review, ensuring that it is linked to a specific commit.

`approve` always syncs the reviewed commit, even for a draft PR where `sync_drafts` is disabled for the repo.

![A GitHub pull request review; the user has written a comment `@lc-hubcast approve` to sync the user's contributions.](/docs/img/approve-comment.png)

> [!NOTE]
> Commenting on lines of code modified by the PR **will not** initiate mirroring; it must be done as shown above.
