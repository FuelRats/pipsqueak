# Utility functions
import datetime

_zerodelta=datetime.timedelta()
def friendly_timedelta(delta):
    """
    Given a datetime.timedelta or a datetime.datetime, gives a human-readable explanation of time differences

    Assumes negative values are in the past, positive values in the future.
    """
    if isinstance(delta, datetime.datetime):
        return friendly_timedelta(delta - datetime.datetime.now(tz=delta.tzinfo))
    if isinstance(delta, datetime.date):
        return friendly_timedelta(delta - datetime.date.today())

    if delta < _zerodelta:
        # Delta is in the past
        delta = delta * -1  # Invert it to simplify math
        fmt = "{} ago"
    else:
        fmt = "{} from now"

    # Calculate some values
    d = delta.days
    s = delta.seconds
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)

    if d >= 365:  # More than a year ago.
        # This isn't technically safe against leap years, but it's an approximation anyways.  So deal.
        result = "{} years".format(d // 365.24)
    elif d >= 28:  # More than 28 days ago.  Let's just go to weeks.
        result = "{}w".format(d // 7)
    elif d >= 10:  # More than 10 days ago.  Long enough where we probably don't care about hours
        result = "{}d".format(d)
    elif d:
        result = "{}d,{}h".format(d, h)
    elif h:
        result = "{}h,{}m".format(h, m)
    elif m:
        result = "{}m,{}s".format(m, s)
    elif s:
        result = "{}s".format(s)
    else:
        return "now"
    return fmt.format(result)


def format_timedelta(delta):
    """
    Given a datetime.timedelta or a datetime.datetime, gives an exact(ish) representation of time difference
    """
    if isinstance(delta, datetime.datetime):
        return friendly_timedelta(delta - datetime.datetime.now(tz=delta.tzinfo))
    if isinstance(delta, datetime.date):
        return friendly_timedelta(delta - datetime.date.today())

    if delta < _zerodelta:
        # Delta is in the past
        delta = delta * -1  # Invert it to simplify math
        fmt = "-{}"
    else:
        fmt = "{}"

    # Calculate some values
    d = delta.days
    s = delta.seconds
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)

    if d:
        result = "{}d,{:02}h{:02}m{:02}s".format(d, h, m, s)
    elif h:
        result = "{}h{:02}m{:02}s".format(h, m, s)
    else:
        result = "{}m{:02}s".format(m, s)

    return fmt.format(result)


def format_timestamp(ts):
    if isinstance(ts, datetime.timedelta):
        return format_timedelta(ts)
    if isinstance(ts, datetime.datetime):
        if ts.tzinfo == datetime.timezone.utc:
            return ts.strftime("%b %d %H:%M:%S UTC")
        elif ts.tzinfo is None:
            return ts.strftime("%b %d %H:%M:%S")
        else:
            return ts.strftime("%b %d %H:%M:%S %Z")
    if isinstance(ts, datetime.date):
        return ts.strftime("%b %d, %Y")
    return ts.strftime("%H:%M:%S")
