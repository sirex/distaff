import copy
import datetime
import itertools
import logging


logger = logging.getLogger(__name__)


def dtype(type, **kwargs):
    return dict(type=type, **kwargs)


class Missing:

    def __repr__(self):
        return 'MISSING'

MISSING = Missing()


class ValidationError(Exception):

    def __init__(self, message='', errors=None):
        self.errors = errors
        super().__init__(message)


class Field:

    def __init__(self, distaff, schema, errors):
        self.distaff = distaff
        self.schema = schema
        self.errors = errors

    def isna(self, value):
        return value is None or value is MISSING

    def native(self, value):
        if isinstance(value, self.native_type):
            return value
        else:
            raise ValidationError("can't convert %r into %r" % (type(value), self.native_type))

    def traverse(self, value, path, kwargs):
        return value

    def validate(self, value):
        if self.isna(value):
            if self.schema['required']:
                raise ValidationError('a value is required')
            else:
                return

        if not isinstance(value, self.native_type):
            raise ValidationError('got %r, but expected type was %r' % (type(value), self.native_type))

        if self.schema['choices'] and value not in self.schema['choices']:
            raise ValidationError('%r is not one of %r' % (value, self.schema['choices']))

    def json(self, value):
        return value


class Boolean(Field):
    native_type = bool

    _schema = {
        'false': dtype('list', required=True, items=dtype('string'), default=['false', 'off', 'no', '0']),
        'true': dtype('list', required=True, items=dtype('string'), default=['true', 'on', 'yes', '1']),
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
                raise ValidationError("can't convert %r into %r" % (value, self.native_type))

        return super().native(value)


class Integer(Field):
    native_type = int

    _schema = {
    }

    def native(self, value):
        if isinstance(value, str):
            return int(value)
        else:
            return super().native(value)


class String(Field):
    native_type = str

    _schema = {
        'empty': dtype('boolean', default=True, required=True),
    }

    def native(self, value):
        if isinstance(value, int):
            return str(value)
        elif isinstance(value, bool):
            return 'true' if value else 'false'
        else:
            return super().native(value)


class Date(Field):
    _schema = {
        'format': dtype('list', items=dtype('string'), default=['%Y-%m-%d']),
    }

    native_type = datetime.date
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
    native_type = list

    _schema = {
        'items': dtype('list', items=dtype('dict'), required=False),
    }

    def traverse(self, value, path, kwargs):
        result = []
        for key, (schema, val) in enumerate(zip(itertools.cycle(self.schema['items']), value)):
            logger.debug('    traverse %r', key)
            result.append(self.process(schema=schema, data=val, path=path + (key,), **kwargs))
        return result

    def process(self, **kwargs):
        return self.distaff.process(**kwargs)


class Dict(Field):
    native_type = dict

    _schema = {
        'items': dtype('dict', required=False),
    }

    def traverse(self, value, path, kwargs):
        result = {}
        if 'items' in self.schema:
            for key, val in self.schema['items'].items():
                logger.debug('    traverse %r', key)
                result[key] = self.process(
                    schema=val,
                    data=value.get(key, MISSING),
                    path=path + (key,),
                    **kwargs,
                )
        else:
            for key, val in value.items():
                logger.debug('    traverse %r', key)
                result[key] = self.process(
                    schema=dtype('key'),
                    data=val,
                    path=path + (key,),
                    **kwargs,
                )
        return result

    def process(self, **kwargs):
        return self.distaff.process(**kwargs)


class Any(Field):

    _schema = {
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


class Schema(Dict):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.schema = copy.deepcopy(self.schema)

    def process(self, schema, **kwargs):
        schema.setdefault('choices', None)
        schema.setdefault('required', False)
        return self.distaff.process(schema, **kwargs)


class Distaff:
    _schema = dtype('schema', required=True, choices=None, items={
        'type': dtype('string', required=True),
        'required': dtype('boolean', default=False),
        'choices': dtype('list', items=dtype('any'), default=None),
        'default': dtype('any'),
    })

    types = {
        'schema': Schema,
        'boolean': Boolean,
        'integer': Integer,
        'string': String,
        'date': Date,
        'list': List,
        'dict': Dict,
        'any': Any,
    }

    def __init__(self, schema, data=None, **context):
        self.data = data
        self.context = context
        self.errors = {'errors': [], 'count': 0}
        self.schema = self.process(self._schema, schema, fail=True, errors=self.errors)

    def __call__(self, data):
        self.fillna()
        self.cast()
        self.check()

    def native(self, *, cast=True, validate=True, fail=False, validate_schema=True):
        return self.process(self.schema, self.data, 'native', cast, validate, fail, errors=self.errors)

    def json(self, *, cast=False, validate=False, fail=True, validate_schema=True):
        return self.process(self.schema, self.data, 'json', cast, validate, fail, errors=self.errors)

    def process(self, schema, data, output='native', cast=True, validate=True, fail=False, path=(), errors=None):
        logger.debug(
            'process %r, path=%r, cast=%r, validate=%r, fail=%r',
            schema['type'], path, cast, validate, fail,
        )
        DataType = self.types[schema['type']]
        logger.debug('  found data type: %r', DataType)
        dtype = DataType(self, schema, errors)

        if 'default' in schema and data is MISSING:
            logger.debug('  set default value to %r', schema['default'])
            data = schema['default']

        if 'fillna' in schema and dtype.isna(data):
            logger.debug('  fill NA value with %r', schema['fillna'])
            data = schema['fillna']

        isna = dtype.isna(data)
        logger.debug('  isna=%r', isna)

        try:
            if cast and not isna:
                logger.debug('  convert to native type')
                data = dtype.native(data)

            if validate:
                logger.debug('  validate')
                dtype.validate(data)

            if not isna:
                logger.debug('  traverse')
                data = dtype.traverse(data, path, {
                    'output': output,
                    'cast': cast,
                    'validate': validate,
                    'fail': False,  # let all nested structures complete processing
                })

        except ValidationError as e:
            logger.debug('  error: %s', e, exc_info=e)
            dtype.errors['errors'].append(str(e))
            self.errors['count'] += 1

        if path == () and self.errors['count'] and fail:
            raise ValidationError(errors=self.errors)

        if path:
            return data
        elif output == 'native':
            return data
        elif output == 'json':
            return dtype.json(data)
