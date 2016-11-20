import pytest
import datetime

from distaff import Distaff, ValidationError, MISSING


def test_date():
    schema = {'type': 'date'}

    distaff = Distaff(schema, '2016-01-01')
    assert distaff.native() == datetime.date(2016, 1, 1)

    distaff = Distaff(schema, datetime.date(2016, 1, 1))
    assert distaff.json() == '2016-01-01'


def test_default():
    schema = {'type': 'date', 'default': None}
    distaff = Distaff(schema, MISSING)
    assert distaff.native() is None

    schema = {'type': 'boolean', 'default': False}
    distaff = Distaff(schema, None)
    assert distaff.native() is None


def test_required():
    schema = {'type': 'boolean', 'required': True}
    distaff = Distaff(schema, None)
    with pytest.raises(ValidationError):
        distaff.native(fail=True)
    assert distaff.errors == ['a value is required']


def test_choices():
    schema = {'type': 'string', 'choices': ['a', 'b']}
    distaff = Distaff(schema, 'c')
    with pytest.raises(ValidationError):
        distaff.native(fail=True)
    assert distaff.errors == ['a value is required']


def test_dict():
    schema = {'type': 'dict', 'items': {'type': {'type': 'string'}}}
    distaff = Distaff(schema, {'type': 'boolean'})
    assert distaff.native() == {'type': 'boolean'}


def test_list():
    schema = {'type': 'list', 'items': [{'type': 'integer'}]}
    distaff = Distaff(schema, [1, '2', '3'])
    assert distaff.native() == [1, 2, 3]
