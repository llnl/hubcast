PERMISSION_DENIED_STATUSES = (
    401,
    403,
)
DEACTIVATED_ACCOUNT_MARKER = "Your account has been deactivated by your administrator."
DEACTIVATED_ACCOUNT_MSG = (
    "Your account on the destination GitLab instance is deactivated."
)
PERMISSION_DENIED_TITLE = (
    "Insufficient permissions on destination repository; user must have developer role."
)
PERMISSION_DENIED_DELETE_LOG_MSG = (
    "Failed to delete ref: insufficient permissions on destination repository."
)
PERMISSION_DENIED_SYNC_LOG_MSG = (
    "Failed to sync ref: insufficient permissions on destination repository."
)
PERMISSION_DENIED_SUMMARY = 'Hubcast requires all users to have at least the "developer" role on the destination repository. If editing the Hubcast configuration file, users must at least have the "maintainer" role to propagate changes.\nEdit the permission settings and retry.'

# raised by repligit's send_pack when the destination rejects the ref update (e.g. protected branches)
HOOK_DECLINED_MSG = "pre-receive hook declined"
HOOK_DECLINED_TITLE = (
    "Push to GitLab failed: check branch protection settings and retry."
)
HOOK_DECLINED_SUMMARY = f"Hubcast got `{HOOK_DECLINED_MSG}` when pushing changes. In most cases, this happens when a force push is initiated and the destination repository has branch protection rules enabled."
PIPELINE_FAILED_MSG = "GitLab could not start the pipeline. Investigate the issue in your GitLab CI configuration"

CONFIG_DOCS_URL = (
    "https://github.com/llnl/hubcast/blob/main/docs/guide-user.md#configuration"
)
CONFIG_NOT_FOUND_TITLE = "Hubcast configuration file not found."
CONFIG_NOT_FOUND_SUMMARY = f"Add the configuration file to the default branch and retry. See the [user guide]({CONFIG_DOCS_URL}) for details."
CONFIG_INVALID_TITLE = "Hubcast configuration file is invalid."
CONFIG_INVALID_SUMMARY = (
    "Hubcast could not parse `.github/hubcast.yml`. "
    f"Fix the configuration file and retry. See the [user guide]({CONFIG_DOCS_URL}) for details."
)


def help_message(bot_caller: str) -> str:
    return f"""
You can interact with me in many ways!

- `{bot_caller} approve`:
    - Mirror this PR to the destination repo
    - Hubcast will perform actions on behalf of the commenter
    - Must be called using the [GitHub review comment feature](https://github.com/llnl/hubcast/blob/main/docs/guide-user.md#approval)
- `{bot_caller} restart pipeline`: request a restart of the latest GitLab CI pipeline
- `{bot_caller} restart failed jobs`: restart any failed jobs in the latest pipeline
- `{bot_caller} help`: see this message

If you are an outside contributor, a maintainer will need to mirror your changes using the `{bot_caller} approve` command.

A [user guide](https://github.com/llnl/hubcast/blob/main/docs/guide-user.md) is available for additional details on Hubcast's functionality.

For assistance and bug reports, open an issue [here](https://github.com/llnl/hubcast/issues).
"""
