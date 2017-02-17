import copy
import collections


class Missing:

    def __repr__(self):
        return 'MISSING'

    def __copy__(self):
        return MISSING

    def __deepcopy__(self, memo):
        return MISSING

MISSING = Missing()


class ValidationError(Exception):
    pass


class Result:

    def __init__(self):
        self.data = None
        self.errors = collections.defaultdict(list)


class Schema:

    def __init__(self, types, name, params):
        self.types = types
        self.dtype =types[name](params)

    def __call__(self, value, cast=True, check=True, fail=False):
        return self.process(value, cast=cast, check=check, fail=fail)

    def to_native(self, value=MISSING):
        return self.process(value, cast=True, check=True)

    def process(self, value=MISSING, *, cast=False, check=False, fail=False, result=None, path=()):
        if result is None:
            result_is_provided = False
            result = Result()
        else:
            result_is_provided = True

        if value is MISSING:
            value = self.dtype.params.default

        if self.dtype.isna(value):
            value = self.dtype.fillna(value)

        na = self.dtype.isna(value)

        try:
            if cast and not na:
                value = self.dtype.cast(value)

            if check:
                self.dtype.check(value)

            if not na:
                value = self.dtype.traverse(value, path, result=result, cast=cast, check=check)
        except ValidationError as e:
            if result_is_provided:
                result.errors[path].append(str(e))
            else:
                raise

        return value


class Registry:

    def __init__(self):
        self.types = {}

    def __call__(self, name, **params):
        return Schema(self.types, name, params)

    def add_type(self, name, DataType):
        self.types[name] = DataType


Param = collections.namedtuple('Param', ['name', 'types', 'default', 'required', 'disable'])


def param(name, types=None, default=MISSING, required=False, disable=False):
    return Param(name, types, default, required, disable)


def get_params(schema, kwargs):
    schema = {
        p.name: p
        for params in reversed(schema)
        for p in params if not p.disable
    }

    for key, value in kwargs.items():
        if key not in schema:
            raise ValidationError("Unknown parameter %r." % key)

    params = {}
    for name, param in schema.items():
        if name in kwargs:
            value = kwargs[name]
            if param.types is not None and not isinstance(value, param.types):
                raise ValidationError("Wrong parameter %r types, expected %r, got %r." % (
                    name, ' or '.join(str(x) for x in types), type(value),
                ))
        elif param.required:
            raise ValidationError("Parameter %r is required." % name)
        else:
            value = copy.deepcopy(param.default)
        params[name] = value

    names, values = zip(*params.items())
    return collections.namedtuple('Params', names)(*values)


class DataType:

    params = [
        param('default'),
        param('fillna'),
        param('required', bool, default=False),
        param('null', bool, default=False),
        param('check', list, default=[]),
    ]

    messages = {
        'cast_error': "can't cast {value_type} into {native_type}",
    }

    def __init__(self, params):
        schema = [x.params for x in self.__class__.__mro__ if hasattr(x, 'params')]
        self.params = get_params(schema, params)

    def error(self, name, value=None, **kwargs):
        raise ValidationError(self.messages[name].format(value=value, params=self.params, **kwargs))

    def isna(self, value):
        return value is None or value is MISSING

    def fillna(self, value):
        if self.params.fillna is not MISSING:
            value = self.params.fillna
        return value

    def cast(self, value):
        if isinstance(value, self.native_type):
            return value
        else:
            self.error('cast_error', value_type=type(value), native_type=self.native_type)

    def check(self, value):
        pass

    def traverse(self, value, path, **kwargs):
        return value


@dtype.checker()
def check_length(dtype, value):
    if dtype.isna(value):
        return

    if dtype.params.gt is not None and dtype.params.gt <= len(value):
        self.error('gt', length=len(value))


class Str(DataType):
    native_type = str

    params = [
        param('null', bool, default=False),
        param('gt', int, default=0),
        param('gte', int, default=None),
        param('lt', int, default=None),
        param('lte', int, default=None),
    ]

    checks = [
        ('length', check_length),
    ]

    messages = {
        'gt': "string should be longer than {params.gt}, got {length}",
    }

    def cast(self, value):
        return str(value)


@dtype.checker()
def check_range(dtype, value):
    if dtype.isna(value):
        return

    if dtype.params.gt is not None and dtype.params.gt <= value:
        dtype.error('gt', value)


class Int(DataType):
    native_type = int

    params = [
        param('null', bool, default=False),
        param('gt', int, default=0),
        param('gte', int, default=None),
        param('lt', int, default=None),
        param('lte', int, default=None),
    ]

    checks = [
        ('range', check_range),
    ]

    messages = {
        'gt': "number should be greater than {params.gt}, got {value!r}",
    }

    def cast(self, value):
        if isinstance(value, str):
            return int(value)
        else:
            return super().cast(value)


class Dict(DataType):
    native_type = dict

    params = [
        param('default', dict, default={}),
        param('keys', Schema),
        param('values', Schema),
        param('items', dict, default={}),
    ]

    def traverse(self, value, path, **kwargs):
        result = {k: v for k, v in value.items()}
        if self.params.items:
            for key, val in self.params.items.items():
                v = val.process(value.get(key, MISSING), path=path + (key,), **kwargs)
                if v is not MISSING:
                    result[key] = v
        return result


class List(DataType):
    native_type = list

    params = [
        param('default', list),
        param('items', Schema, default=None),
    ]

    def traverse(self, value, path, **kwargs):
        if self.params.items is None:
            return [x for x in value]

        result = []
        for key, val in enumerate(value):
            result.append(self.params.items.process(val, path=path + (key,), **kwargs))
        return result


dtype = Registry()
dtype.add_type('int', Int)
dtype.add_type('dict', Dict)
dtype.add_type('list', List)
