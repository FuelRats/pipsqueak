"""
props.py - Object change tracking and history control.
Copyright 2016, Daniel "dewiniaid" Grace - https://github.com/dewiniaid

Licensed under the Eiffel Forum License 2.
"""

import datetime
import iso8601
import itertools
import functools
import collections


__all__ = [
    'TrackedProperty', 'TrackedMetaclass', 'TrackedBase', 'TypeCoercedProperty', 'DateTimeProperty',
    'InstrumentedList', 'InstrumentedSet', 'InstrumentedDict',
    'SetProperty', 'ListProperty', 'DictProperty', 'EventEmitter', 'InstrumentedProperty'
]

class TrackedProperty:
    """
    Tracks attribute changes on an object.
    """
    def __init__(self, name=None, default=None, remote_name=None, readonly=False):
        """
        Creates a new TrackedProperty.

        :param name: Property name.  This may be `None`.
        :param default: Property default value.
        :param remote_name: Property remote name.  Defaults to the same as property name.
        :param readonly: If set, property is read-only.  (This only affects writing to JSON output)
        """
        self.name = name
        self.default = default
        self.remote_name = remote_name
        self.readonly = readonly

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
            instance._changed.add(self)

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
        if self.readonly:
            return
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
        instance._data[self.name] = self.load(json.get(self.remote_name))
        instance._changed.discard(self)

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
    def __init__(self, name=None, default=None, remote_name=None, coerce=None, coerce_dump=None):
        super().__init__(name, default, remote_name)
        self.coerce = coerce
        self.coerce_dump = coerce_dump

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

    def dump(self, instance):
        result = super().dump(instance)
        if result is None or self.coerce_dump is None:
            return result
        return self.coerce_dump(result)


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

    def commit(self):
        for prop in self._changed:
            if isinstance(prop, InstrumentedProperty):
                prop.commit(self)
        self._changed = set()


def make_wrapper(class_, attr, notify, *notify_args, **notify_kw):
    method = getattr(class_, attr)

    @functools.wraps(method)
    def fn(self, *a, **kw):
        rv = method(self, *a, **kw)
        notify(self, attr, *notify_args, **notify_kw)
        return rv
    setattr(class_, attr, fn)


class EventEmitter:
    """
    Quick and dirty event system.

    You can listen to events an EventEmitter emits using the add_listener and remove_listener functions.

    The following events are currently implemented by most subclasses:

    COMMITTED: The object state was committed to the external source.  In other words, it is no longer considered to
    be modified -- all pending change history is discarded.

    MERGED: External data was (possibly) applied to the object, merging in changes if feasible to do so.  As part of
    the merge, all pending change history is discarded.

    CHANGED: Local representation of the object was changed in some way.  Excludes updates from MERGED/COMMITTED.

    ALL_EVENTS: Triggered after any event occurs.

    Functions listening to ALL_EVENTS are called as function(event, obj)

    Functions listening to a specific event are called as function(obj)
    """
    ALL_EVENTS = object()
    CHANGED = object()
    COMMITTED = object()
    MERGED = object()
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._listeners = collections.defaultdict(set)

    def add_listener(self, event, listener):
        self._listeners[event].add(listener)

    def remove_listener(self, event, listener):
        self._listeners[event].discard(listener)

    def emit(self, event):
        for listener in self._listeners[event]:
            listener(self)
        for listener in self._listeners[self.ALL_EVENTS]:
            listener(event, self)

    @staticmethod
    def emits(event):
        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(self, *args, **kwargs):
                result = fn(self, *args, **kwargs)
                self.emit(event)
                return result
            return wrapper
        return decorator


class InstrumentedList(EventEmitter, list):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.appends = []
        self.replace = False

    def commit(self, _event=EventEmitter.COMMITTED):
        self.appends = []
        self.replace = False
        self.emit(_event)

    def merge(self, other):
        if self.replace:
            return self
        super().clear()
        super().extend(other)
        super().extend(self.appends)
        self.commit(EventEmitter.MERGED)
        return self

    @EventEmitter.emits(EventEmitter.CHANGED)
    def _notify(self, attr):
        self.replace = True
        self.emit(EventEmitter.CHANGED)

    @EventEmitter.emits(EventEmitter.CHANGED)
    def append(self, item):
        if not self.replace:
            self.appends.append(item)
        return super().append(item)

    @EventEmitter.emits(EventEmitter.CHANGED)
    def extend(self, items):
        if not self.replace:
            logged, items = itertools.tee(items, 2)
            self.appends.extend(logged)
        return super().extend(items)
for attr in "insert remove pop clear index sort reverse __delitem__ __setitem__ __iadd__ __imul__".split(" "):
    make_wrapper(InstrumentedList, attr, InstrumentedList._notify)


class InstrumentedSet(EventEmitter, set):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.changes = {}
        self.replace = False

    def commit(self, _event=EventEmitter.COMMITTED):
        self.changes = {}
        self.replace = False

        self.emit(_event)

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
        super().update(k for k, v in self.changes.items() if v)
        self.commit(EventEmitter.MERGED)
        return self

    @EventEmitter.emits(EventEmitter.CHANGED)
    def _notify(self, attr):
        self.replace = True

    @EventEmitter.emits(EventEmitter.CHANGED)
    def add(self, item):
        result = super().add(self, item)
        if not self.replace:
            self.changes[item] = True
        return result

    @EventEmitter.emits(EventEmitter.CHANGED)
    def update(self, *iterables):
        items = itertools.chain(*iterables)
        if not self.replace:
            copy, items = itertools.tee(items, 2)
            try:
                self.changes.update((item, True) for item in copy)
            except:
                print('I have no clue why this error happens, but TypeError: \'NoneType\' object is not iterable')
        return super().update(items)

    def __ior__(self, other):
        self.update(other)
        return self

    @EventEmitter.emits(EventEmitter.CHANGED)
    def __isub__(self, other):
        if not self.replace:
            copy, other = itertools.tee(other, 2)
            self.changes.update((item, False) for item in copy)
        return super().__isub__(other)

    @EventEmitter.emits(EventEmitter.CHANGED)
    def discard(self, item):
        result = super().discard(self, item)
        if not self.replace:
            self.changes[item] = False
        return result

    @EventEmitter.emits(EventEmitter.CHANGED)
    def remove(self, item):
        result = super().remove(self, item)
        if not self.replace:
            self.changes[item] = False
        return result

for attr in "__iand__ __ixor__ clear difference_update intersection_update symmetric_difference_update pop".split(" "):
    make_wrapper(InstrumentedSet, attr, InstrumentedSet._notify)


class InstrumentedDict(EventEmitter, dict):
    _DELETED = object()
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.changes = {}
        self.replace = False

    def commit(self, _event=EventEmitter.COMMITTED):
        self.changes = {}
        self.replace = False
        self.emit(_event)

    @EventEmitter.emits(EventEmitter.CHANGED)
    def merge(self, other):
        if self.replace:
            return self
        super().clear()
        super().update(other)
        for k, v in self.changes.items():
            if v is self._DELETED:
                try:
                    super().__delitem__(k)
                except KeyError:
                    pass
            else:
                super().__setitem__(k, v)
        self.emit(EventEmitter.MERGED)
        return self

    @EventEmitter.emits(EventEmitter.CHANGED)
    def _notify(self, attr):
        self.replace = True

    @EventEmitter.emits(EventEmitter.CHANGED)
    def add(self, item):
        result = super().add(self, item)
        if not self.replace:
            self.changes[item] = True
        return result

    @EventEmitter.emits(EventEmitter.CHANGED)
    def update(self, *e, **f):
        if self.replace:
            return super().update(*e, **f)

        changeset = dict(*e)
        changeset.update(**f)
        self.changes.update(changeset)
        return super().update(changeset)

    @EventEmitter.emits(EventEmitter.CHANGED)
    def __delitem__(self, key):
        super().__delitem__(key)
        if not self.replace:
            self.changes[key] = self._DELETED

    @EventEmitter.emits(EventEmitter.CHANGED)
    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if not self.replace:
            self.changes[key] = value
for attr in "clear fromkeys pop popitem setdefault".split(" "):
    make_wrapper(InstrumentedDict, attr, InstrumentedDict._notify)


class InstrumentedProperty(TypeCoercedProperty):
    def set(self, instance, value, dirty=True):
        def listener(obj):
            if obj is getattr(instance, self.name):
                instance._changed.add(self)
            else:
                instance.remove_listener(EventEmitter.CHANGED, listener)
        super().set(instance, value, dirty)
        value = super().get(instance)
        if value is not None:
            value.add_listener(EventEmitter.CHANGED, listener)

    def merge(self, instance, incoming, dirty=False):
        value = self.get(instance)
        if value:
            value.merge(incoming)
            return
        self.set(instance, incoming, dirty)
        if not dirty:
            instance._changed.discard(self)
        return

    def read(self, instance, json, merge=False):
        if not merge:
            return super().read(instance, json)
        value = self.load(json[self.remote_name])
        return self.merge(instance, value)

    def commit(self, instance):
        value = self.get(instance)
        value.commit()


SetProperty = functools.partial(InstrumentedProperty, coerce=InstrumentedSet, coerce_dump=list)
ListProperty = functools.partial(InstrumentedProperty, coerce=InstrumentedList, coerce_dump=list)
DictProperty = functools.partial(InstrumentedProperty, coerce=InstrumentedDict, coerce_dump=dict)
