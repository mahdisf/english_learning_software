from english_coach.mastery import QualifyingEvent, compute_mastery, mistake_state


def _events(pattern: list[bool], sessions: list[str] | None = None) -> list[QualifyingEvent]:
    sessions = sessions or [f"s{i}" for i in range(len(pattern))]
    return [QualifyingEvent(session_id=s, correct=c) for s, c in zip(sessions, pattern)]


def test_no_events_gives_zero_new():
    result = compute_mastery([])
    assert result.score == 0
    assert result.status == "new"


def test_learning_status_boundary():
    # 1 incorrect event: accuracy 0% -> 0, volume 3, session 4 -> score 7 (learning range).
    result = compute_mastery(_events([False]))
    assert 1 <= result.score <= 39
    assert result.status == "learning"


def test_practicing_status_boundary():
    # 3 correct events in 1 session: accuracy_component=50, volume=9, session=4 -> score 63.
    events = _events([True, True, True], sessions=["s1", "s1", "s1"])
    result = compute_mastery(events)
    assert result.score == 63
    assert result.status == "practicing"


def test_mastery_formula_matches_spec():
    # 5 correct out of 5 events across 3 distinct sessions.
    events = _events([True, True, True, True, True], sessions=["s1", "s1", "s2", "s3", "s3"])
    result = compute_mastery(events)
    accuracy_component = round(50 * 1.0)
    volume_component = min(30, 5 * 3)
    session_component = min(20, 3 * 4)
    expected = accuracy_component + volume_component + session_component
    assert result.score == expected


def test_strong_status():
    events = _events([True] * 8, sessions=[f"s{i}" for i in range(8)])
    result = compute_mastery(events)
    assert result.status in ("strong", "mastered")
    assert result.score >= 70


def test_mastered_requires_all_conditions():
    # 12 qualifying events, 5 distinct sessions, all correct, last three correct.
    sessions = ["s1", "s1", "s2", "s2", "s3", "s3", "s4", "s4", "s5", "s5", "s5", "s5"]
    events = _events([True] * 12, sessions=sessions)
    result = compute_mastery(events)
    assert result.status == "mastered"
    assert result.score >= 90


def test_mastered_fails_if_last_three_not_all_correct():
    sessions = ["s1", "s1", "s2", "s2", "s3", "s3", "s4", "s4", "s5", "s5", "s5", "s5"]
    pattern = [True] * 11 + [False]
    events = _events(pattern, sessions=sessions)
    result = compute_mastery(events)
    assert result.status != "mastered"


def test_mistake_state_resolved_requires_five_correct_three_sessions():
    assert mistake_state(5, 3) == "resolved"
    assert mistake_state(4, 3) == "improving"
    assert mistake_state(5, 2) == "improving"
    assert mistake_state(0, 0) == "active"


def test_mistake_state_manual_override_wins():
    assert mistake_state(0, 0, manual_override="resolved") == "resolved"
