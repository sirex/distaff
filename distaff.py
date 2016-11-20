import datetime
import itertools


class Missing:

    def __repr__(self):
        return 'MISSING'

MISSING = Missing()


class ValidationError(Exception):
    pass


class Field:

    def __init__(self, distaff, schema):
        self.distaff = distaff
        self.schema = schema

    def isna(self, value):
        return value is None

    def native(self, value):
        if isinstance(value, self.type):
            return value
        else:
            raise ValidationError("can't convert %r into %r" % (type(value), self.type))

    def traverse(self, value, path, kwargs):
        return value

    def validate(self, value):
        if self.isna(value):
            if self.schema.get('required', False):
                raise ValidationError('a value is required')
            else:
                return

        if not isinstance(value, self.type):
            raise ValidationError('got %r, but expected type was %r' % (type(value), self.type))

        if self.schema['choices'] and value not in self.schema['choices']:
            raise ValidationError('%r is not one of %r' % (value, self.schema['choices']))

    def json(self, value):
        return value


class Boolean(Field):
    type = bool

    sschema = {
        'false': {
            'type': 'list',
            'items': [{'type': 'string'}],
            'default': ['false', '0', 'no', 'off'],
            'required': True,
        },
        'true': {
            'type': 'list',
            'items': [{'type': 'string'}],
            'default': ['true', '1', 'yes', 'on'],
            'required': True,
        },
    }

    false = ['false', '0', 'no', 'off']
    true = ['true', '1', 'yes', 'on']

    def native(self, value):
        if isinstance(value, str):
            if value in self.false:
                return False
            elif value in self.true:
                return True
            else:
                raise ValidationError("can't convert %r into %r" % (value, self.type))

        return super().native(value)


class Integer(Field):
    type = int

    sschema = {
    }

    def native(self, value):
        if isinstance(value, str):
            return int(value)
        else:
            return super().native(value)


class String(Field):
    type = str

    sschema = {
        'empty': {'type': 'boolean', 'default': True, 'required': True},
    }

    def native(self, value):
        if isinstance(value, int):
            return str(value)
        elif isinstance(value, bool):
            return 'true' if value else 'false'
        else:
            return super().native(value)


class Date(Field):
    sschema = {
        'format': {'type': 'list', 'items': [{'type': 'string'}], 'default': ['%Y-%m-%d']},
    }

    type = datetime.date
    format = [
        '%Y-%m-%d',
    ]

    def native(self, value):
        if isinstance(value, str):
            for format in self.schema.get('format', self.format):
                try:
                    return datetime.datetime.strptime(value, format).date()
                except ValueError:
                    pass

        return super().native(value)

    def json(self, value):
        return value.strftime(self.format[0])


class List(Field):
    type = list

    sschema = {
        'items': {'type': 'list', 'items': [{'type': 'dict'}], 'required': False},
    }

    def traverse(self, value, path, kwargs):
        result = []
        for key, (schema, val) in enumerate(zip(itertools.cycle(self.schema['items']), value)):
            result.append(self.distaff.process(schema=schema, data=val, path=path + (key,), **kwargs))
        return result


class Dict(Field):
    type = dict

    sschema = {
        'items': {'type': 'dict', 'required': False},
    }

    def traverse(self, value, path, kwargs):
        result = {}
        if 'items' in self.schema:
            for key, val in self.schema['items'].items():
                result[key] = self.distaff.process(
                    schema=val,
                    data=value.get(key, MISSING),
                    path=path + (key,),
                    **kwargs,
                )
        else:
            for key, val in value.items():
                result[key] = self.distaff.process(
                    schema={'type': 'any'},
                    data=val,
                    path=path + (key,),
                    **kwargs,
                )
        return result


class Any(Field):

    sschema = {
    }

    def isna(self, value):
        return value is MISSING

    def native(self, value):
        return value

    def validate(self, value):
        if self.isna(value):
            if self.schema.get('required', False):
                raise ValidationError('a value is required')
            else:
                return


class Distaff:
    sschema = {
        'type': 'dict',
        'items': {
            'type': {'type': 'string', 'required': True},
            'required': {'type': 'boolean', 'default': False},
            'default': {'type': 'any'},
            'choices': {'type': 'list', 'items': [{'type': 'any'}], 'default': None},
        }
    }

    types = {
        'boolean': Boolean,
        'integer': Integer,
        'string': String,
        'date': Date,
        'list': List,
        'dict': Dict,
        'any': Any,
    }

    def __init__(self, schema, data, **context):
        self.schema = schema
        self.data = data
        self.context = context
        self.errors = []

    def __call__(self, data):
        self.fillna()
        self.cast()
        self.check()

    def native(self, *, cast=True, validate=True, fail=False, validate_schema=True):
        return self.process(self.schema, self.data, 'native', cast, validate, fail, validate_schema)

    def json(self, *, cast=False, validate=False, fail=True, validate_schema=True):
        return self.process(self.schema, self.data, 'json', cast, validate, fail, validate_schema)

    def process(self, schema, data, output, cast, validate, fail, validate_schema=True, path=()):
        DataType = self.types[schema['type']]
        if validate_schema:
            sschema = dict(
                self.sschema,
                items=dict(
                    dict(
                        self.sschema['items'],
                        type=dict(self.sschema['items']['type'], choices=list(self.types.keys())),
                    ),
                    **DataType.sschema,
                ),
            )
            schema = Distaff(sschema, schema).native(validate_schema=False)
        dtype = DataType(self, schema)

        if 'default' in schema and data is MISSING:
            data = schema['default']

        if 'fillna' in schema and dtype.isna(data):
            data = schema['fillna']

        try:
            if cast and not dtype.isna(data):
                data = dtype.native(data)

            if not dtype.isna(data):
                data = dtype.traverse(data, path, {
                    'output': output,
                    'cast': cast,
                    'validate': validate,
                    'fail': fail,
                    'validate_schema': validate_schema,
                })

            if validate:
                dtype.validate(data)
        except ValidationError as e:
            self.errors.append(str(e))
            if fail:
                raise

        if path:
            return data
        elif output == 'native':
            return data
        elif output == 'json':
            return dtype.json(data)
