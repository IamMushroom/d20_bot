def format(format: str) -> str:
    formats = {
        "json": '{"datetime": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": {%(message)s}}'
    }
    return formats[format]