import re
from dataclasses import dataclass

MAX_DICE_COUNT = 100
MAX_DICE_SIDES = 1000
MAX_MODIFIER = 1_000_000
MAX_EXPRESSION_TERMS = 20

_DICE_EXPRESSION = re.compile(r'^(\d*)[dDкК](\d+)(?:(kh|kl)(\d+))?$', re.IGNORECASE)


@dataclass(frozen=True)
class DiceTerm:
    count: int
    sides: int
    sign: int = 1
    keep: str | None = None
    keep_count: int | None = None


@dataclass(frozen=True)
class ModifierTerm:
    value: int
    sign: int = 1


ExpressionTerm = DiceTerm | ModifierTerm
RollExpression = tuple[ExpressionTerm, ...]


def parse_dice_term(string: str, sign: int = 1) -> DiceTerm | None:
    match = _DICE_EXPRESSION.fullmatch(string.strip())
    if match is None:
        return None

    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    keep = match.group(3).lower() if match.group(3) else None
    keep_count = int(match.group(4)) if match.group(4) else None
    if not 1 <= count <= MAX_DICE_COUNT:
        return None
    if not 1 <= sides <= MAX_DICE_SIDES:
        return None
    if keep_count is not None and not 1 <= keep_count <= count:
        return None

    return DiceTerm(count=count, sides=sides, sign=sign, keep=keep, keep_count=keep_count)


def normalize_input(string: str) -> tuple[int, int]:
    term = parse_dice_term(string)
    if term is None or term.keep is not None:
        return (0, 0)

    return (term.count, term.sides)


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

        dice = parse_dice_term(raw_term, sign)
        if dice is not None:
            total_dice += dice.count
            if total_dice > MAX_DICE_COUNT:
                return None
            terms.append(dice)
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
