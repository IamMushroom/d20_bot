from collections.abc import Callable
from random import randint

from dice.expression import DiceTerm, parse_roll_expression

Roller = Callable[[int, int], tuple[int, ...]]


def roll_regular(count: int, dice: int) -> tuple[int, ...]:
    return tuple(randint(1, dice) for _ in range(count))


def roll_d20(count: int, dice: int) -> tuple[int, ...]:
    result = []
    for _ in range(count):
        roll = randint(1, dice + 2)
        if roll == dice + 1:
            roll = 1
        elif roll == dice + 2:
            roll = dice
        result.append(roll)
    return tuple(result)


def evaluate_roll_expression(expression: str, roller: Roller) -> str | None:
    terms = parse_roll_expression(expression)
    if terms is None:
        return None

    total = 0
    details = []
    for index, term in enumerate(terms):
        operator = '− ' if term.sign < 0 else ('+ ' if index > 0 else '')
        if isinstance(term, DiceTerm):
            rolls = roller(term.count, term.sides)
            kept_rolls = rolls
            suffix = ''
            if term.keep and term.keep_count:
                reverse = term.keep == 'kh'
                kept_rolls = tuple(sorted(rolls, reverse=reverse)[: term.keep_count])
                suffix = f'{term.keep}{term.keep_count}'
            subtotal = sum(kept_rolls)
            total += term.sign * subtotal
            label = f'{term.count}d{term.sides}{suffix}'
            if term.keep:
                details.append(
                    f'• {operator}{label}: {", ".join(map(str, rolls))} → '
                    f'{" + ".join(map(str, kept_rolls))} = {subtotal}'
                )
            else:
                details.append(f'• {operator}{label}: {" + ".join(map(str, rolls))} = {subtotal}')
        else:
            total += term.sign * term.value
            details.append(f'• {operator}{term.value}')

    return f'🎲 Итог: {total}\n🧮 Расчёт:\n' + '\n'.join(details)


def dgh(modifier: int = 0) -> str:
    hope = randint(1, 12)
    fear = randint(1, 12)
    result = hope + fear + modifier
    if hope > fear:
        s = 'с надеждой'
    elif hope < fear:
        s = 'со страхом'
    else:
        s = 'КРИТ!'
    modifier_line = ''
    if modifier:
        operator = '' if modifier > 0 else '−'
        modifier_line = f'\n🧮 Модификатор: {operator}{abs(modifier)}'
    result = f'🎲 Твой бросок {result} {s}\n✨ Надежда: {hope}\n🌑 Страх: {fear}{modifier_line}'
    return result
