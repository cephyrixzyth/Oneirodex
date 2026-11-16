from oneirodex.utils.csv_safety import neutralize_spreadsheet_formulas


def test_neutralize_spreadsheet_formulas_prefixes_formula_cells():
    row = {
        'equals': '=1+1',
        'plus': '+SUM(A1:A2)',
        'minus': '-2+3',
        'at': '@SUM(A1:A2)',
        'leading_space': ' \t=1+1',
    }

    assert neutralize_spreadsheet_formulas(row) == {
        key: "'" + value for key, value in row.items()
    }


def test_neutralize_spreadsheet_formulas_preserves_safe_values_and_input():
    row = {'plain': 'Game title', 'empty': '', 'number': 42, 'none': None}

    assert neutralize_spreadsheet_formulas(row) == row
    assert row == {'plain': 'Game title', 'empty': '', 'number': 42, 'none': None}
