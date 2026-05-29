from types import SimpleNamespace

from memocheck.evals.judge import make_judge


def fake_completion(content: str, calls: list | None = None):
    """A stand-in for litellm.completion returning a fixed message content."""

    def _complete(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return _complete


def test_judge_parses_same_item_true():
    judge = make_judge(
        complete=fake_completion('{"same_item": true, "reason": "same task"}'),
        cache={},
    )
    assert judge("book the campsite for the trip", "book campsite") is True


def test_judge_parses_same_item_false():
    judge = make_judge(
        complete=fake_completion('{"same_item": false, "reason": "different action"}'),
        cache={},
    )
    assert judge("review the proposal", "send the proposal") is False


def test_judge_strips_markdown_fenced_json():
    judge = make_judge(
        complete=fake_completion('```json\n{"same_item": true}\n```'),
        cache={},
    )
    assert judge("a", "b") is True


def test_judge_caches_verdict_per_pair():
    calls: list = []
    judge = make_judge(
        complete=fake_completion('{"same_item": true}', calls), cache={}
    )

    assert judge("a", "b") is True
    assert judge("a", "b") is True
    assert len(calls) == 1  # second identical pair served from cache

    judge("a", "c")
    assert len(calls) == 2  # a distinct pair triggers a fresh call
