"""
Search for packages.
"""
from rez.settings import settings
from rez.packages import iter_package_families, iter_packages
from rez.vendor.version.version import VersionRange
from rez.vendor.version.requirement import Requirement
import os.path
import fnmatch
import sys


def setup_parser(parser):
    types_ = ("package", "family", "auto")
    parser.add_argument("-s", "--sort", action="store_true",
                        help="print results in sorted order")
    parser.add_argument("-t", "--type", default="auto", choices=types_,
                        help="type of resource to search for. If 'auto', "
                        "either packages or package families are searched, "
                        "depending on NAME and VERSION")
    parser.add_argument("--nl", "--no-local", dest="no_local",
                        action="store_true",
                        help="don't search local packages")
    parser.add_argument("--paths", type=str, default=None,
                        help="set package search path")
    parser.add_argument("-f", "--format", type=str, default=None,
                        help="format package output, eg "
                        "--format='{qualified_name} | {description}'")
    parser.add_argument("-e", "--errors", action="store_true",
                        help="only print packages that contain errors")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="verbose mode, repeat for more verbosity")
    parser.add_argument("NAME", type=str, nargs='?',
                        help="only match packages with the given family "
                        "name. Glob-style patterns are supported")
    parser.add_argument("VERSION", type=str, nargs='?',
                        help="range of package versions to match")


def command(opts, parser):
    if opts.paths is None:
        pkg_paths = settings.nonlocal_packages_path if opts.no_local else None
    else:
        pkg_paths = (opts.paths or "").split(os.pathsep)
        pkg_paths = [os.path.expanduser(x) for x in pkg_paths if x]

    name_pattern = opts.NAME or '*'
    version_range = VersionRange(opts.VERSION) if opts.VERSION else None

    if opts.NAME and not version_range:
        # support syntax ala 'rez-search foo-1.2+'
        req = Requirement(opts.NAME)
        if req.range:
            name_pattern = req.name
            version_range = req.range

    type_ = opts.type
    if type_ == "auto" and version_range:
        type_ = "package"

    # families
    num_matches = 0
    family_names = []
    families = iter_package_families(paths=pkg_paths)
    if opts.sort:
        families = sorted(families, key=lambda x: x.name)
    for family in families:
        if family.name not in family_names and \
                fnmatch.fnmatch(family.name, name_pattern):
            family_names.append(family.name)
            if type_ == "auto":
                type_ = "package" if family.name == name_pattern else "family"
            if type_ == "family":
                print family.name
                num_matches += 1

    # packages
    if type_ == "package":
        for name in family_names:
            packages = iter_packages(name, version_range)
            if opts.sort:
                packages = sorted(packages, key=lambda x: x.version)
            for package in packages:
                if opts.errors:
                    try:
                        package.validate()
                    except Exception as e:
                        print str(e)
                        num_matches += 1
                elif opts.format:
                    try:
                        print package.format(opts.format, pretty=True)
                    except Exception as e:
                        print >> sys.stderr, str(e)
                        num_matches += 1
                else:
                    print package.qualified_name
                    num_matches += 1

    if not num_matches:
        if opts.errors:
            print "no erroneous packages found"
        else:
            print "no matches found"
            sys.exit(1)
