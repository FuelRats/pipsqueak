#coding: utf8
"""
rat-facts.py - Fact reciting module
Copyright 2015, Dimitri "Tyrope" Molenaars <tyrope@tyrope.nl>
Copyright 2016, Daniel "Dewin" Grace
Licensed under the Eiffel Forum License 2.

These modules are built on top of the Sopel system.
http://sopel.chat/
"""

import json
import os.path
import re
import glob
import functools

from sopel.module import commands, NOLIMIT, HALFOP, OP
from sopel.config.types import StaticSection, ValidatedAttribute, ListAttribute
from sopel.tools import SopelMemory, Identifier
from sqlalchemy import exc, inspect

from ratlib.db import Fact, with_db
import ratlib.sopel


class RatfactsSection(StaticSection):
    filename = ValidatedAttribute('filename', str, default='')
    lang = ListAttribute('lang', str, default=['en'])


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
    config.ratfacts.configure_setting(
        'lang',
        (
            "Comma-separated list of languages to search when requesting a fact with no language identifier."
            " The first language in this list is the default language for new facts."
        )
    )


@with_db
def import_facts(bot, merge=False, db=None):
    """
    Import json data into the fact database

    :param bot: Sopel instance
    :param merge: If True, incoming facts overwrite existing ones rather than being ignored.
    """
    filename = bot.config.ratfacts.filename
    if not filename:
        return
    try:
        lang = bot.config.ratfacts.lang[0]
    except:
        lang = 'en'

    def _gen(json):
        for k, v in json.items():
            if isinstance(v, dict):
                for name, message in v.items():
                    yield Fact(name=name, lang=k, message=message)
            else:
                yield Fact(name=k, lang=lang, message=v)

    for fact in _gen(load_fact_json(filename)):
        try:
            with db.begin_nested():
                if merge:
                    fact = db.merge(fact)
                else:
                    fact = db.add(fact)
        except exc.DatabaseError:
            if merge:  # Shouldn't have errors in this case
                raise
    db.commit()


def setup(bot):
    ratlib.sopel.setup(bot)
    try:
        lang = bot.config.ratfacts.lang
    except:
        lang = ['en']
    else:
        if not lang:
            lang = ['en']
    bot.config.ratfacts.lang = lang

    # Import facts
    import_facts(bot)


def load_fact_json(path, recurse=True):
    """
    Loads facts from the specified filename.

    If filename is a directory and recurse is True, loads all json files in that directory.
    """
    facts = {}
    if recurse and os.path.isdir(path):
        for filename in glob.iglob(os.path.join(path, "*.json")):
            result = load_fact_json(filename, recurse=False)
            if result:
                facts.update(result)
        return facts

    with open(path) as f:
        facts = json.load(f)

    if not isinstance(facts, dict):
        # Something horribly wrong with the json
        raise RuntimeError("{}: json structure is not a dict.".format(path))
    return facts


@with_db
def find_fact(bot, text, exact=False, db=None):
    lang_search = bot.config.ratfacts.lang

    fact = Fact.find(db, name=text, lang=lang_search[0] if exact else lang_search)
    if fact:
        return fact
    if '-' in text:
        name, lang = text.rsplit('-', 1)
        if not exact:
            lang = [lang] + lang_search
        return Fact.find(db, name=name, lang=lang)
    return None


def format_fact(fact):
    return (
        "\x02{fact.name}-{fact.lang}\x02 - {fact.message} ({author})"
        .format(fact=fact, author=("by " + fact.author) if fact.author else 'unknown')
    )

@commands(r'[^\s]+')
def cmd_recite_fact(bot, trigger):
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
@with_db
def cmd_fact(bot, trigger, db=None):
    """
    Lists known facts, list details on a fact, or rescans the fact database.

    !fact - Lists all known facts
    !fact FACT [full] - Shows detailed stats on the specified fact.  'full' dumps all translations to a PM.
    !fact LANGUAGE [full] - Shows detailed stats on the specified language.  'full' dumps all facts to a PM.

    The following commands require privileges:
    !fact import - Reimports JSON data and triggers rescan
    !fact full - Dumps all facts, all languages to a PM.
    !fact add <id> <text> - Creates a new fact or updates an existing one.  <id> must be of the format <factname>-<lang>
        Aliases: set
    !fact del <id> <text> - Deletes a fact.  <id> must be of the format <factname>-<lang>
        Aliases: delete remove
    """
    pm = functools.partial(bot.say, destination=trigger.nick)
    parts = re.split(r'\s+', trigger.group(2), maxsplit=2) if trigger.group(2) else None
    command = parts.pop(0).lower() if parts else None
    option = parts.pop(0).lower() if parts else None
    extra = parts[0] if parts else None

    access = 0
    if command in('full', 'rescan', 'import', 'add', 'del', 'delete', 'set', 'remove'):
        nick = Identifier(trigger.nick)
        for channel in bot.privileges.values():
            access |= channel.get(nick, 0)


    if not command:
        # List known facts.
        unique_facts = list(Fact.unique_names(db))
        if not unique_facts:
            return bot.reply("Like Jon Snow, I know nothing.  (Or there's a problem with the fact database.)")
        return bot.reply("{} known fact(s): {}".format(len(unique_facts), ", ".join(unique_facts)))

    if command == 'import':
        if access & (HALFOP | OP):
            import_facts(bot)
            return bot.reply("Facts imported.")
        return bot.reply("Not authorized.")

    if command == 'full':
        if not (access & (HALFOP | OP)):
            return bot.reply("Not authorized.")
        if not trigger.is_privmsg:
            bot.reply("Messaging you the complete fact database.")
        pm("Language search order is {}".format(", ".join(bot.config.ratfacts.lang)))
        for fact in Fact.findall(db):
            pm(format_fact(fact))
        pm("-- End of list --")
        return NOLIMIT

    if command in ('add', 'set', 'del', 'delete', 'remove'):
        if not (access & (HALFOP | OP)):
            return bot.reply("Not authorized.")
        if not option:
            bot.reply("Missing fact.")
            return NOLIMIT
        if '-' not in option:
            bot.reply(
                "Fact must include a language specifier.  (Perhaps you meant '{name}-{lang}'?)"
                .format(name=option, lang=bot.config.ratfacts.lang[0])
            )
            return NOLIMIT
        name, lang = option.rsplit('-', 1)
        if command in('add', 'set'):
            message = extra.strip() if extra else None
            if not message:
                bot.reply("Can't add a blank fact.")
                return NOLIMIT
            fact = db.merge(Fact(name=name, lang=lang, message=extra, author=trigger.nick))
            is_new = not inspect(fact).persistent
            db.commit()
            bot.reply(("Added " if is_new else "Updated ") + format_fact(fact))
            return NOLIMIT
        fact = Fact.find(db, name=name, lang=lang)
        if fact:
            db.delete(fact)
            db.commit()
            bot.reply("Deleted " + format_fact(fact))
        else:
            bot.reply("No such fact.")
        return NOLIMIT

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

    # See if it's the name of a fact or a lang
    full = option == 'full'
    for attr, opposite, name, opposite_name_s, opposite_name_p in [
        ('name', 'lang', 'fact', 'translation', 'translations'),
        ('lang', 'name', 'language', 'fact', 'facts')
    ]:
        if not db.query(Fact.query(db, order_by=False, **{attr: command}).exists()).scalar():
            continue
        sq = Fact.unique_query(db, field=getattr(Fact, opposite), order_by=False).subquery()
        sq_opp = getattr(sq.c, opposite)
        fact_opp = getattr(Fact, opposite)
        fact_col = getattr(Fact, attr)

        query = (
            db.query(Fact, sq_opp)
            .select_from(sq.outerjoin(Fact, (sq_opp == fact_opp) & (fact_col == command)))
            .order_by(Fact.message.is_(None), sq_opp)
        )
        exists = set()
        missing = set()
        if full:
            if not trigger.is_privmsg:
                bot.reply("Messaging you what I know about {} '{}'".format(name, command))
            pm("Fact search for {} '{}'".format(name, command))

        for fact, key in query:
            if fact and full:
                pm(format_fact(fact))
            (exists if fact else missing).add(key)

        summary = (
            "{} '{}': ".format(name.title(), command) +
            _translation_stats(exists, missing, s=opposite_name_s, p=opposite_name_p)
        )
        if full:
            pm(summary)
            return NOLIMIT
        else:
            bot.reply(summary)
            return NOLIMIT

    bot.reply("'{}' is not a known fact, language, or subcommand".format(command))
    return NOLIMIT
