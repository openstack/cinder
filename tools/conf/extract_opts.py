# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 SINA Corporation
# All Rights Reserved.
# Author: Zhongyue Luo <lzyeval@gmail.com>
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Extracts OpenStack config option info from module(s)."""

from __future__ import print_function

import __builtin__
setattr(__builtin__, '_', lambda x: x)
import os
import re
import socket
import sys
import textwrap

from oslo.config import cfg

from cinder.openstack.common import importutils

STROPT = "StrOpt"
BOOLOPT = "BoolOpt"
INTOPT = "IntOpt"
FLOATOPT = "FloatOpt"
LISTOPT = "ListOpt"
MULTISTROPT = "MultiStrOpt"

OPTION_REGEX = re.compile(r"(%s)" % "|".join([STROPT, BOOLOPT, INTOPT,
                                              FLOATOPT, LISTOPT,
                                              MULTISTROPT]))
OPTION_HELP_INDENT = "####"

PY_EXT = ".py"
BASEDIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
WORDWRAP_WIDTH = 60


def main(srcfiles):
    print('\n'.join(['#' * 20, '# cinder.conf sample #', '#' * 20,
                     '', '[DEFAULT]', '']))
    _list_opts(cfg.ConfigOpts,
               cfg.__name__ + ':' + cfg.ConfigOpts.__name__)
    mods_by_pkg = dict()
    for filepath in srcfiles:
        pkg_name = filepath.split(os.sep)[1]
        mod_str = '.'.join(['.'.join(filepath.split(os.sep)[:-1]),
                            os.path.basename(filepath).split('.')[0]])
        mods_by_pkg.setdefault(pkg_name, list()).append(mod_str)
    # NOTE(lzyeval): place top level modules before packages
    pkg_names = filter(lambda x: x.endswith(PY_EXT), mods_by_pkg.keys())
    pkg_names.sort()
    ext_names = filter(lambda x: x not in pkg_names, mods_by_pkg.keys())
    ext_names.sort()
    pkg_names.extend(ext_names)
    for pkg_name in pkg_names:
        mods = mods_by_pkg.get(pkg_name)
        mods.sort()
        for mod_str in mods:
            _print_module(mod_str)


def _print_module(mod_str):
    mod_obj = None
    if mod_str.endswith('.__init__'):
        mod_str = mod_str[:mod_str.rfind(".")]
    try:
        mod_obj = importutils.import_module(mod_str)
    except Exception as e:
        sys.stderr.write("Failed to collect options from module %s: %s\n" % (
            mod_str, str(e)))
        return
    _list_opts(mod_obj, mod_str)


def _list_opts(obj, name):
    opts = list()
    for attr_str in dir(obj):
        attr_obj = getattr(obj, attr_str)
        if isinstance(attr_obj, cfg.Opt):
            opts.append(attr_obj)
        elif (isinstance(attr_obj, list) and
              all(map(lambda x: isinstance(x, cfg.Opt), attr_obj))):
            opts.extend(attr_obj)
    if not opts:
        return
    print('#')
    print('# Options defined in %s' % name)
    print('#')
    print()
    for opt in opts:
        _print_opt(opt)
    print()


def _get_my_ip():
    try:
        csock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        csock.connect(('8.8.8.8', 80))
        (addr, port) = csock.getsockname()
        csock.close()
        return addr
    except socket.error:
        return None


MY_IP = _get_my_ip()
HOST = socket.gethostname()


def _sanitize_default(s):
    """Set up a reasonably sensible default for pybasedir, my_ip and host."""
    if s.startswith(BASEDIR):
        return s.replace(BASEDIR, '/usr/lib/python/site-packages')
    elif s == MY_IP:
        return '10.0.0.1'
    elif s == HOST:
        return 'cinder'
    elif s.strip() != s:
        return '"%s"' % s
    return s


OPT_TYPES = {
    'StrOpt': 'string value',
    'BoolOpt': 'boolean value',
    'IntOpt': 'integer value',
    'FloatOpt': 'floating point value',
    'ListOpt': 'list value',
    'MultiStrOpt': 'multi valued',
}


def _print_opt(opt):
    opt_name, opt_default, opt_help = opt.dest, opt.default, opt.help
    if not opt_help:
        sys.stderr.write('WARNING: "%s" is missing help string.\n' % opt_name)
    opt_type = None
    try:
        opt_type = OPTION_REGEX.search(str(type(opt))).group(0)
    except (ValueError, AttributeError) as err:
        sys.stderr.write("%s\n" % str(err))
        sys.exit(1)
    opt_help += ' (' + OPT_TYPES[opt_type] + ')'
    print('#', "\n# ".join(textwrap.wrap(opt_help, WORDWRAP_WIDTH)))
    try:
        if opt_default is None:
            print('#%s=<None>' % opt_name)
        elif opt_type == STROPT:
            assert(isinstance(opt_default, basestring))
            print('#%s=%s' % (opt_name, _sanitize_default(opt_default)))
        elif opt_type == BOOLOPT:
            assert(isinstance(opt_default, bool))
            print('#%s=%s' % (opt_name, str(opt_default).lower()))
        elif opt_type == INTOPT:
            assert(isinstance(opt_default, int) and
                   not isinstance(opt_default, bool))
            print('#%s=%s' % (opt_name, opt_default))
        elif opt_type == FLOATOPT:
            assert(isinstance(opt_default, float))
            print('#%s=%s' % (opt_name, opt_default))
        elif opt_type == LISTOPT:
            assert(isinstance(opt_default, list))
            print('#%s=%s' % (opt_name, ','.join(opt_default)))
        elif opt_type == MULTISTROPT:
            assert(isinstance(opt_default, list))
            if opt_default:
                for default in opt_default:
                    print('#%s=%s' % (opt_name, default))
            else:
                print('#%s=' % (opt_name))
        print()
    except Exception:
        sys.stderr.write('Error in option "%s"\n' % opt_name)
        sys.exit(1)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("usage: python %s [srcfile]...\n" % sys.argv[0])
        sys.exit(0)
    main(sys.argv[1:])
