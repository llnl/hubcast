# Developer Guide

Thank you for contributing to Hubcast! Before you read this guide, take a look at our intro [contributing document](/docs/CONTRIBUTING.md).

In this section of the documentation, we'll cover how to set up an initial development environment and some common tasks you may perform within Hubcast's codebase.

## Development Environment

We recommend using Spack to initialize your development environment.

### Prerequisites
You'll need to install Spack if you haven't already. 
You can clone Spack from Github by running the following:

```bash
$ git clone -c feature.manyFiles=true https://github.com/spack/spack.git
$ cd spack/
```

Next we'll need to load Spack into our shell. (Add one of the following lines -- prepended by the directory you cloned spack into -- to your `.zshrc`, `.bashrc`, or equivalent to make it permanent.)

```bash
# For bash/zsh/sh
$ . spack/share/spack/setup-env.sh

# For tcsh/csh
$ source spack/share/spack/setup-env.csh

# For fish
$ . spack/share/spack/setup-env.fish
```

### Activating
Activate the Spack environment by entering the following,
```bash
$ cd path/to/hubcast
$ spack env activate -d .
```

> [!TIP]
> If you have [direnv](https://direnv.net) installed on your system
> you can run `direnv allow` to automatically load the Spack environment
> when you cd into the repository in the future.

### Installing
Install Hubcast's development dependencies with Spack by running the following:

```bash
$ spack install
```

### Upgrading
To update your Spack environment run:
```bash
$ spack concretize --force --fresh
$ spack install
```

### Testing a local Hubcast instance

To test your development version of Hubcast on a real-world GitHub -> GitLab syncing example, we recommend using [smee.io](https://smee.io) to forward webhooks.

For example, go to [smee.io](https://smee.io), start a new channel, and from the command line forward a local Hubcast endpoint to the new channel. 
Note that you will need to set up two channels: one for the source webhook handler and another for the destination handler.

```
smee -u https://smee.io/HASH -t http://localhost:8080/v1/events/src/github
```

## Development Tasks

### Account Maps
Account maps are used by Hubcast to link user accounts between Git forges. Hubcast ships with implementations like a YAML file mapper, with plans to include LDAP and GitHub OAuth mappers.

To write your own account mapper, see the abstract base class in [`src/hubcast/account_map/abc.py`](/src/hubcast/account_map/abc.py) and current implementations in the `account_map` directory.

The basic idea is to define an input (a file, metadata from a webhook) where the initiating user is identified, along a way to link that user's identity to an account on the destination forge.
