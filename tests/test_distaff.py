import pytz
import pytest

from databot.dtypes import dtype, ValidationError, Form



def test_default():
    schema = dtype('int', default=42)
    assert schema().data == 42


def test_int_str_to_int():
    assert dtype('1', 'int').data == 1


def test_int_gt():
    assert dtype(2, 'int', gt=1).data == 2
    assert dtype(2, 'int', gt=2).errors == ["Value should be greater than 2, got 2."]
    assert dtype(2, 'int', gt=3).errors == ["Value should be greater than 3, got 2."]


def test_datetime():
    schema = dtype('datetime')
    data = '2017-02-18T11:11:02.754778+00:00'
    assert schema(data).data == datetime.datetime(2017, 2, 18, 11, 11, 2, 754778, tzinfo=pytz.utc)


def test_oneof():
    data = [1, '2']

    schema = dtype('list', items=dtype('oneof', choices=[
        dtypes('str'),
        dtypes('int'),
    ]))
    assert schema(data).data == [1, '2']

    # Same as above, but using or operator.
    schema = dtype('list', items=dtypes('str') | dtypes('int'))
    assert schema(data).data == [1, '2']


def test_dict():
    schema = dtype('dict', items={
        'a': dtype('int'),
        'b': dtype('dict'),
    })

    data = {
        'a': '42',
        'b': {'foo': 'bar'},
    }

    assert schema(data).data == {
        'a': 42,
        'b': {'foo': 'bar'},
    }


def test_list():
    data = ['1', '2', '3', 4]
    assert dtype(data, 'list').data == data

    schema = dtype('list', items=dtype('int'))
    assert schema(data).data == [1, 2, 3, 4]


def test_nested():
    schema = dtype('dict', items={
        'a': dtype('int'),
        'b': dtype('list'),
        'c': dtype('dict', items={
            'c.a': dtype('dict', items={
                'c.a.a': dtype('int', default=3),
            }),
        }),
    })

    assert schema({}).data == {
        'c': {
            'c.a': {
                'c.a.a': 3,
            },
        },
    }


def test_password_check():
    @dtype.checker(level=-1, messages={
        'mismatch': "Passwords don't match.",
    })
    def passwords_match(dtype, value):
        if value['pasword'] != value['passwords_match']:
            dtype.error('mismatch')

    schema = dtype('dict', items={
        'username': dtype('str', gt=3),
        'pasword': dtype('str'),
        'pasword_confirm': dtype('str', check=[passwords_match]),
    })

    assert schema({}).data == {}


def test_converter():
    @dtype.converter('int', str)
    def verbose_numbers(dtype, value):
        if value == 'one':
            return 1

    assert dtype('one', 'int').data == 1
    assert dtype('uno', 'int').errors == ["Don't know how to convert 'uno' to 'int'."]


def test_first_arg_value():
    assert dtype('int')('-').errors == ["Don't know how to convert '-' to 'int'."]
    assert dtype('-', 'int').errors == ["Don't know how to convert '-' to 'int'."]


def test_nested_errors():
    schema = dtype('dict', items={
        'a': dtype('int'),
        'b': dtype('int'),
        'x': dtype('list', gt=5, items=dtype('int')),
    })

    data = {
        'a': '-',
        'b': '-',
        'c': 1,
        'x': [1, 2, 'err'],
    }

    assert schema(data).errors == {
        'errors': ["Unknown item 'c'."],
        'items': {
            'a': ["Don't know how to convert '-' to 'int'."],
            'b': ["Don't know how to convert '-' to 'int'."],
            'x': {
                'errors': ["Expected more than 5 items in the list, got 3."],
                'items': {
                    2: ["Don't know how to convert 'err' to 'int'."],
                }
            }
        }
    }


def test_context():
    db = [3, 4, 8]

    @dtype.checker(
        context=[
            param('db', list, required=True),
        ],
        messages={
            'duplicate': "Value {value!r} already exist in the database.",
        },
    )
    def duplicate(dtype, value):
        if value in dtype.context.db:
            dtype.error('duplicate', value)

    schema = dtype('int', check=[duplicate])
    with schema.context(db=db):
        assert schema(1).data == 1
        assert schema(3).errors == ["Value 3 already exist in the database."]

    context = {'db': db}
    assert schema(1, context=context).data == 1
    assert schema(3, context=context).errors == ["Value 3 already exist in the database."]


def test_results():
    schema = dtype('int')
    result = schema('42')
    assert result.data == 42
    assert result.errors == []
    assert result.json() == '42'
    assert result.json(serialize=False) == 42


def test_results_error():
    schema = dtype('int')
    result = schema('err')
    assert result.data is None
    assert result.errors == ["Don't know how to convert 'err' to 'int'."]
    assert result.json() == 'null'
    assert result.json(serialize=False) == None


def test_serializer():

    @dtype.serializer('json')
    def json(value, serialize):
        if serialize:
            return json.dumps(value)
        else:
            return value

    @dtype.serializer('json', 'date')
    def json_date(value):
        return value.isoformat()

    schema = dtype('dict', items={
        'date': dtype('date'),
        'ints': dtype('list', items=dtype('int')),
    })

    data = {
        'date': datetime.date(2000, 1, 1),
        'ints': [1, '2', 3],
    }

    assert schema(data).json(serialize=False) == {
        'date': '2000-01-01',
        'ints': [1, 2, 3],
    }


def test_parametrized_checker():
    db = {
        'users': [
            'user1',
            'user3',
        ]
    }

    def unique(table):
        @dtype.checker(
            context=[
                param('db', dict, required=True),
            ],
            messages={
                'duplicate': "Value {value!r} already exist in the database.",
            },
        )
        def check(dtype, value):
            if value in dtype.context.db[table]:
                dtype.error('duplicate', value)

    schema = {
        'username': dtype('str', check=[unique('users')]),
        'password': dtype('str'),
    }

    data = {
        'username': 'user3',
        'password': '',
    }

    assert schema(data).errors == {
        'errors': [],
        'items': {
            'username': ["Value 'user3' already exist in the database."],
        }
    }


def test_infer_dict_type():
    document = {'name': 'john doe'}

    schema = dtype({'name': {'type': 'str'}})
    assert schema(document).errors == []

    # Same as above, but using dtype helper.
    schema = dtype({'name': dtype('str')})
    assert schema(document).errors == []
