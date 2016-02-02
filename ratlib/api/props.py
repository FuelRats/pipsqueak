"""
props.py - Object change tracking and history control.
Copyright 2016, Daniel "dewiniaid" Grace - https://github.com/dewiniaid

Licensed under the Eiffel Forum License 2.
"""

import datetime
import iso8601
import itertools
import functools


__all__ = [
    'TrackedProperty', 'TrackedMetaclass', 'TrackedBase', 'TypeCoercedProperty', 'DateTimeProperty',
    'InstrumentedList', 'InstrumentedSet', 'InstrumentedDict',
    'SetProperty', 'ListProperty', 'DictProperty',
]

class TrackedProperty:
    """
    Tracks attribute changes on an object.
    """
    def __init__(self, name=None, default=None, remote_name=None):
        """
        Creates a new TrackedProperty.

        :param name: Property name.  This may be `None`.
        :param default: Property default value.
        :param remote_name: Property remote name.  Defaults to the same as property name.
        """
        self.name = name
        self.default = default
        self.remote_name = remote_name

    def setup(self):
        """
        Performs setup tasks.  Intended to be called by metaclasses.
        """
        if self.remote_name is None:
            self.remote_name = self.name

    def get(self, instance):
        """
        Retrieves property value.
        """
        return instance._data[self.name]

    def __get__(self, instance, owner):
        return self.get(instance)

    def set(self, instance, value, dirty=True):
        """
        Sets property value.

        :param instance: Instance being modified
        :param value: New value
        :param dirty: If True, adds this to the list of changed properties on the instance.
        """
        instance._data[self.name] = value
        if dirty:
            instance._changed.add(self.name)

    def __set__(self, instance, value):
        self.set(instance, value, dirty=True)

    def dump(self, instance):
        """
        Returns the JSON representation of this property, when possible.

        Whether this is actually used by write() is implementation-dependant.
        """
        return self.get(instance)

    def write(self, instance, json):
        """
        Update json with results of exporting data
        """
        json[self.remote_name] = self.dump(instance)

    def load(self, value):
        """
        Takes a property from JSON and converts it to our native format, when possible.

        Whether this is actually used by read() is implementation-dependant.
        """
        return value

    def read(self, instance, json):
        """
        Read json data and update the instance.
        """
        instance._data[self.name] = self.load(json[self.remote_name])

    def has(self, instance, json):
        """
        Returns True if this property is in the json data.
        """
        return self.remote_name in json


class DateTimeProperty(TrackedProperty):
    UTC = datetime.timezone.utc

    def load(self, value):
        if value is None:
            return None
        if isinstance(value, str):
            return iso8601.parse_date(value, self.UTC)
        if isinstance(value, (int, float)):
            # We'll assume floats are proper timestamps.  But ints...
            if isinstance(value, int):
                # Current timestamps are 10 digits long.  It will be at least 200 years before this changes...
                # so I think this is reasonably future-proof given it's a patch against an API bug.
                if len(str(value)) > 10:
                    value = value / 1000
            return datetime.datetime.fromtimestamp(value, tz=self.UTC)
        raise ValueError("Invalid datetime format")

    def dump(self, value):
        raise NotImplementedError('Writing of datetime properties is not currently supported')


class TypeCoercedProperty(TrackedProperty):
    def __init__(self, name=None, default=None, remote_name=None, coerce=None):
        super().__init__(name, default, remote_name)
        self.coerce = coerce

    def set(self, instance, value, dirty=True):
        if value is not None:
            if not isinstance(value, self.coerce):
                value = self.coerce(value)
        super().set(instance, value, dirty)

    def load(self, value):
        if value is not None:
            if not isinstance(value, self.coerce):
                value = self.coerce(value)
        return value


class TrackedMetaclass(type):
    """
    When an object is created with this metaclass, any TrackedProperties are automatically configured.
    """
    def __new__(cls, name, bases, namespace, **kwds):
        if '_props' not in namespace:
            namespace['_props'] = set()
        for name, value in namespace.items():
            if isinstance(value, TrackedProperty):
                if value.name is None:
                    value.name = name
                value.setup()
                namespace['_props'].add(value)
        return type.__new__(cls, name, bases, namespace, **kwds)


class TrackedBase(metaclass=TrackedMetaclass):
    """
    Base class for classes with TrackedProperties
    """
    def __init__(self, **kwargs):
        self._data = {}
        for prop in self._props:
            value = kwargs[prop.name] if prop.name in kwargs else prop.default
            if callable(value):
                value = value()
            prop.set(self, value, dirty=False)
        self._changed = set()


def make_wrapper(class_, attr, notify, *notify_args, **notify_kw):
    method = getattr(class_, attr)

    @functools.wraps(method)
    def fn(self, *a, **kw):
        rv = method(self, *a, **kw)
        notify(self, attr, *notify_args, **notify_kw)
        return rv
    setattr(class_, attr, fn)


class InstrumentedList(list):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.appends = []
        self.replace = False

    def commit(self):
        self.appends = []
        self.replace = False

    def merge(self, other):
        if self.replace:
            return self
        super().clear()
        super().extend(other)
        super().extend(self.appends)
        self.commit()
        return self

    def _notify(self, attr):
        self.replace = True

    def append(self, item):
        if not self.replace:
            self.appends.append(item)
        return super().append(item)

    def extend(self, items):
        logged = None
        if not self.replace:
            logged, items = itertools.tee(items, n=2)
            self.appends.extend(logged)
        return super().extend(items)

for attr in "insert remove pop clear index sort reverse __delitem__ __setitem__ __iadd__ __imul__".split(" "):
    make_wrapper(InstrumentedList, attr, InstrumentedList._notify)


class InstrumentedSet(set):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.changes = {}
        self.replace = False

    def commit(self):
        self.changes = {}
        self.replace = False

    def merge(self, other):
        if self.replace:
            return self
        super().clear()
        super().update(other)
        for item, add in self.changes.items():
            if add:
                super().add(item)
            else:
                super().discard(item)
        super().extend(self.appends)
        self.commit()
        return self

    def _notify(self, attr):
        self.replace = True

    def add(self, item):
        result = super().add(self, item)
        if not self.replace:
            self.changes[item] = True
        return result

    def update(self, *iterables):
        logged = None
        items = itertools.chain(*iterables)
        if not self.replace:
            logged, items = itertools.tee(items, n=2)
            self.changes.update((item, True) for item in logged)
        return super().extend(items)

    def discard(self, item):
        result = super().discard(self, item)
        if not self.replace:
            self.changes[item] = False
        return result

    def remove(self, item):
        result = super().remove(self, item)
        if not self.replace:
            self.changes[item] = False
        return result
for attr in "__iand__ __ior__ __isub__ __ixor__ clear difference_update intersection_update symmetric_difference_update pop".split(" "):
    make_wrapper(InstrumentedSet, attr, InstrumentedSet._notify)


class InstrumentedDict(dict):
    _DELETED = object()
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.changes = {}
        self.replace = False

    def commit(self):
        self.changes = {}
        self.replace = False

    def merge(self, other):
        if self.replace:
            return self
        super().clear()
        super().update(other)
        for k, v in self.changes.items():
            if v is self._DELETED:
                try:
                    del self[k]
                except KeyError:
                    pass
            else:
                self[k] = v
        self.commit()
        return self

    def _notify(self, attr):
        self.replace = True

    def add(self, item):
        result = super().add(self, item)
        if not self.replace:
            self.changes[item] = True
        return result

    def update(self, *e, **f):
        logged = None
        if self.replace:
            super().update(*e, **f)

        changeset = dict(*e)
        changeset.update(**f)
        self.changes.update(changeset)
        return super().update(changeset)

    def __delitem__(self, key):
        super().__delitem__(key)
        if not self.replace:
            self.changes = self._DELETED

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if not self.replace:
            self.changes = value

for attr in "clear fromkeys pop popitem setdefault".split(" "):
    make_wrapper(InstrumentedDict, attr, InstrumentedDict._notify)


SetProperty = functools.partial(TypeCoercedProperty, coerce=InstrumentedSet)
ListProperty = functools.partial(TypeCoercedProperty, coerce=InstrumentedList)
DictProperty = functools.partial(TypeCoercedProperty, coerce=InstrumentedDict)


