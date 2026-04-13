# Contributing

## Introduction
Hubcast welcomes contributions via [Pull Requests](https://github.com/LLNL/hubcast/pulls).
We've labeled beginner friendly (good first issue) tasks in the issue tracker. Feel free
to reach out and ask for help when getting started.

For small changes (e.g. bug fixes), feel free to submit a PR.

For larger architectural changes and new features, consider opening an
[issue](https://github.com/LLNL/hubcast/issues/new?template=issue-feature-request.md) outlining your
proposed contribution.

## Prerequisites
Hubcast is written in Python. You'll need a version of Python and pip to
install the required dependencies and Node.js to install the
[smee-client](https://www.npmjs.com/package/smee-client) to test the application locally.

You can install the full development environment using [Spack](/docs/guide-developer.md#development-environment).

## Development
After cloning the Hubcast repository, we recommend reading through the [documentation](/docs/readme.md) and each guide ([admin](/docs/guide-admin.md), [user](/docs/guide-user.md), [developer](/docs/guide-developer.md)) to understand how to use Hubcast and set up your local environment.

> [!TIP]
> If you're developing locally you can use [smee.io](https://smee.io) to relay
> webhooks to your local machine. Just click "start a new channel" and then run
> the following, substituting your channel url as the argument and GitHub App
> endpoint.
>
> ```bash
> $ smee -u https://smee.io/reDaCTed
> ```

## Project Structure
```bash
.
├── LICENSE
├── README.md
├── docs # ---------> project documentation
├── src # ----------> Python application
├── spack # --------> Spack package files
├── pyproject.toml
└── spack.yaml # ---> Spack development environment
```
```bash
src/hubcast
├── __main__.py # --> Hubcast entrypoint and config setup
├── config.py # ----> Hubcast config manager
├── logging.py # ---> Hubcast logging config
├── account_map # --> User mapping between Git forges
├── clients # ------> GitHub & GitLab auth and API clients
├── repos # --------> Hubcast-managed Git repo config
├── web # ----------> GitHub & GitLab event routing logic
```
