# User Guide

This guide covers usage of Hubcast to sync repository state between Git forges.

First, identify the source and destination repositories Hubcast will be syncing.

## Configuration

Hubcast settings for each repository are defined in the `hubcast.yml` file. Create this file at `.github/hubcast.yml` in your repository:

```yaml
Repo:
  # Required: organization or user that owns the repo on the destination forge
  dest_org: example

  # Required: name of the destination repository
  dest_name: hubcast-test

  # Optional: name of the CI check as reported back to GitHub (default: gitlab-ci)
  check_name: gitlab-ci

  # Optional: granularity of CI statuses reported to GitHub (default: [pipeline])
  # Available types: pipeline, child-pipelines, jobs
  # You can mix and match any combination of these types
  # Examples:
  #   [pipeline] - overall pipeline status only (default behavior)
  #   [child-pipelines] - child pipeline statuses only
  #   [jobs] - individual job statuses only
  #   [pipeline, child-pipelines] - pipeline and child pipeline statuses
  #   [pipeline, jobs] - pipeline and job statuses
  #   [pipeline, child-pipelines, jobs] - all status types
  check_types: [pipeline]

  # Optional: delete branches from destination when source PR is closed (default: true)
  delete_closed: true

  # Optional: sync draft PRs/MRs (default: true)
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

Hubcast will sync changes via a force push if there has been a local change to the destination repository. To avoid issues, you may wish to disable the default force push branch protection rules on the destination repository.

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
To securely sync commits from external collaborators, approvals must be done via commenting on a PR review, ensuring that the approval is linked to a specific commit.

![A GitHub pull request review; the user has written a comment `@lc-hubcast approve` to sync the user's contributions.](/docs/img/approve-comment.png)

> [!NOTE]
> Commenting on lines of code modified by the PR **will not** approve syncing; it must be done as shown above.
