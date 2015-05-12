from rez import __version__
from rez.vendor.memcache.memcache import Client as Client_, SERVER_MAX_KEY_LENGTH
from functools import update_wrapper
from inspect import getargspec
from hashlib import md5
from uuid import uuid4


def get_memcached_client():
    """Get a configured memcached client."""
    from rez.config import config
    return Client(servers=config.memcached_uri)


class Client(object):
    """Wrapper for memcache.Client instance.

    Adds the features:
    - unlimited key length;
    - hard/soft flushing;
    - ability to cache None.
    """
    class _Miss(object):
        def __nonzero__(self): return False
    miss = _Miss()

    def __init__(self, servers, debug=False):
        """Create a memcached client.

        Args:
            servers (str or list of str): Server URI(s), eg '127.0.0.1:11211'.
            debug (bool): If True, quasi human readable keys are used. This helps
                debugging - run 'memcached -vv' in the foreground to see the keys
                being get/set/stored.
        """
        self.servers = [servers] if isinstance(servers, basestring) else servers
        self.key_hasher = self._debug_key_hash if debug else self._key_hash
        self._client = None
        self.debug = debug
        self.current = ''

    def __nonzero__(self):
        return bool(self.servers)

    @property
    def client(self):
        """Get the native memcache client.

        Returns:
            `memcache.Client` instance.
        """
        if self._client is None:
            self._client = Client_(self.servers)
        return self._client

    def test_servers(self):
        """Test that memcached servers are servicing requests.

        Returns:
            set: URIs of servers that are responding.
        """
        responders = set()
        for server in self.servers:
            client = Client_([server])
            key = uuid4().hex
            client.set(key, 1)
            if client.get(key) == 1:
                responders.add(server)
        return responders

    def set(self, key, val, time=0, min_compress_len=0):
        """See memcache.Client."""
        key = self._qualified_key(key)
        hashed_key = self.key_hasher(key)
        val = (key, val)

        self.client.set(key=hashed_key,
                        val=val,
                        time=time,
                        min_compress_len=min_compress_len)

    def get(self, key):
        """See memcache.Client.

        Returns:
            object: A value if cached, else `self.miss`. Note that this differs
            from `memcache.Client`, which returns None on cache miss, and thus
            cannot cache the value None itself.
        """
        key = self._qualified_key(key)
        hashed_key = self.key_hasher(key)
        entry = self.client.get(hashed_key)

        if isinstance(entry, tuple) and len(entry) == 2:
            key_, result = entry
            if key_ == key:
                return result
        return self.miss

    def delete(self, key):
        """See memcache.Client."""
        key = self._qualified_key(key)
        hashed_key = self.key_hasher(key)
        self.client.delete(hashed_key)

    def flush(self, hard=False):
        """Drop existing entries from the cache.

        Args:
            hard (bool): If True, all current entries are flushed from the
                server(s), which affects all users. If False, only the local
                process is affected.
        """
        if hard:
            self.client.flush_all()
            self.reset_stats()
        else:
            from uuid import uuid4
            tag = uuid4().hex
            if self.debug:
                tag = "flushed" + tag
            self.current = tag

    def get_stats(self):
        """Get server statistics.

        Returns:
            A list of tuples (server_identifier, stats_dictionary).
        """
        return self._get_stats()

    def reset_stats(self):
        """Reset the server stats."""
        self._get_stats("reset")

    def _qualified_key(self, key):
        return "%s:%s:%s" % (__version__, self.current, key)

    def _get_stats(self, stat_args=None):
        return self.client.get_stats(stat_args=stat_args)

    @classmethod
    def _key_hash(cls, key):
        return md5(key).hexdigest()

    @classmethod
    def _debug_key_hash(cls, key):
        import re
        h = cls._key_hash(key)[:16]
        value = "%s:%s" % (h, key)
        value = value[:SERVER_MAX_KEY_LENGTH]
        value = re.sub("[^0-9a-zA-Z]+", '_', value)
        return value


def memcached(servers, key=None, from_cache=None, to_cache=None, time=0,
              min_compress_len=0, debug=False):
    """memcached memoization function decorator.

    The wrapped function is expected to return a value that is stored to a
    memcached server, first translated by `to_cache` if provided. In the event
    of a cache hit, the data is translated by `from_cache` if provided, before
    being returned. If you do not want a result to be cached, wrap the return
    value of your function in a `DoNotCache` object.

    Example:

        @memcached('127.0.0.1:11211')
        def _listdir(path):
            return os.path.listdir(path)

    Note:
        If using the default key function, ensure that repr() is implemented on
        all your arguments and that they are hashable.

    Note:
        `from_cache` and `to_cache` both accept the value as first parameter,
        then the target function's arguments follow.

    Args:
        servers (str or list of str): memcached server uri(s), eg '127.0.0.1:11211'.
            This arg can be None also, in which case memcaching is disabled.
        key (callable, optional): Function that, given the target function's args,
            returns the string key to use in memcached.
        from_cache (callable, optional): If provided, and a cache hit occurs, the
            cached value will be translated by this function before being returned.
        to_cache (callable, optional): If provided, and a cache miss occurs, the
            function's return value will be translated by this function before
            being cached.
        time (int): Tells memcached the time which this value should expire, either
            as a delta number of seconds, or an absolute unix time-since-the-epoch
            value. See the memcached protocol docs section "Storage Commands"
            for more info on <exptime>. We default to 0 == cache forever.
        min_compress_len (int): The threshold length to kick in auto-compression
            of the value using the zlib.compress() routine. If the value being cached is
            a string, then the length of the string is measured, else if the value is an
            object, then the length of the pickle result is measured. If the resulting
            attempt at compression yeilds a larger string than the input, then it is
            discarded. For backwards compatability, this parameter defaults to 0,
            indicating don't ever try to compress.
        debug (bool): If True, memcache keys are kept human readable, so you can
            read them if running a foreground memcached proc with 'memcached -vv'.
            However this increases chances of key clashes so should not be left
            turned on.
    """
    def default_key(func, *nargs, **kwargs):
        parts = [func.__module__]

        argnames = getargspec(func).args
        if argnames:
            if argnames[0] == "cls":
                cls_ = nargs[0]
                parts.append(cls_.__name__)
                nargs = nargs[1:]
            elif argnames[0] == "self":
                cls_ = nargs[0].__class__
                parts.append(cls_.__name__)
                nargs = nargs[1:]

        parts.append(func.__name__)

        value = ('.'.join(parts), nargs, tuple(sorted(kwargs.items())))
        # make sure key is hashable. We don't strictly need it to be, but this
        # is a way of hopefully avoiding object types that are not ordered (these
        # would give an unreliable key). If you need to key on unhashable args,
        # you should provide your own `key` functor.
        _ = hash(value)
        return repr(value)

    def identity(value, *nargs, **kwargs):
        return value

    from_cache = from_cache or identity
    to_cache = to_cache or identity
    client = Client(servers, debug=debug)

    def decorator(func):
        if servers:
            def wrapper(*nargs, **kwargs):
                if key:
                    cache_key = key(*nargs, **kwargs)
                else:
                    cache_key = default_key(func, *nargs, **kwargs)

                # get
                result = client.get(cache_key)
                if result is not client.miss:
                    return from_cache(result, *nargs, **kwargs)

                # cache miss - run target function
                result = func(*nargs, **kwargs)
                if isinstance(result, DoNotCache):
                    return result.result

                # store
                cache_result = to_cache(result, *nargs, **kwargs)
                client.set(key=cache_key,
                           val=cache_result,
                           time=time,
                           min_compress_len=min_compress_len)
                return result
        else:
            def wrapper(*nargs, **kwargs):
                return func(*nargs, **kwargs)

        def forget():
            """Forget entries in the cache.

            Note that this does not delete entries from a memcached server - that
            would be slow and error-prone. Calling this function only ensures
            that entries set by the current process will no longer be seen during
            this process.
            """
            client.flush()

        wrapper.forget = forget
        wrapper.__wrapped__ = func
        return update_wrapper(wrapper, func)
    return decorator


class DoNotCache(object):
    def __init__(self, result):
        self.result = result
