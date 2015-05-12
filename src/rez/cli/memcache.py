"""
Manage and query memcache server(s).
"""


def setup_parser(parser, completions=False):
    parser.add_argument(
        "--flush", action="store_true",
        help="flush all cache entries")
    parser.add_argument(
        "--stats", action="store_true",
        help="list stats")
    parser.add_argument(
        "--reset-stats", action="store_true",
        help="reset statistics")
    parser.add_argument(
        "--poll", action="store_true",
        help="continually poll, showing get/sets per second")
    parser.add_argument(
        "--interval", type=float, metavar="SECS", default=1.0,
        help="interval (in seconds) used when polling (default: %(default)s)")


def poll(client, interval):
    import time

    prev_entry = None
    print "%-64s %-16s %-16s" % ("SERVER", "GET/s", "SET/s")

    while True:
        stats = dict(client.get_stats())
        entry = (time.time(), stats)

        if prev_entry:
            prev_t, prev_stats = prev_entry
            t, stats = entry

            dt = t - prev_t
            for instance, payload in stats.iteritems():
                prev_payload = prev_stats.get(instance)
                if prev_payload:
                    gets = int(payload["cmd_get"]) - int(prev_payload["cmd_get"])
                    sets = int(payload["cmd_set"]) - int(prev_payload["cmd_set"])
                    gets_per_sec = gets / dt
                    sets_per_sec = sets / dt
                    print "%-64s %-16g %-16g" % (instance, gets_per_sec, sets_per_sec)

        prev_entry = entry
        time.sleep(interval)


def command(opts, parser, extra_arg_groups=None):
    from rez.config import config
    from rez.utils.yaml import dump_yaml
    from rez.utils.memcached import get_memcached_client
    from rez.utils.formatting import columnise, readable_time_duration, \
        readable_memory_size
    import sys

    memcache_client = get_memcached_client()

    if not memcache_client:
        print >> sys.stderr, "memcaching is not enabled."
        sys.exit(1)

    if opts.poll:
        poll(memcache_client, opts.interval)
        return

    if opts.flush:
        memcache_client.flush(hard=True)
        print "memcached servers are flushed."
        return

    if opts.reset_stats:
        memcache_client.reset_stats()
        print "memcached servers are stat reset."
        return

    stats = memcache_client.get_stats()
    if opts.stats:
        if stats:
            txt = dump_yaml(stats)
            print txt
        return

    # print stats summary
    if not stats:
        print >> sys.stderr, "memcached servers are not responding."
        sys.exit(1)

    rows = [["CACHE SERVER", "UPTIME", "HITS", "MISSES", "HIT RATIO", "MEMORY", "USED"],
            ["------------", "------", "----", "------", "---------", "------", "----"]]

    for server_id, stats_dict in stats:
        server_uri = server_id.split()[0]
        uptime = int(stats_dict.get("uptime", 0))
        hits = int(stats_dict.get("get_hits", 0))
        misses = int(stats_dict.get("get_misses", 0))
        memory = int(stats_dict.get("limit_maxbytes", 0))
        used = int(stats_dict.get("bytes", 0))

        hit_ratio = float(hits) / max(hits + misses, 1)
        hit_percent = int(hit_ratio * 100.0)
        used_ratio = float(used) / max(memory, 1)
        used_percent = int(used_ratio * 100.0)

        row = (server_uri,
               readable_time_duration(uptime),
               str(hits),
               str(misses),
               "%d%%" % hit_percent,
               readable_memory_size(memory),
               "%s (%d%%)" % (readable_memory_size(used), used_percent))

        rows.append(row)
    print '\n'.join(columnise(rows))
