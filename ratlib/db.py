"""
Defines database structures and setup
"""

import functools
import re

import sqlalchemy as sa
from sqlalchemy import sql, orm
from sqlalchemy.ext.declarative import as_declarative, declared_attr

import alembic.command
import alembic.config


def fix_uri(uri):
    """
    Sopel gives us SQLite URIs with two trailing slashes, but SA wants three.

    This works around the issue.

    :param uri: Incoming URI
    :return: Corrected URI.
    """
    if uri.startswith('sqlite://') and not uri.startswith('sqlite:///'):
        return uri.replace('sqlite://', 'sqlite:///', 1)
    return uri


def setup(bot):
    """
    Initial SQLAlchemy setup for this bot session.  Also performs in-place db upgrade.

    :param bot: Sopel bot
    :return: Nothing
    """
    uri = fix_uri(bot.db.get_uri())
    cfg = alembic.config.Config(bot.config.ratbot.alembic or "alembic.ini")
    cfg.set_main_option("url", uri)
    alembic.command.upgrade(cfg, "head")

    engine = sa.create_engine(fix_uri(bot.db.get_uri()), echo=getattr(bot.config.ratbot, 'debug_sql', False))

    @sa.event.listens_for(engine, "connect")
    def do_connect(dbapi_connection, connection_record):
        # disable pysqlite's emitting of the BEGIN statement entirely.
        # also stops it from emitting COMMIT before any DDL.
        dbapi_connection.isolation_level = None

    @sa.event.listens_for(engine, "begin")
    def do_begin(conn):
        # emit our own BEGIN
        conn.execute("BEGIN")

    db = orm.scoped_session(orm.sessionmaker(bind=engine))
    return db


@as_declarative()
class Base:
    """
    Base class for tables.
    """
    @declared_attr
    def __tablename__(cls):
        """
        Generate table names by replacing every occurrence of e.g. "aA" with "a_a".  This effectively converts
        camelCase and TitleCase to underscore_separated.

        Also prefixes all names with ratbot_
        """
        return "ratbot_" + re.sub(r'([^A-Z])([A-Z])', r'\1_\2', cls.__name__).lower()


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


def with_db(fn):
    """
    Ensures an instance to the database is passed to the wrapped function as a 'db' parameter.

    Requires the first parameter of the function to be a bot instance.

    Handles cleanup/etc on its own.

    :param fn: Function to wrap
    :return: Wrapped database
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        bot = args[0]
        db = bot.memory['ratbot']['sqla']
        try:
            return fn(*args, db=db, **kwargs)
        finally:
            db.rollback()
    return wrapper
