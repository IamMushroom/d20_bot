from random import randint
from typing import Callable, Optional, Tuple

from utils import parse_roll_expression

Roller = Callable[[int, int], Tuple[int, ...]]

def roll_regular(count: int, dice: int) -> Tuple[int, ...]:
    return tuple(randint(1, dice) for _ in range(count))

def roll_d20(count: int, dice: int) -> Tuple[int, ...]:
    result = []
    for _ in range(count):
        roll = randint(1, dice + 2)
        if roll == dice + 1:
            roll = 1
        elif roll == dice + 2:
            roll = dice
        result.append(roll)
    return tuple(result)


def evaluate_roll_expression(expression: str, roller: Roller) -> Optional[str]:
    terms = parse_roll_expression(expression)
    if terms is None:
        return None

    total = 0
    details = []
    for index, (sign, term) in enumerate(terms):
        operator = '- ' if sign < 0 else ('+ ' if index > 0 else '')
        if isinstance(term, tuple):
            count, sides = term
            rolls = roller(count, sides)
            total += sign * sum(rolls)
            details.append(f'{operator}{count}d{sides}: {" + ".join(map(str, rolls))}')
        else:
            total += sign * term
            details.append(f'{operator}{term}')

    return f'Your roll: {total} ({"; ".join(details)})'

def dgh() -> str:
    hope = randint(1, 12)
    fear = randint(1, 12)
    result = hope + fear
    if hope > fear:
        s = 'с надеждой'
    elif hope < fear:
        s = 'со страхом'
    else:
        s = 'КРИТ!'
    result = f"Твой бросок {result} {s} (надежда: {hope}, страх: {fear})"
    return result
