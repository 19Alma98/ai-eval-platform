# Configuration and errors

Where the SDK sends data, with which credentials, and for which project.

Configuration is scoped to an `Opengrade` instance (`Settings`, or `OPENGRADE_*` env vars at construction). Activate an instance for ambient helpers via `current()`.

::: opengrade._state.Settings

::: opengrade._opengrade.Opengrade
    options:
      members:
        - __init__
        - settings
        - client
        - async_client
        - set_project
        - aset_project
        - get_project
        - configure_capture
        - activate
        - close

::: opengrade._opengrade.current

::: opengrade._errors.OpengradeError

::: opengrade._errors.OpengradeAPIError

::: opengrade._errors.OpengradeConnectionError
