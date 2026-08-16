from truckerworld_bot.cogs.tasks import BackgroundTasksCog


def test_reopen_queue_is_polled_for_near_real_time_sync() -> None:
    assert BackgroundTasksCog.ticket_reopen_watch.seconds == 5.0
