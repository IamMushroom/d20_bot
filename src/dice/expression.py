import re
from dataclasses import dataclass

MAX_DICE_COUNT = 100
MAX_DICE_SIDES = 1000
MAX_MODIFIER = 1_000_000
MAX_EXPRESSION_TERMS = 20

_DICE_EXPRESSION = re.compile(r'^(\d*)[dDкК](\d+)$')


@dataclass(frozen=True)
class DiceTerm:
    count: int
    sides: int
    sign: int = 1


@dataclass(frozen=True)
class ModifierTerm:
    value: int
    sign: int = 1


ExpressionTerm = DiceTerm | ModifierTerm
RollExpression = tuple[ExpressionTerm, ...]


def normalize_input(string: str) -> tuple[int, int]:
    match = _DICE_EXPRESSION.fullmatch(string.strip())
    if match is None:
        return (0, 0)

    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    if not 1 <= count <= MAX_DICE_COUNT:
        return (0, 0)
    if not 1 <= sides <= MAX_DICE_SIDES:
        return (0, 0)

    return (count, sides)


def parse_roll_expression(string: str) -> RollExpression | None:
    expression = re.sub(r'\s+', '', string)
    if not expression:
        return None

    terms = []
    total_dice = 0
    position = 0
    for match in re.finditer(r'([+-]?)([^+-]+)', expression):
        if match.start() != position:
            return None
        position = match.end()

        sign_text, raw_term = match.groups()
        sign = -1 if sign_text == '-' else 1

        dice = normalize_input(raw_term)
        if dice != (0, 0):
            total_dice += dice[0]
            if total_dice > MAX_DICE_COUNT:
                return None
            terms.append(DiceTerm(count=dice[0], sides=dice[1], sign=sign))
            continue

        if not raw_term.isdecimal():
            return None
        modifier = int(raw_term)
        if modifier > MAX_MODIFIER:
            return None
        terms.append(ModifierTerm(value=modifier, sign=sign))

    if position != len(expression) or not terms or len(terms) > MAX_EXPRESSION_TERMS:
        return None
    return tuple(terms)
