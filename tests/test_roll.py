import pytest

from dice import roll as roll_module


def test_regular_roll_uses_each_generated_value(monkeypatch):
    values = iter((2, 5, 3))
    monkeypatch.setattr(roll_module, 'randint', lambda _minimum, _maximum: next(values))

    assert roll_module.roll_regular(3, 6) == (2, 5, 3)


@pytest.mark.parametrize(
    ('generated', 'expected'),
    [
        (1, 1),
        (20, 20),
        (21, 1),
        (22, 20),
    ],
)
def test_weighted_roll_maps_extra_values_to_extremes(monkeypatch, generated, expected):
    monkeypatch.setattr(roll_module, 'randint', lambda _minimum, _maximum: generated)

    assert roll_module.roll_d20(1, 20) == (expected,)


def test_evaluate_expression_with_dice_and_modifiers():
    def fixed_roller(count, _sides):
        return tuple(range(1, count + 1))

    result = roll_module.evaluate_roll_expression('2d6 - 1d4 + 3', fixed_roller)

    assert result == ('🎲 Итог: 5\n🧮 Расчёт:\n• 2d6: 1 + 2 = 3\n• − 1d4: 1 = 1\n• + 3')


def test_evaluate_invalid_expression():
    assert roll_module.evaluate_roll_expression('2dd6', roll_module.roll_regular) is None


@pytest.mark.parametrize(
    ('hope', 'fear', 'outcome'),
    [
        (10, 4, 'с надеждой'),
        (4, 10, 'со страхом'),
        (7, 7, 'КРИТ!'),
    ],
)
def test_duality_outcome(monkeypatch, hope, fear, outcome):
    values = iter((hope, fear))
    monkeypatch.setattr(roll_module, 'randint', lambda _minimum, _maximum: next(values))

    result = roll_module.dgh()

    assert f'Твой бросок {hope + fear} {outcome}' in result
    assert f'Надежда: {hope}' in result
    assert f'Страх: {fear}' in result
    assert 'Модификатор' not in result


@pytest.mark.parametrize(
    ('modifier', 'total', 'display'),
    [
        (5, 17, '5'),
        (-3, 9, '−3'),
    ],
)
def test_duality_modifier(monkeypatch, modifier, total, display):
    values = iter((8, 4))
    monkeypatch.setattr(roll_module, 'randint', lambda _minimum, _maximum: next(values))

    result = roll_module.dgh(modifier)

    assert f'Твой бросок {total} с надеждой' in result
    assert f'Модификатор: {display}' in result
