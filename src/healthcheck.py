import json
from os import getenv
from urllib.request import urlopen

HEALTHCHECK_ERRORS = (OSError, ValueError)


def telegram_is_available(token: str, timeout: float = 5) -> bool:
    if not token:
        return False

    try:
        with urlopen(f'https://api.telegram.org/bot{token}/getMe', timeout=timeout) as response:
            payload = json.load(response)
    except HEALTHCHECK_ERRORS:
        return False
    return response.status == 200 and payload.get('ok') is True


def main() -> int:
    return 0 if telegram_is_available(getenv('TG_TOKEN', '')) else 1


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
