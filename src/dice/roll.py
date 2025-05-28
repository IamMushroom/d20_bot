from random import randint
from typing import Tuple

def roll_regular(count: int, dice: int) -> Tuple[int, ...]:
    result = ()
    for _ in range(count):
        result += (randint (1, dice),)
    return result

def roll_d20(count: int, dice: int) -> Tuple[int, ...]:
    result = ()
    for _ in range(count):
        r = randint (1, dice + 2)
        if r == dice + 1: r = 1
        if r == dice + 2: r = dice
        result += (r,)
    return result

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
    result = f"Твой бросок {s} (надежда: {hope}, страх: {fear})"
    return result
