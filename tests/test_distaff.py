import pytest
import datetime
import collections

from distaff import Distaff, ValidationError, MISSING, dtype

import logging

logger = logging.getLogger(__name__)

Result = collections.namedtuple('Result', ['data', 'errors'])


class DistaffError(Exception):

    def __init__(self, data, errors):
        self.data = data
        self.errors = errors


class DataType:

    def __init__(self, schema, data):
        self.schema = schema
        self.source = data
        self.data = MISSING
        self.errors = {}

    def error(self, message):
        if 'errors' not in self.errors:
            self.errors['errors'] = []
        self.errors['errors'].append(message)


class Dict(DataType):

    def traverse(self, path, kwargs):
        self.data = []
        if 'items' in self.schema:
            for key, schema in self.schema['items'].items():
                self.process(schema, key, self.source.get(key, MISSING))
        else:
            for key, value in self.source.items():
                self.process(dtype('any'), key, value)

    def process(self, schema, key, value):
        result = distaff(schema, value)
        if value is not MISSING:
            self.data[key] = result.data
        if result.errors:
            if 'items' not in self.errors:
                self.errors['items'] = {}
            self.errors['items'][key] = result.errors


def distaff(schema, data, errors=None, types=None):
    DType = types[schema['type']] if isinstance(schema['type'], str) else schema['type']
    dtype = DType(schema, data)
    dtype.traverse()
    return Result(dtype.data, dtype.errors)


def test_distaff():
    assert distaff(dtype('integer'), None).errors == []


def test_distaff_error():
    try:
        distaff(dtype('integer', required=True), None)
    except DistaffError as e:
        assert e.data == []
        assert e.errors == {}


def test_schema_none():
    with pytest.raises(ValidationError) as e:
        Distaff(None)
    assert e.value.errors == {'errors': ['a value is required'], 'count': 1}


def test_schema_empty():
    with pytest.raises(ValidationError) as e:
        Distaff({})
    assert e.value.errors == {}

    assert Distaff(dtype('integer')) == {}


def test_date():
    distaff = Distaff(dtype('date'), '2016-01-01')
    assert distaff.native() == datetime.date(2016, 1, 1)

    distaff = Distaff(dtype('date'), datetime.date(2016, 1, 1))
    assert distaff.json() == '2016-01-01'


def test_default():
    schema = dtype('date', default=None)
    distaff = Distaff(schema, MISSING)
    assert distaff.native() is None

    schema = dtype('boolean', default=False)
    distaff = Distaff(schema, None)
    assert distaff.native() is None


def test_required():
    schema = dtype('boolean', required=True)
    distaff = Distaff(schema, None)
    with pytest.raises(ValidationError):
        distaff.native(fail=True)
    assert distaff.errors == ['a value is required']


def test_choices():
    schema = dtype('string', choices=['a', 'b'])
    distaff = Distaff(schema, 'c')
    with pytest.raises(ValidationError):
        distaff.native(fail=True)
    assert distaff.errors == ['a value is required']


def test_dict():
    schema = dtype('dict', items={'type': type('string')})
    distaff = Distaff(schema, {'type': 'boolean'})
    assert distaff.native() == {'type': 'boolean'}


def test_list():
    schema = dtype('list', items=dtype('integer'))
    distaff = Distaff(schema, [1, '2', '3'])
    assert distaff.native() == [1, 2, 3]
