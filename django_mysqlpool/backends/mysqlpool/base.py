# -*- coding: utf-8 -*-
"""The top-level package for ``django-mysqlpool``."""
# These imports make 2 act like 3, making it easier on us to switch to PyPy or
# some other VM if we need to for performance reasons.
from __future__ import (absolute_import, print_function, unicode_literals,
                        division)

import collections
import os

from django.conf import settings
from django.db.backends.mysql import base
from django.core.exceptions import ImproperlyConfigured

try:
    import sqlalchemy.pool as pool
except ImportError as e:
    raise ImproperlyConfigured("Error loading SQLAlchemy module: %s" % e)


# Make ``Foo()`` work the same in Python 2 as it does in Python 3.
__metaclass__ = type


# Global variable to hold the actual connection pool.
MYSQLPOOL = None
# Default pool type (QueuePool, SingletonThreadPool, AssertionPool, NullPool,
# StaticPool).
DEFAULT_BACKEND = 'QueuePool'
# Needs to be less than MySQL connection timeout (server setting). The default
# is 120, so default to 119.
DEFAULT_POOL_TIMEOUT = 119


class OldDatabaseProxy():

    """Saves a reference to the old connect function.

    Proxies calls to its own connect() method to the old function.
    """

    def __init__(self, old_connect):
        """Store ``old_connect`` to be used whenever we connect."""
        self.old_connect = old_connect

    def connect(self, **kwargs):
        """Delegate to the old ``connect``."""
        # Bounce the call to the old function.
        return self.old_connect(**kwargs)


class HashableDict(collections.OrderedDict):

    """A dictionary that is hashable.

    This is not generally useful, but created specifically to hold the ``conv``
    parameter that needs to be passed to MySQLdb.

    HT to `Alex Martelli`_ for the idea of using a shared ``__key`` function.

    .. _Alex Martelli: https://stackoverflow.com/a/1151686
    """

    @staticmethod
    def _is_iterable(test_me):
        """Determine whether ``test_me`` is iterable."""
        try:
            iter(test_me)
            return True
        except TypeError:
            return False

    @staticmethod
    def _tuplefy_as_needed(val):
        return tuple(val) if HashableDict._is_iterable(val) else val

    def __key(self):
        return tuple((k, HashableDict._tuplefy_as_needed(v))
                     for k, v in self.items())

    def __hash__(self):
        """Calculate the hash of this ``dict``.

        The hash is determined by converting to a sorted tuple of
        key-value pairs and hashing that.
        """
        return hash(self.__key())

    def __eq__(self, other):
        """Determine whether ``other`` is equal to this ``dict``.

        The implementation of this comparison uses the same underlying
        mechanism as ``__hash__``, in order to guarantee that ``==`` and
        ``.hash`` are in sync.
        """
        return self.__key() == other.__key()


# Define this here so Django can import it.
DatabaseWrapper = base.DatabaseWrapper


# Wrap the old connect() function so our pool can call it.
OldDatabase = OldDatabaseProxy(base.Database.connect)


def get_pool():
    """Create one and only one pool using the configured settings."""
    global MYSQLPOOL
    if MYSQLPOOL is None:
        backend_name = getattr(settings, 'MYSQLPOOL_BACKEND', DEFAULT_BACKEND)
        backend = getattr(pool, backend_name)
        kwargs = getattr(settings, 'MYSQLPOOL_ARGUMENTS', {})
        kwargs.setdefault('poolclass', backend)
        kwargs.setdefault('recycle', DEFAULT_POOL_TIMEOUT)
        MYSQLPOOL = pool.manage(OldDatabase, **kwargs)
        setattr(MYSQLPOOL, '_pid', os.getpid())

    if getattr(MYSQLPOOL, '_pid', None) != os.getpid():
        pool.clear_managers()
    return MYSQLPOOL


def connect(**kwargs):
    """Obtain a database connection from the connection pool."""
    conv = kwargs.pop('conv', None)
    if conv:
        # SQLAlchemy serializes the parameters to keep unique connection
        # parameter groups in their own pool. We need to store conv in a manner
        # that is compatible with their serialization.
        kwargs['conv'] = HashableDict(conv)
    # Open the connection via the pool.
    return get_pool().connect(**kwargs)


# Monkey-patch the regular mysql backend to use our hacked-up connect()
# function.
base.Database.connect = connect
