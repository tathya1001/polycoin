def init_sentry(dsn: str, release: str, environment: str = "production") -> None:
    """Send unhandled errors to Sentry, keeping request data and local variables out of them.

    Decrypted narrations and amounts exist as local variables inside views and services, so
    the settings that matter here are the ones that stop Sentry from capturing them. Exception
    messages are still sent, so they must never contain user data (AIError and ImportProblem
    are already written that way).
    """
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        release=release,
        environment=environment,
        send_default_pii=False,  # no cookies, auth headers, user ids, or IP addresses
        include_local_variables=False,  # frames would otherwise carry decrypted values
        max_request_body_size="never",  # uploaded statements and JSON bodies are private
        traces_sample_rate=0,  # errors only: no performance traces
    )
