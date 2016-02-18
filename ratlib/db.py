"""
Database support module.
"""
import functools
import re
import os.path
import urllib.parse

import sqlalchemy as sa
from sqlalchemy import sql, orm, schema
from sqlalchemy.ext.declarative import as_declarative, declared_attr
import alembic.command
import alembic.config


def setup(bot):
    """
    Initial SQLAlchemy setup for this bot session.  Also performs in-place db upgrades.

    :param bot: Sopel bot
    :return: Nothing
    """
    url = bot.config.ratbot.database
    if not url:
        raise ValueError("Database is not configured.")

    # Schema migration/upgrade
    cfg = alembic.config.Config(bot.config.ratbot.alembic or "alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    alembic.command.upgrade(cfg, "head")
    bot.memory['ratbot']['db'] = orm.scoped_session(orm.sessionmaker(sa.create_engine(url)))

    db = get_session(bot)
    status = get_status(db)
    if status is None:
        status = Status(id=1, starsystem_refreshed=None)
        db.add(status)
        db.commit()
    db.close()


def get_session(bot):
    """
    Returns a database session.

    :param bot: Bot to examine
    """
    return bot.memory['ratbot']['db']()


def with_session(fn=None):
    """
    Ensures that a database session is is passed to the wrapped function as a 'db' parameter.

    :param fn: Function to wrap.

    If fn is None, returns a decorator rather than returning the decorating fn.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            db = get_session(args[0])
            try:
                return fn(*args, db=db, **kwargs)
            finally:
                db.close()
        return wrapper
    return decorator(fn) if fn else decorator


@as_declarative(metadata=schema.MetaData())
class Base:
    """
    Base class for tables.
    """
    __abstract__ = True

    # noinspection PyMethodParameters
    @declared_attr
    def __tablename__(cls):
        """
        Generate table names by replacing every occurrence of e.g. "aA" with "a_a".  This effectively converts
        camelCase and TitleCase to underscore_separated.

        Also prefixes all names with 
        """
        return re.sub(r'([^A-Z])([A-Z])', r'\1_\2', cls.__name__).lower()


def _listify(x):
    if not x:
        return []
    if isinstance(x, str):
        x = [x.strip().lower()]
    return list(i.strip().lower() for i in x)


class Fact(Base):
    name = sa.Column(sa.Text, primary_key=True)
    lang = sa.Column(sa.Text, primary_key=True)
    message = sa.Column(sa.Text, nullable=False)
    author = sa.Column(sa.Text, nullable=True)

    def __init__(self, name=None, lang=None, message=None, author=None):
        if name:
            name = name.lower().strip() or None
        if lang:
            lang = lang.lower().strip() or None
        # noinspection PyArgumentList
        super().__init__(name=name, lang=lang, message=message, author=author)

    @classmethod
    def query(cls, db, name=None, lang=None, order_by=True):
        name = _listify(name)
        lang = _listify(lang)

        query = db.query(cls)
        if len(name) == 1:
            query = query.filter(cls.name == name[0])
        elif len(name) > 1:
            query = query.filter(cls.name.in_(name))
        if len(lang) == 1:
            query = query.filter(cls.lang == lang[0])
        elif len(lang) > 1:
            query = query.filter(cls.lang.in_(lang))

        # Handle ordering
        if order_by:
            if order_by is True:
                if not lang:
                    query = query.order_by(cls.lang)
                elif len(lang) > 1:
                    query = query.order_by(
                        sql.case(
                            value=cls.lang,
                            whens=list((item, ix) for ix, item in enumerate(lang))
                        )
                    )
                if len(name) != 1:
                    query = query.order_by(cls.name)
            else:
                # noinspection PyArgumentList
                query = query.order_by(*order_by)
        return query

    @classmethod
    def find(cls, db, name=None, lang=None, order_by=True):
        return cls.query(db, name, lang, order_by).first()

    @classmethod
    def findall(cls, db, name=None, lang=None, order_by=True):
        yield from cls.query(db, name, lang, order_by)

    @classmethod
    def unique_query(cls, db, name=None, lang=None, field=None, order_by=True):
        if order_by:
            order_by = [field]
        return (
            cls.query(db, name, lang, order_by)
            .with_entities(field)
            .distinct()
        )

    @classmethod
    def unique_names(cls, db, name=None, lang=None, order_by=True):
        for item in cls.unique_query(db, name, lang, cls.name, order_by):
            yield item[0]

    @classmethod
    def unique_langs(cls, db, name=None, lang=None, order_by=True):
        for item in cls.unique_query(db, name, lang, cls.lang, order_by):
            yield item[0]


class Status(Base):
    id = sa.Column(sa.Integer, primary_key=True)
    starsystem_refreshed = sa.Column(sa.DateTime(timezone=True), nullable=True)  # Time of last refresh


class StarsystemPrefix(Base):
    id = sa.Column(sa.Integer, primary_key=True)
    first_word = sa.Column(sa.Text, nullable=False)
    word_ct = sa.Column(sa.Integer, nullable=False)
    const_words = sa.Column(sa.Text, nullable=True)
    ratio = sa.Column('ratio', sa.Float())
    cume_ratio = sa.Column('cume_ratio', sa.Float())
StarsystemPrefix.__table__.append_constraint(schema.Index(
    'starsystem_prefix__unique_words', 'first_word', 'word_ct', unique=True
))


class Starsystem(Base):
    id = sa.Column(sa.Integer, primary_key=True)
    name_lower = sa.Column(sa.Text, nullable=False)
    name = sa.Column(sa.Text, nullable=False)
    word_ct = sa.Column(sa.Integer, nullable=False)
    x = sa.Column(sa.Float, nullable=True)
    y = sa.Column(sa.Float, nullable=True)
    z = sa.Column(sa.Float, nullable=True)
    prefix_id = sa.Column(
        sa.Integer,
        sa.ForeignKey(StarsystemPrefix.id, onupdate='cascade', ondelete='set null'), nullable=True
    )
    prefix = orm.relationship(StarsystemPrefix, backref=orm.backref('systems', lazy=True), lazy=True)
Starsystem.__table__.append_constraint(schema.Index('starsystem__prefix_id', 'prefix_id'))
Starsystem.__table__.append_constraint(schema.Index('starsystem__name_lower', 'name_lower'))


def get_status(db):
    return db.query(Status).get(1)
