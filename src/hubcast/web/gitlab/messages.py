def help_message(bot_caller: str) -> str:
    return f"""
You can interact with me in many ways!

- `{bot_caller} approve`:
    - Mirror this MR to the destination repo
    - Hubcast will perform actions on behalf of the commenter
    - Must be called from a comment on a specific line in the MR's diff (a "diff note"), not a regular MR comment
- `{bot_caller} restart pipeline`: request a restart of the latest GitLab CI pipeline
- `{bot_caller} restart failed jobs`: restart any failed jobs in the latest pipeline
- `{bot_caller} help`: see this message

If you are an outside contributor, a maintainer will need to mirror your changes using the `{bot_caller} approve` command.

A [user guide](https://github.com/llnl/hubcast/blob/main/docs/guide-user.md) is available for additional details on Hubcast's functionality.

For assistance and bug reports, open an issue [here](https://github.com/llnl/hubcast/issues).
"""
