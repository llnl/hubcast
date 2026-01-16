<!-- ## Trust model

Hubcast is designed to operate across security boundaries between systems with different trust assumptions.

The source forge (for example, GitHub.com) is the origin of contributor identity, repository state, and intended actions (such as PRs and other changes). The destination forge provides the compute resources needed to execute CI jobs and details for authorizing access to the resources.

Hubcast is trusted by both forges to relay events and synchronize state, but it does not execute code and does not bypass the permission models of either forge.

## Identity management and authorization

Events received by Hubcast originate from users on the source forge, while the execution of code on the destination forge may require vetting and explicit approval by an organization.

To safely coordinate these actions, Hubcast requires a mapping between identities on the source and destination forges. This mapping is used to determine how user actions on the source forge are represented on the destination forge and whether those actions can be processed.

TODO if a user is not in the account map, they aren't allowed to perform any actions...users in the account map can delegate and approve others to do stuff on their behalf...

Hubcast supports multiple account mapping mechanisms, such as static files, LDAP, and OAuth.

## Repository scope and deployment model

A single Hubcast instance may service the syncing of multiple repositories.

Hubcast is granted access to a variety of actions (webhook sending, read/write to repository, etc.) on both forges through mechanisms like GitHub apps and GitLab personal access tokens.

Administrators grant Hubcast the permissions required to access repositories on both forges. Users configure repository-specific settings through a separate process. -->

explain the URL structure of how the API is set up...

TODO document what an account map does?