# Architecture

This document describes Hubcast's architecture, explaining the system's design principles, trust model, and core interactions to provide a comprehensive understanding of how Hubcast operates.

The scope is limited to how Hubcast brokers events, identities, and repository state across security boundaries. It does not cover implementation details or specific deployment configurations.

## Overview

Hubcast operates between two Git forges with different trust assumptions: a source forge, where contributors collaborate and initiate actions, and a destination forge, where CI pipelines are executed on restricted infrastructure.
Hubcast acts as a coordinating service that receives events from both environments, validates intent and authorization, and syncs repository state and status without directly executing user code.

In a typical deployment, Hubcast is exposed to both forges through a webhook endpoint and has outbound access to their REST APIs. A user mapping component provides identity resolution between external (source forge) and site-local (destination forge) users. Existing CI workflows remain unchanged and are treated as independent systems that Hubcast observes and reports on, rather than controls.

## Key concepts

Hubcast's architecture is built around a small set of core concepts that define how actions are interpreted, authorized, and executed across systems.

An **event** is any notification originating from a forge that represents a user action or state change, such as a push, pull request update, comment, or CI job status. All inbound events are treated as untrusted until they are authorized.

The **source forge** is the system where collaboration occurs and where user intent is expressed, while the **destination forge** is the system where the repository state is mirrored and CI pipelines are executed. Hubcast preserves the native permission and security model of each forge while coordinating between them.

A **user mapping** associates a user identity on the source forge with a corresponding identity on the destination. The mapping is used to determine whether an action is permitted and, if so, which destination identity Hubcast should act as when performing actions. Authorized users on the source forge can act as **approvers** for state-changing actions taken by other users.

Hubcast is trusted to relay events, validate state, and enforce authorization decisions, but it cannot bypass forge permissions, execute CI workloads, or make independent policy decisions outside of its configured rules.

## Trust model and security boundaries

Hubcast is designed to operate across a clear boundary between systems with different trust assumptions. The source forge is treated as the authoritative origin of user identity, intent, and repository state, while the destination forge is the environment for executing CI workloads and enforcing site-local access controls. These systems don't directly trust one another; Hubcast serves as an intermediary that coordinates interactions.

All inbound events received by Hubcast are considered untrusted until validated against their source. Webhook payloads are authenticated using secrets or application credentials.

By design, failures at the trust boundary, such as malformed events and unresolved identities, result in inaction rather than unsafe execution.

## Identity, authorization, and approval flow

User actions handled by Hubcast originate from identities on the source forge but may result in execution on infrastructure governed by site-local policies. To safely bridge this gap, Hubcast includes a user mapping component as the authoritative source of identity linkage.

When an event is received, Hubcast extracts the initiating source forge user and queries the user mapping to resolve the corresponding destination forge user. If no mapping exists, Hubcast treats the initiating user as unauthorized and will not perform state-changing actions.

Hubcast allows for authorized users to "approve" unauthorized actions. When an approval is requested (via a comment on the source forge, see the [user guide](/docs/guide-user.md#hubcast-bot)), Hubcast performs the requested operation by assuming the identity of the approver, ensuring that all actions remain subject to existing permission models.

Hubcast includes [implementations](/docs/guide-admin.md#account-maps) of account maps, allowing administrators of Hubcast instances to decide the best fit for their organization.

## Repository synchronization

Hubcast syncs repo state from the source forge to the destination in response to validated events. Synchronization is limited to Git data and metadata required to reflect contributor intent, such as branch and pull request references.

Repository mapping is configured on a per-repository basis using a configuration file originating in the source repository. This configuration defines the destination forge location and controls some [Hubcast settings](/docs/guide-user.md#configuration). Hubcast reads this configuration from the default branch of the source repository.

When a synchronization is initiated, Hubcast fetches the relevant references from the source forge and pushes them to the destination forge using credentials from the resolved user identity. If the user lacks sufficient permissions on the destination repository, the sync will fail.

## CI status reporting

Hubcast propagates CI results from the destination forge back to the source forge to provide contributors with timely feedback within their existing workflows. CI pipelines are executed by the destination forge using its built-in mechanisms; Hubcast observes and reports on their outcomes.

The destination forge is configured to emit webhook events for pipeline and job status changes to Hubcast. Each webhook request includes query parameters that identify the corresponding source repository and check context, such as the source owner, repository name, and check identifier. Hubcast uses this information to associate CI results with the appropriate reference on the source forge. These parameters are required because CI events from the destination do not encode the source forge context.

After validating the webhook, Hubcast reports the pipeline state from the destination forge to the source forge using its checks or status APIs. Various states are forwarded, such as failed, successful, skipped, and in-progress pipelines.

## Deployment

Hubcast is deployed as a long-running service accessible to the forges via a public-facing webhook endpoint.

Access to the source forge is usually provided through an application-based integration, such as a GitHub App, which allows Hubcast to receive events and post status updates with narrowly scoped permissions. Access to the destination forge is granted via tokens that reflect the chosen permissions model, either by impersonating resolved user identities or operating through a dedicated service account with constrained repository access.

A single Hubcast instance may serve multiple repositories and organizations, provided that permissions and account mappings are configured.

## API surface

Hubcast exposes a small web API focused on event ingestion and status callbacks. These endpoints are not intended for general use and are only accessed by configured forges.

Inbound events are received through dedicated webhook endpoints for the source and destination forges, which accept `POST` requests containing event payloads and authentication information.

`v1` of the Hubcast API is defined as follows:

- `/v1/events/src/github`:  GitHub source forge event handler
- `/v1/events/src/gitlab`:  GitLab source forge event handler
- `/v1/events/dest/gitlab`: GitLab destination forge event handler

Only one source forge event handler is registered per Hubcast instance, based on its configured source forge.
