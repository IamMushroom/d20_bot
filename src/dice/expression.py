import re
from dataclasses import dataclass

MAX_DICE_COUNT = 100
MAX_DICE_SIDES = 1000
MAX_MODIFIER = 1_000_000
MAX_EXPRESSION_TERMS = 20
MAX_EXPRESSION_LENGTH = 200

_DICE_EXPRESSION = re.compile(r'^(\d*)[dDкК](\d+)(?:(kh|kl|k)(\d*))?$', re.IGNORECASE)


class RollParseError(ValueError):
    def __init__(self, message: str, fragment: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.fragment = fragment


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


def parse_dice_term_or_raise(string: str, sign: int = 1) -> DiceTerm:
    match = _DICE_EXPRESSION.fullmatch(string.strip())
    if match is None:
        raise RollParseError('неверная запись куба', string)

    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    keep = match.group(3).lower() if match.group(3) else None
    if keep == 'k':
        keep = 'kh'
    keep_count = int(match.group(4) or 1) if keep else None
    if not 1 <= count <= MAX_DICE_COUNT:
        raise RollParseError(f'число кубов должно быть от 1 до {MAX_DICE_COUNT}', string)
    if not 1 <= sides <= MAX_DICE_SIDES:
        raise RollParseError(f'число граней должно быть от 1 до {MAX_DICE_SIDES}', string)
    if keep_count is not None and not 1 <= keep_count <= count:
        raise RollParseError('нельзя оставить столько результатов', string)

    return DiceTerm(count=count, sides=sides, sign=sign, keep=keep, keep_count=keep_count)


def parse_dice_term(string: str, sign: int = 1) -> DiceTerm | None:
    try:
        return parse_dice_term_or_raise(string, sign)
    except RollParseError:
        return None


def normalize_input(string: str) -> tuple[int, int]:
    term = parse_dice_term(string)
    if term is None or term.keep is not None:
        return (0, 0)

    return (term.count, term.sides)


def parse_roll_expression_or_raise(string: str) -> RollExpression:
    if len(string) > MAX_EXPRESSION_LENGTH:
        raise RollParseError(f'выражение длиннее {MAX_EXPRESSION_LENGTH} символов')
    expression = re.sub(r'\s+', '', string)
    if not expression:
        raise RollParseError('пустое выражение')

    unsupported = re.search(r'[*/()]', expression)
    if unsupported:
        raise RollParseError('поддерживаются только операции + и −', unsupported.group())

    terms = []
    total_dice = 0
    position = 0
    for match in re.finditer(r'([+-]?)([^+-]+)', expression):
        if match.start() != position:
            raise RollParseError('лишний или повторный знак операции', expression[position:])
        position = match.end()

        sign_text, raw_term = match.groups()
        sign = -1 if sign_text == '-' else 1

        if re.search(r'[dDкК]', raw_term):
            dice = parse_dice_term_or_raise(raw_term, sign)
            total_dice += dice.count
            if total_dice > MAX_DICE_COUNT:
                raise RollParseError(
                    f'суммарно можно бросить не больше {MAX_DICE_COUNT} кубов', raw_term
                )
            terms.append(dice)
            continue

        if not raw_term.isdecimal():
            raise RollParseError('ожидался куб или целое число', raw_term)
        modifier = int(raw_term)
        if modifier > MAX_MODIFIER:
            raise RollParseError(f'модификатор не должен превышать {MAX_MODIFIER}', raw_term)
        terms.append(ModifierTerm(value=modifier, sign=sign))

    if position != len(expression):
        raise RollParseError('выражение обрывается после знака операции', expression[position:])
    if not terms:
        raise RollParseError('пустое выражение')
    if len(terms) > MAX_EXPRESSION_TERMS:
        raise RollParseError(f'разрешено не больше {MAX_EXPRESSION_TERMS} слагаемых')
    return tuple(terms)


def parse_roll_expression(string: str) -> RollExpression | None:
    try:
        return parse_roll_expression_or_raise(string)
    except RollParseError:
        return None
