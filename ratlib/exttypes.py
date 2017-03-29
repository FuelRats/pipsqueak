"""
Support for certain extended SQL types.
"""
from sqlalchemy import types, sql
import re
import operator


class Point(tuple):
    __slots__ = ()

    def __new__(cls, x, z=None):
        if z is None:
            x, z = x
            return Point(x, z)
        if x is None or z is None:
            raise ValueError("Values of a Point cannot be None")
        return super().__new__(cls, (x, z))

    x = property(fget=operator.itemgetter(0))
    z = property(fget=operator.itemgetter(1))

    def __repr__(self):
        return self.__class__.__name__ + super().__repr__()


class SQLPoint(types.UserDefinedType):
    _re_pattern = re.compile(r'\s*\(\s*(.*)\s*,\s*(.*)\s*\)\s*')

    def __init__(self, number_type=float):
        super().__init__()
        self.number_type = float

    def get_col_spec(self):
        return "POINT"


    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return value
            if None in value:
                raise ValueError('Value cannot contain None values')
            return ",".join(str(x) for x in value)
        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return value
            return Point(self.number_type(x) for x in self._re_pattern.match(value).groups())
        return process

    def bind_expression(self, bindvalue):
        if bindvalue.value is None:
            return None
        return sql.func.point(bindvalue, type_=self)
