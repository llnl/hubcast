def help_message(bot_caller: str) -> str:
    return f"""
You can interact with me in many ways!

- `{bot_caller} approve`: 
    - Manually sync this PR to the destination repo
    - Hubcast will perform syncs and run pipelines on behalf of the commenter
- `{bot_caller} run pipeline`: request a new run of the GitLab CI pipeline
- `{bot_caller} restart failed jobs`: restart any failed jobs in the most recent pipeline
- `{bot_caller} help`: see this message

If you are an outside contributor, a maintainer will need to approve your commits using the [GitHub review comment feature](https://github.com/llnl/hubcast/blob/main/docs/guide-user.md#approval).

For assistance and bug reports, open an issue [here](https://github.com/llnl/hubcast/issues).
"""
