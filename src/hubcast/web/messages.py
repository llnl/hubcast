CONFIG_DOCS_URL = (
    "https://github.com/llnl/hubcast/blob/main/docs/guide-user.md#configuration"
)
CONFIG_INVALID_TITLE = "Hubcast configuration file is invalid"
CONFIG_INVALID_SUMMARY = (
    "Hubcast could not parse `hubcast.yml`. "
    f"Fix the configuration file and retry. See the [user guide]({CONFIG_DOCS_URL}) for details."
)
CONFIG_VALID_TITLE = "Hubcast config file is valid"
CONFIG_VALID_SUMMARY = (
    "Hubcast has validated `hubcast.yml`. "
    "These changes will take effect once merged into the default branch."
)

PERMISSION_DENIED_TITLE = (
    "Hubcast couldn't sync your changes due to insufficient permissions."
)
PERMISSION_DENIED_SUMMARY = 'Hubcast requires all users to have at least the "developer" role on the destination repository or have a repository maintainer mirror changes [on your behalf](https://github.com/llnl/hubcast/blob/main/docs/guide-user.md#secure-mirroring).'
PERMISSION_DENIED_SYNC_LOG_MSG = (
    "Failed to sync ref: insufficient permissions on destination repository."
)
PERMISSION_DENIED_DELETE_LOG_MSG = (
    "Failed to delete ref: insufficient permissions on destination repository."
)

# raised by repligit's send_pack when the destination rejects the ref update (e.g. protected branches)
HOOK_DECLINED_MSG = "pre-receive hook declined"
HOOK_DECLINED_TITLE = (
    "Push to GitLab failed: check branch protection settings and retry."
)
HOOK_DECLINED_SUMMARY = f"Hubcast got `{HOOK_DECLINED_MSG}` when pushing changes. In most cases, this happens when a force push is initiated and the destination repository has branch protection rules enabled."

INTERNAL_ERROR_TITLE = "Hubcast internal error"
INTERNAL_ERROR_SUMMARY = (
    "Hubcast encountered an internal error while processing this event. "
    "This is not caused by your repository configuration or permissions. "
    "Please contact the admins of this Hubcast instance."
)

WEBHOOK_PERMISSION_DENIED_TITLE = (
    "Hubcast couldn't update its configuration due to insufficient permissions."
)
WEBHOOK_PERMISSION_DENIED_SUMMARY = 'Hubcast was unable to propagate changes to its configuration due to insufficient permissions on the destination repository. Users who push changes to Hubcast configuration files must have at least the "maintainer" role on the destination repository.\nTo correct this, a user with the maintainer role can push a commit with `[hubcast config]` in the message or a commit with additional changes to the Hubcast configuration file.'

DEACTIVATED_ACCOUNT_MARKER = "Your account has been deactivated by your administrator."
DEACTIVATED_ACCOUNT_MSG = (
    "Your account on the destination GitLab instance is deactivated."
)
PIPELINE_FAILED_MSG = "GitLab could not start the pipeline. Investigate the issue in your GitLab CI configuration"
