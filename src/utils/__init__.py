from typing import Tuple

def normalize_input(string: str) -> Tuple[int, int]:
    r = string.split('d')    
    if len(r) == 1:
        r = string.split('к')
    if len(r) == 1:
        return (0,0)
    return (int(r[0]), int(r[1]))