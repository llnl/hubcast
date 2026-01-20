# Hubcast

Hubcast is an event-driven service that securely syncs repository state between Git forges. It is designed for workflows where code collaboration happens on a public forge (such as GitHub.com), but testing must occur on restricted infrastructure (such as an HPC center or an internal network).

Many organizations operate compute environments that cannot directly interact with public Git forges due to security, network, or policy constraints. At the same time, developers rely on public forges for collaboration and visibility.

This tension is addressed by allowing projects to keep their existing development workflows while safely integrating external compute resources.

Hubcast acts as a trusted intermediary between two Git forges:
- The source forge is where contributors collaborate (pull requests, reviews, comments).
- The destination forge is where CI jobs are executed.

Repository state and CI status are synced between these two environments without requiring contributors to directly access restricted infrastructure.

## Architecture

<!-- TODO DIAGRAM IN HERE -->

At a high level, Hubcast sits between two Git forges and brokers events, repository state, and trust.

Four core functions:
1. Receiving events from the source forge (pull request, pushes, comments).
2. Evaluating whether actions are permitted based on the user's identity.
3. Synchronizing repository state to the destination forge.
4. Reporting CI results back to the source forge.

## What Hubcast does not do

The scope is intentionally limited to support flexible and secure deployment:
- CI jobs are not executed directly
- Existing CI systems or workflow managers are not replaced (keep your existing `.gitlab-ci.yml` files)
- Forge permission models are not bypassed

Hubcast's role is to simply coordinate among existing systems, not to replace them.

## Supported forges

### Source forge
- GitHub.com
- GitLab (coming soon)

### Destination forge
- Any GitLab instance

## Documentation by Role

- **[User](/docs/guide-user.md)**: You contribute to a project that uses Hubcast to execute CI pipelines on external infrastructure.
- **[Administrator](/docs/guide-admin.md)**: You deploy and operate Hubcast.
- **[Developer](/docs/guide-developer.md)**: You maintain the Hubcast or add new features.
