import pytest
from pool.utils.scoring import calculate_points, calculate_winner


@pytest.mark.parametrize(
    "args, expected",
    [
        ([3, 0], "home"),
        ([0, 3], "away"),
        ([3, 3], "draw"),
        ([0, 0], "draw"),
    ],
)
def test_calculate_winner(args, expected):
    assert calculate_winner(*args) == expected


@pytest.mark.parametrize(
    "args, expected",
    [
        ([2, 1, 2, 1], (10, "exact")),
        ([3, 1, 2, 0], (7, "partial")),
        ([2, 0, 1, 0], (5, "partial")),
        ([1, 1, 0, 0], (5, "partial")),
        ([2, 0, 3, 0], (5, "partial")),
        ([3, 1, 1, 3], (0, "wrong")),
        ([2, 0, 0, 1], (0, "wrong")),
        ([1, 1, 2, 0], (0, "wrong")),
        ([2, 0, 1, 1], (0, "wrong")),
        ([0, 0, 0, 0], (10, "exact")),
    ],
)
def test_calculate_points(args, expected):
    assert calculate_points(*args) == expected
