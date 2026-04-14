def american_to_decimal(american):
    american = int(american.replace('+', ''))
    if american > 0:
        return (american / 100) + 1
    else:
        return (100 / abs(american)) + 1

def decimal_to_american(decimal):
    if decimal >= 2.0:
        return f'+{int((decimal - 1) * 100)}'
    else:
        return f'{int(-100 / (decimal - 1))}'

def parlay_odds(american_odds_list):
    decimal = 1.0
    for odds in american_odds_list:
        decimal *= american_to_decimal(odds)
    return decimal_to_american(decimal)

def implied_probability(american):
    decimal = american_to_decimal(american)
    return round(1 / decimal * 100, 2)
