"""Strict numerical boundaries for untrusted infrastructure observations."""
import math


def nonnegative(value, name, *, integer=False):
    kinds = (int,) if integer else (int, float)
    if type(value) not in kinds or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative {'integer' if integer else 'number'}")
    return value
