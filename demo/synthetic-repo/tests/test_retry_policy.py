from src.job_runner import RetryPolicy


def test_retry_policy_builds_bounded_exponential_delays() -> None:
    policy = RetryPolicy(max_attempts=3, base_delay_seconds=0.25)

    assert policy.delays() == (0.25, 0.5)
