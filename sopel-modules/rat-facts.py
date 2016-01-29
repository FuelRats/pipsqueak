#coding: utf8
"""
rat-facts.py - Fact reciting module
Copyright 2015, Dimitri "Tyrope" Molenaars <tyrope@tyrope.nl>
Licensed under the Eiffel Forum License 2.

These modules are built on top of the Sopel system.
http://sopel.chat/
"""

import json
import os
import os.path
import re
import glob
import functools
import threading
from sopel.module import commands, NOLIMIT, HALFOP, OP
from sopel.config.types import StaticSection, ValidatedAttribute
from sopel.tools import SopelMemory, Identifier


class LockableSet(set):
    """Lets us ensure we can access a set without concurrently modifying it."""
    def __init__(self, *args, lock=None):
        if lock is None:
            lock = threading.RLock()
        self.lock = lock
        super().__init__(*args)

    def acquire(self, *a, **kw):
        return self.lock.acquire(*a, **kw)

    def release(self, *a, **kw):
        return self.lock.release(*a, **kw)

    def __enter__(self):
        self.lock.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self.lock.__exit__(exc_type, exc_val, exc_tb)


class RatfactsSection(StaticSection):
    filename = ValidatedAttribute('filename', str, default='')
    table = ValidatedAttribute('table', str, default='ratfacts')


class Fact(object):
    """
    A Rat Fact
    """
    FIELDS = ('name', 'lang', 'message', 'author')  # Database fields

    def __init__(self, name, lang, message, author=None):
        """
        :param name: Name of this fact.  Autoconverted to lowercase.
        :param lang: ISO 639-1 or similar language code (e.g. "en").  Autoconverted to lowercase.
        :param message: Text for this fact.
        :param author: Author of this fact, e.g. creator's nickname.  Optional
        """
        self.name = name.lower().strip()
        self.lang = lang.lower().strip()
        self.message = message
        self.author = author

    def save(self, bot=None, db=None, table=None, using='REPLACE'):
        self._save(self, bot, db, table, using)

    def delete(self, bot=None, db=None, table=None):
        return self._delete(self, bot, db, table)

    @classmethod
    def _getfactsql(cls, name, lang):
        """
        Returns data used in query construction for getfact and getfacts
        :param name: Name to lookup.  May be None to match all facts, or a list of multiple facts.
        :param lang: Language(s) to lookup.  May be None to match all languages
        :return: Tuple of (names, langs, where_clauses, where_params)
        """
        def _listify(x):
            if not x:
                return []
            if isinstance(x, str):
                x = [x]
            return list(i.strip().lower() for i in x)

        def _in(x, field):
            if not x:
                return None
            if len(x) == 1:
                return field + "=?"
            return "{field} IN({values})".format(field=field, values=",".join("?" for _ in range(len(x))))
        name = _listify(name)
        lang = _listify(lang)
        where = []
        clause = _in(name, 'name')
        if clause:
            where.append(clause)
        clause = _in(lang, 'lang')
        if clause:
            where.append(clause)

        return name, lang, where, name + lang

    @classmethod
    def _getdbtable(cls, bot=None, db=None, table=None):
        """
        Many methods expect either a 'bot' object or a combination of db+table.

        This performs validation, and simplifies down to a db and table (or raises a ValueError)
        :param bot: Bot instance to query.
        :param db: Database connection to query.
        :param table: Table to query.
        :return:
        """
        if ((db is None) != (table is None)) or ((bot is None) == (db is None)):
            raise ValueError('either bot must be specified xor table and db must be specified.')
        if bot:
            return bot.db, bot.config.ratfacts.table
        return db, table

    @classmethod
    def _load(cls, row, fields=None):
        """
        Return a Fact object representing a row in the database
        :param row: Result of fetchrow()
        :param fields: Field order.  Defaults to cls.FIELDS
        :return: A Fact
        """
        if fields is None:
            fields = cls.FIELDS
        d = dict(zip(fields, row))
        return cls(name=d.get('name'), lang=d.get('lang'), message=d.get('message'), author=d.get('author'))

    @classmethod
    def _save(cls, fact, bot=None, db=None, table=None, using='REPLACE', fields=None):
        """
        Modifies/creates a Fact in the database
        :param fact: Fact instance to save
        :param bot:
        :param db:
        :param table:
        :param using:
        :return:
        """
        if fields is None:
            fields = cls.FIELDS

        db, table = cls._getdbtable(bot, db, table)
        params = list(getattr(fact, field) for field in fields)
        sql = "{using} INTO {table} ({fields}) VALUES ({values})".format(
            using=using,
            table=table,
            fields=", ".join(fields),
            values=", ".join("?" for _ in range(len(fields)))
        )
        result = db.execute(sql, params).rowcount
        if not bot:
            return result
        mem = bot.memory['ratbot']['ratfacts']
        with mem['langs'] as langs, mem['facts'] as facts:
            facts.add(fact.name)
            langs.add(fact.lang)
        return result

    @classmethod
    def _delete(cls, fact, bot=None, db=None, table=None):
        db, table = cls._getdbtable(bot, db, table)

        result = db.execute(
            "DELETE FROM {table} WHERE name=? AND lang=?".format(table=table),
            [fact.name, fact.lang]
        ).rowcount
        if not bot:
            return result
        if result:
            mem = bot.memory['ratbot']['ratfacts']
            with mem['langs'] as langs, mem['facts'] as facts:
                row = db.execute(
                    "SELECT EXISTS(SELECT 1 FROM {table} WHERE name=?), EXISTS(SELECT 1 FROM {table} WHERE lang=?)"
                    .format(table=table), [fact.name, fact.lang]
                ).fetchone()
                if not row[0]:
                    facts.discard(fact.name)
                if not row[1]:
                    langs.discard(fact.lang)
        return result

    @classmethod
    def _sql(cls, select, where=None, order_by=None, limit=None):
        sql = select
        if where:
            sql += " WHERE {clauses}".format(clauses=" AND ".join(where))
        if order_by:
            sql += " ORDER BY {order_by}".format(order_by=", ".join(order_by))
        if limit:
            sql += " LIMIT {limit}".format(limit=limit)
        return sql

    @classmethod
    def find(cls, name, lang, bot=None, db=None, table=None):
        """
        Returns a fact from the database.

        :param name: Name of fact to retrieve.  Lowercased and stripped.
        :param lang: Language to retrieve.  Lowercased and stripped.  If this is an iterable other than string,
            each language in it will be attempted in order until one is found.
        :param bot: Bot instance to query.
        :param db: Database connection to query.
        :param table: Table to query.

        If bot is specified, db and table must not be specified.  Otherwise, db and table must be specified.
        """
        db, table = cls._getdbtable(bot, db, table)

        name, lang, where, params = cls._getfactsql(name, lang)
        if not name:
            raise ValueError('name is required')
        if not lang:
            raise ValueError('lang is required')

        order_by = []
        # If we're querying multiple languages, we'll need to sort the results so we get only the first matching result
        # based on our search order.
        if len(lang) > 1:
            params.extend(lang)  # Add a second copy of the lang parameters for the ORDER BY portion.
            order_by.append(
                "CASE lang {whens} END".format(
                    whens=" ".join("WHEN ? THEN {}".format(i) for i in range(len(lang)))
                )
            )

        c = db.execute(
            cls._sql(
                "SELECT {fields} FROM {table}".format(fields=", ".join(cls.FIELDS), table=table),
                where=where, order_by=order_by, limit="1"
            ), params
        )
        for row in c:
            return cls._load(row)
        return None

    @classmethod
    def findall(cls, name=None, lang=None, bot=None, db=None, table=None, order_by=None):
        """
        Yields all matching facts from the database

        :param name: Name of fact(s) to retrieve, or None to retrieve all facts.  Lowercased and stripped.
        :param lang: Language to retrieve, or None to retrieve all languages.  Lowercased and stripped.
        :param bot: Bot instance to query.
        :param db: Database connection to query.
        :param table: Table to query.

        If bot is specified, db and table must not be specified.  Otherwise, db and table must be specified.
        """
        db, table = cls._getdbtable(bot, db, table)
        name, lang, where, params = cls._getfactsql(name, lang)
        c = db.execute(
            cls._sql(
                "SELECT {fields} FROM {table}".format(fields=", ".join(cls.FIELDS), table=table),
                where=where, order_by=order_by
            ), params
        )
        for row in c:
            yield cls._load(row, fields=cls.FIELDS)
        return

    @classmethod
    def unique_names(cls, lang=None, bot=None, db=None, table=None, order_by=['name']):
        """
        Yields a list of distinct fact names matching the language parameter, or all languages if lang is None
        :param lang:
        :param bot: Bot instance to query.
        :param db: Database connection to query.
        :param table: Table to query.
        :return:
        """
        db, table = cls._getdbtable(bot, db, table)
        _, lang, where, params = cls._getfactsql(None, lang)
        c = db.execute(
            cls._sql(
                "SELECT DISTINCT name FROM {table} ".format(table=table),
                where=where, order_by=order_by
            ), params
        )
        for row in c:
            yield row[0]

    @classmethod
    def unique_langs(cls, name=None, bot=None, db=None, table=None, order_by=['lang']):
        """
        Yields a list of distinct fact languages matching the name parameter, or all facts if name is None
        :param lang:
        :param bot: Bot instance to query.
        :param db: Database connection to query.
        :param table: Table to query.
        :return:
        """
        db, table = cls._getdbtable(bot, db, table)
        name, _, where, params = cls._getfactsql(name, None)
        c = db.execute(
            cls._sql(
                "SELECT DISTINCT lang FROM {table} ".format(table=table),
                where=where, order_by=order_by
            ), params
        )
        for row in c:
            yield row[0]

    @classmethod
    def import_dict(cls, data, lang, bot=None, db=None, table=None, using="INSERT OR IGNORE"):
        """
        Imports a dictionary into the database.  Used for converting json facts.

        :param data: Dictionary to import
        :param lang: Default language to assign to imported data
        :param bot: Bot instance to query.
        :param db: Database connection to query.
        :param table: Table to query.

        Each key-value pair in the dictionary may be in one of the following formats:
        lang = { fact: value, .... }
        fact = value
        """
        for k, v in data.items():
            if isinstance(v, dict):
                for name, message in v.items():
                    fact = cls(name=name, message=message, lang=k)
                    fact.save(bot, db, table, using)
            else:
                fact = cls(name=k, message=v, lang=lang)
                fact.save(bot, db, table, using)

def configure(config):
    config.define_section('ratfacts', RatfactsSection)
    config.ratfacts.configure_setting(
        'filename',
        (
            "If specified, facts in this file will be imported to the database on startup.  These facts will not "
            " override existing entries in the database.  If this is a directory, all *.json files in that directory "
            " will be imported."
        )
    )
    config.ratfacts.configure_setting('table', "Defines what database table facts will be stored in.")
    config.ratfacts.configure_setting(
        'language',
        (
            "Comma-separated list of languages to search when requesting a fact with no language identifier."
            " The first language in this list is the default language for new facts."
        )
    )


def rescan_facts(bot):
    """
    To avoid a database lookup on every possible command, we store a set of unique fact names in memory.  The database
    is only queried if a fact matches something in the set.
    """
    mem = bot.memory['ratbot']['ratfacts']
    mem['facts'] = LockableSet(Fact.unique_names(bot=bot))
    mem['langs'] = LockableSet(Fact.unique_langs(bot=bot))


def import_facts(bot, using="INSERT OR IGNORE"):
    """
    import json data into the fact database
    """
    filename = bot.config.ratfacts.filename
    if filename:
        Fact.import_dict(getfacts(filename), lang=bot.memory['ratbot']['ratfacts']['lang-order'][0], bot=bot)


def setup(bot):
    # Sanity-check the facts database
    table = bot.config.ratfacts.table or 'ratfacts'
    bot.config.ratfacts.table = table
    # Check to see if our table exists
    try:
        bot.db.execute("SELECT * FROM {table} LIMIT 1".format(table=table))
    except:
        # Doesn't exist.  Attempt to create it.
        try:
            bot.db.execute(
                "CREATE TABLE {table} ("
                "   name TEXT NOT NULL,"
                "   lang TEXT NOT NULL,"
                "   message TEXT NOT NULL,"
                "   author TEXT NULL,"
                "   PRIMARY KEY(name, lang)"
                ")".format(table=table)
            )
            print("rat-facts: Created initial database schema.")
        except Exception as ex:
            raise RuntimeError("Unable to initialize the rat-facts database.") from ex

    # Check to see if the table has the columns we expect it to have.
    try:
        bot.db.execute("SELECT {columns} FROM {table} LIMIT 1".format(table=table, columns=", ".join(Fact.FIELDS)))
    except Exception as ex:
        raise RuntimeError("rat-facts database is in an unexpected format.") from ex

    if 'ratbot' not in bot.memory:
        bot.memory['ratbot'] = SopelMemory()
    mem = SopelMemory()
    bot.memory['ratbot']['ratfacts'] = mem
    mem['facts'] = LockableSet()
    mem['langs'] = LockableSet()

    # Determine languages
    langs = bot.config.ratfacts.language or 'en'
    langs = [lang.strip().lower() for lang in langs.split(",")]
    mem['lang-order'] = langs

    # Import facts
    import_facts(bot)

    # Build fact cache
    rescan_facts(bot)


def getfacts(path, recurse=True):
    """
    Loads facts from the specified filename.

    If filename is a directory and recurse is True, loads all json files in that directory.
    """
    facts = {}
    if recurse and os.path.isdir(path):
        for filename in glob.iglob(os.path.join(path, "*.json")):
            result = getfacts(filename, recurse=False)
            if result:
                facts.update(result)
        return facts

    with open(path) as f:
        facts = json.load(f)

    if not isinstance(facts, dict):
        # Something horribly wrong with the json
        raise RuntimeError("{}: json structure is not a dict.".format(path))
    return facts

def find_fact(bot, text, exact=False):
    mem = bot.memory['ratbot']['ratfacts']
    facts = mem['facts']
    lang_search = mem['lang-order']

    if text in facts:
        lang = lang_search[0] if exact else lang_search
        return Fact.find(name=text, lang=lang, bot=bot)

    if '-' in text:
        name, lang = text.rsplit('-', 1)
        if name not in facts:
            return None
        if not exact:
            lang = [lang] + lang_search
        return Fact.find(name=name, lang=lang, bot=bot)
    return None

def format_fact(fact):
    return (
        "\x02{fact.name}-{fact.lang}\x02 - {fact.message} ({author})"
        .format(fact=fact, author=("by " + fact.author) if fact.author else 'unknown')
    )

@commands(r'[^\s]+')
def reciteFact(bot, trigger):
    """Recite facts"""
    fact = find_fact(bot, trigger.group(1))
    if not fact:
        return NOLIMIT

    rats = trigger.group(2)
    if rats:
        # Reorganize the rat list for consistent & proper separation
        # Split whitespace, comma, colon and semicolon (all common IRC multinick separators) then rejoin with commas
        rats = ", ".join(filter(None, re.split(r"[,\s+]", rats))) or None

    # reply_to automatically picks the sender's name if rats is None, no additional logic needed
    return bot.reply(fact.message, reply_to=rats)


@commands('fact', 'facts')
def listFacts(bot, trigger):
    """
    Lists known facts, list details on a fact, or rescans the fact database.

    !fact - Lists all known facts
    !fact FACT [full] - Shows detailed stats on the specified fact.  'full' dumps all translations to a PM.
    !fact LANGUAGE [full] - Shows detailed stats on the specified language.  'full' dumps all facts to a PM.

    The following commands require privileges:
    !fact rescan - Rebuilds the fact cache.  Should only be needed if the sqlite file is externally modified.
    !fact import - Reimports JSON data and triggers rescan
    !fact full - Dumps all facts, all languages to a PM.
    !fact add <id> <text> - Creates a new fact or updates an existing one.  <id> must be of the format <factname>-<lang>
        Aliases: set
    !fact del <id> <text> - Deletes a fact.  <id> must be of the format <factname>-<lang>
        Aliases: delete remove
    """
    pm = functools.partial(bot.say, destination=trigger.nick)
    mem = bot.memory['ratbot']['ratfacts']

    parts = re.split(r'\s+', trigger.group(2), maxsplit=2) if trigger.group(2) else None
    command = parts.pop(0) if parts else None
    option = parts.pop(0) if parts else None
    extra = parts[0] if parts else None

    access = 0
    if command in('full', 'rescan', 'import', 'add', 'del', 'delete', 'set'):
        nick = Identifier(trigger.nick)
        for channel in bot.privileges.values():
            access |= channel.get(nick, 0)

    if not command:
        with mem['facts'] as facts:
            if not facts:
                return bot.reply("Like Jon Snow, I know nothing.  (Or there's a problem with the fact database.)")
            return bot.reply("{} known fact(s): {}".format(len(facts), ", ".join(sorted(facts))))

    if command == 'rescan':
        if access & (HALFOP | OP):
            rescan_facts(bot)
            return bot.reply("Facts rescanned.  {} known fact(s).".format(len(mem['facts'])))
        return bot.reply("Not authorized.")

    if command == 'import':
        if access & (HALFOP | OP):
            import_facts(bot)
            return bot.reply("Facts imported.  {} known fact(s).".format(len(mem['facts'])))
        return bot.reply("Not authorized.")

    if command == 'full':
        if access & (HALFOP | OP):
            if not trigger.is_privmsg:
                bot.reply("Messaging you the complete fact database.")
            pm("Language search order is {}".format(", ".join(bot.memory['ratbot']['ratfacts']['lang-order'])))
            for fact in Fact.findall(bot=bot, order_by=['name', 'lang']):
                pm(format_fact(fact))
            pm("-- End of list --")
            return NOLIMIT
        else:
            return bot.reply("Not authorized.")

    if command in ('add', 'set', 'del', 'delete', 'remove'):
        if access & (HALFOP | OP):
            if not option:
                bot.reply("Missing fact.")
                return NOLIMIT
            if '-' not in option:
                bot.reply(
                    "Fact must include a language specifier.  (Perhaps you meant '{name}-{lang}'?)"
                    .format(name=option, lang=mem['lang-order'][0])
                )
                return NOLIMIT
            name, lang = option.rsplit('-', 1)
            if command in('add', 'set'):
                message = extra.strip() if extra else None
                if not message:
                    bot.reply("Can't add a blank fact.")
                    return NOLIMIT
                fact = Fact(name=name, lang=lang, message=extra, author=trigger.nick)
                fact.save(bot)
                bot.reply("Added " + format_fact(fact))
                return NOLIMIT
            fact = Fact.find(name=name, lang=lang, bot=bot)
            if fact:
                fact.delete(bot)
                bot.reply("Deleted " + format_fact(fact))
            else:
                bot.reply("No such fact.")
            return NOLIMIT
        return bot.reply("Not authorized.")

    def _translation_stats(exists, missing, s='translation', p='translations'):
        if exists:
            exists = "{count} {word} ({names})".format(
                count=len(exists), word=s if len(exists) == 1 else p, names=", ".join(sorted(exists))
            )
        else:
            exists = "no " + p
        if missing:
            missing = "missing {count} ({names})".format(count=len(missing), names=", ".join(sorted(missing)))
        else:
            missing = "none missing"
        return exists + ", " + missing

    # See if it's the name of a fact.
    with mem['facts'] as facts, mem['langs'] as langs:
        full = option == 'lower'
        prop = None

        if command in facts:
            if full:
                if not trigger.is_privmsg:
                    bot.reply("Messaging you what I know about fact '{}'".format(command))
                    pm("Fact search for name='{}'".format(command))
                    exists = set()
                    for fact in Fact.findall(bot=bot, name=command, order_by=['lang']):
                        pm(format_fact(fact))
                        exists.add(fact.lang)
                    missing = set(langs) - exists
            else:
                exists = set(Fact.unique_langs(bot=bot, name=command))
                missing = set(langs) - exists

            summary = (
                "Fact {}: ".format(command) +
                _translation_stats(exists, missing, s='translation', p='translations')
            )
            if full:
                pm(summary)
                return NOLIMIT
            bot.reply(summary)
            return NOLIMIT
        elif command in langs:
            if full:
                if not trigger.is_privmsg:
                    bot.reply("Messaging you what I know about language '{}'".format(command))
                    pm("Fact search for lang='{}'".format(command))
                    exists = set()
                    for fact in Fact.findall(bot=bot, lang=command, order_by=['fact']):
                        pm(format_fact(fact))
                        exists.add(fact.name)
                    missing = set(facts) - exists
            else:
                exists = set(Fact.unique_names(bot=bot, lang=command))
                missing = set(facts) - exists
            summary = (
                "Language {}: ".format(command) +
                _translation_stats(exists, missing, s='fact', p='facts')
            )
            if full:
                pm(summary)
                return NOLIMIT
            bot.reply(summary)
            return NOLIMIT

    bot.reply("'{}' is not a known fact, language, or subcommand".format(command))
    return NOLIMIT
