import pytest

from dice.expression import DiceTerm, ModifierTerm, normalize_input, parse_roll_expression


@pytest.mark.parametrize(
    ('expression', 'expected'),
    [
        ('d20', (DiceTerm(1, 20),)),
        ('2D6', (DiceTerm(2, 6),)),
        ('8к10', (DiceTerm(8, 10),)),
        ('4d6kh3', (DiceTerm(4, 6, keep='kh', keep_count=3),)),
        ('2D20KL1', (DiceTerm(2, 20, keep='kl', keep_count=1),)),
        ('1d12 + 1d6', (DiceTerm(1, 12), DiceTerm(1, 6))),
        ('1d10 - 4', (DiceTerm(1, 10), ModifierTerm(4, -1))),
        (
            '2d20 - 1d4 + 3',
            (DiceTerm(2, 20), DiceTerm(1, 4, -1), ModifierTerm(3)),
        ),
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
        '4d6kh0',
        '4d6kh5',
        '4d6kh',
        '4d6ka3',
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
