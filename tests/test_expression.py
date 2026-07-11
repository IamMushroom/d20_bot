import pytest

from dice.expression import normalize_input, parse_roll_expression


@pytest.mark.parametrize(
    ('expression', 'expected'),
    [
        ('d20', ((1, (1, 20)),)),
        ('2D6', ((1, (2, 6)),)),
        ('8к10', ((1, (8, 10)),)),
        ('1d12 + 1d6', ((1, (1, 12)), (1, (1, 6)))),
        ('1d10 - 4', ((1, (1, 10)), (-1, 4))),
        ('2d20 - 1d4 + 3', ((1, (2, 20)), (-1, (1, 4)), (1, 3))),
    ],
)
def test_parse_valid_expression(expression, expected):
    assert parse_roll_expression(expression) == expected


@pytest.mark.parametrize(
    'expression',
    [
        '',
        'abc',
        '2dd6',
        '1d12d20',
        '1d12 + 1k20',
        '1d12 * 1к20',
        '1е12',
        '1d6 +',
        '1d6++2',
        '1d6 -- 2',
        '1d6 / 2',
        '(1d6 + 2)',
        '1d6 + d',
        '0d6',
        '1d0',
        '101d6',
        '1d1001',
        '60d6 + 41d8',
        '1d6 + 1000001',
    ],
)
def test_reject_invalid_expression(expression):
    assert parse_roll_expression(expression) is None


def test_normalize_implicit_dice_count():
    assert normalize_input('d12') == (1, 12)
