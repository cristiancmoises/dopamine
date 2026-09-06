"""Locale-dependent labels for fictional units, never exchange rates or money.

Stored integers keep their historical values. Changing language changes only the
symbol/separators, including old receipts. English deliberately defaults to USD.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Currency:
    code: str
    symbol: str
    grouping: str
    decimal: str
    decimals: int

CURRENCIES = {
    "pt-br": Currency("BRL", "R$", ".", ",", 2),
    "en": Currency("USD", "US$", ",", ".", 2),
    "zh": Currency("CNY", "CN¥", ",", ".", 2),
    "ja": Currency("JPY", "JP¥", ",", ".", 0),
}

def currency(language: str) -> Currency:
    return CURRENCIES.get(language, CURRENCIES["pt-br"])

def money(value: int, language: str = "pt-br") -> str:
    if type(value) is not int:
        raise TypeError("Fictional values must be whole integer units")
    selected = currency(language)
    digits = format(abs(value), ",").replace(",", selected.grouping)
    tail = selected.decimal + "0" * selected.decimals if selected.decimals else ""
    return ("−" if value < 0 else "") + selected.symbol + " " + digits + tail

def infinity(language: str = "pt-br") -> str:
    return currency(language).symbol + " ∞"
