#!/usr/bin/env python
# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
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

# Interactive shell based on Django:
#
# Copyright (c) 2005, the Lawrence Journal-World
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     1. Redistributions of source code must retain the above copyright notice,
#        this list of conditions and the following disclaimer.
#
#     2. Redistributions in binary form must reproduce the above copyright
#        notice, this list of conditions and the following disclaimer in the
#        documentation and/or other materials provided with the distribution.
#
#     3. Neither the name of Django nor the names of its contributors may be
#        used to endorse or promote products derived from this software without
#        specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


"""
  CLI interface for cinder management.
"""

from __future__ import print_function


import os
import sys
import warnings

warnings.simplefilter('once', DeprecationWarning)

from oslo_config import cfg
from oslo_db.sqlalchemy import migration
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import uuidutils

from cinder import i18n
i18n.enable_lazy()

# Need to register global_opts
from cinder.common import config  # noqa
from cinder import context
from cinder import db
from cinder.db import migration as db_migration
from cinder.db.sqlalchemy import api as db_api
from cinder.i18n import _
from cinder.objects import base as objects_base
from cinder import rpc
from cinder import utils
from cinder import version


CONF = cfg.CONF


# Decorators for actions
def args(*args, **kwargs):
    def _decorator(func):
        func.__dict__.setdefault('args', []).insert(0, (args, kwargs))
        return func
    return _decorator


def param2id(object_id):
    """Helper function to convert various id types to internal id.
    args: [object_id], e.g. 'vol-0000000a' or 'volume-0000000a' or '10'
    """
    if uuidutils.is_uuid_like(object_id):
        return object_id
    elif '-' in object_id:
        # FIXME(ja): mapping occurs in nova?
        pass
    else:
        try:
            return int(object_id)
        except ValueError:
            return object_id


class ShellCommands(object):
    def bpython(self):
        """Runs a bpython shell.

        Falls back to Ipython/python shell if unavailable
        """
        self.run('bpython')

    def ipython(self):
        """Runs an Ipython shell.

        Falls back to Python shell if unavailable
        """
        self.run('ipython')

    def python(self):
        """Runs a python shell.

        Falls back to Python shell if unavailable
        """
        self.run('python')

    @args('--shell', dest="shell",
          metavar='<bpython|ipython|python>',
          help='Python shell')
    def run(self, shell=None):
        """Runs a Python interactive interpreter."""
        if not shell:
            shell = 'bpython'

        if shell == 'bpython':
            try:
                import bpython
                bpython.embed()
            except ImportError:
                shell = 'ipython'
        if shell == 'ipython':
            try:
                from IPython import embed
                embed()
            except ImportError:
                try:
                    # Ipython < 0.11
                    # Explicitly pass an empty list as arguments, because
                    # otherwise IPython would use sys.argv from this script.
                    import IPython

                    shell = IPython.Shell.IPShell(argv=[])
                    shell.mainloop()
                except ImportError:
                    # no IPython module
                    shell = 'python'

        if shell == 'python':
            import code
            try:
                # Try activating rlcompleter, because it's handy.
                import readline
            except ImportError:
                pass
            else:
                # We don't have to wrap the following import in a 'try',
                # because we already know 'readline' was imported successfully.
                import rlcompleter    # noqa
                readline.parse_and_bind("tab:complete")
            code.interact()

    @args('--path', required=True, help='Script path')
    def script(self, path):
        """Runs the script from the specified path with flags set properly.
        arguments: path
        """
        exec(compile(open(path).read(), path, 'exec'), locals(), globals())


def _db_error(caught_exception):
    print('%s' % caught_exception)
    print(_("The above error may show that the database has not "
            "been created.\nPlease create a database using "
            "'cinder-manage db sync' before running this command."))
    exit(1)


class HostCommands(object):
    """List hosts."""

    @args('zone', nargs='?', default=None,
          help='Availability Zone (default: %(default)s)')
    def list(self, zone=None):
        """Show a list of all physical hosts. Filter by zone.
        args: [zone]
        """
        print(_("%(host)-25s\t%(zone)-15s") % {'host': 'host', 'zone': 'zone'})
        ctxt = context.get_admin_context()
        services = db.service_get_all(ctxt)
        if zone:
            services = [s for s in services if s['availability_zone'] == zone]
        hosts = []
        for srv in services:
            if not [h for h in hosts if h['host'] == srv['host']]:
                hosts.append(srv)

        for h in hosts:
            print(_("%(host)-25s\t%(availability_zone)-15s")
                  % {'host': h['host'],
                     'availability_zone': h['availability_zone']})


class DbCommands(object):
    """Class for managing the database."""

    def __init__(self):
        pass

    @args('version', nargs='?', default=None,
          help='Database version')
    def sync(self, version=None):
        """Sync the database up to the most recent version."""
        return db_migration.db_sync(version)

    def version(self):
        """Print the current database version."""
        print(migration.db_version(db_api.get_engine(),
                                   db_migration.MIGRATE_REPO_PATH,
                                   db_migration.INIT_VERSION))

    @args('age_in_days', type=int,
          help='Purge deleted rows older than age in days')
    def purge(self, age_in_days):
        """Purge deleted rows older than a given age from cinder tables."""
        age_in_days = int(age_in_days)
        if age_in_days <= 0:
            print(_("Must supply a positive, non-zero value for age"))
            exit(1)
        ctxt = context.get_admin_context()
        db.purge_deleted_rows(ctxt, age_in_days)


class VersionCommands(object):
    """Class for exposing the codebase version."""

    def __init__(self):
        pass

    def list(self):
        print(version.version_string())

    def __call__(self):
        self.list()


class VolumeCommands(object):
    """Methods for dealing with a cloud in an odd state."""

    def __init__(self):
        self._client = None

    def rpc_client(self):
        if self._client is None:
            if not rpc.initialized():
                rpc.init(CONF)
                target = messaging.Target(topic=CONF.volume_topic)
                serializer = objects_base.CinderObjectSerializer()
                self._client = rpc.get_client(target, serializer=serializer)

        return self._client

    @args('volume_id',
          help='Volume ID to be deleted')
    def delete(self, volume_id):
        """Delete a volume, bypassing the check that it
        must be available.
        """
        ctxt = context.get_admin_context()
        volume = db.volume_get(ctxt, param2id(volume_id))
        host = volume['host']

        if not host:
            print(_("Volume not yet assigned to host."))
            print(_("Deleting volume from database and skipping rpc."))
            db.volume_destroy(ctxt, param2id(volume_id))
            return

        if volume['status'] == 'in-use':
            print(_("Volume is in-use."))
            print(_("Detach volume from instance and then try again."))
            return

        cctxt = self.rpc_client().prepare(server=host)
        cctxt.cast(ctxt, "delete_volume", volume_id=volume['id'])

    @args('--currenthost', required=True, help='Existing volume host name')
    @args('--newhost', required=True, help='New volume host name')
    def update_host(self, currenthost, newhost):
        """Modify the host name associated with a volume.

        Particularly to recover from cases where one has moved
        their Cinder Volume node, or modified their backend_name in a
        multi-backend config.
        """
        ctxt = context.get_admin_context()
        volumes = db.volume_get_all_by_host(ctxt,
                                            currenthost)
        for v in volumes:
            db.volume_update(ctxt, v['id'],
                             {'host': newhost})


class ConfigCommands(object):
    """Class for exposing the flags defined by flag_file(s)."""

    def __init__(self):
        pass

    @args('param', nargs='?', default=None,
          help='Configuration parameter to display (default: %(default)s)')
    def list(self, param=None):
        """List parameters configured for cinder.

        Lists all parameters configured for cinder unless an optional argument
        is specified.  If the parameter is specified we only print the
        requested parameter.  If the parameter is not found an appropriate
        error is produced by .get*().
        """
        param = param and param.strip()
        if param:
            print('%s = %s' % (param, CONF.get(param)))
        else:
            for key, value in CONF.iteritems():
                print('%s = %s' % (key, value))


class GetLogCommands(object):
    """Get logging information."""

    def errors(self):
        """Get all of the errors from the log files."""
        error_found = 0
        if CONF.log_dir:
            logs = [x for x in os.listdir(CONF.log_dir) if x.endswith('.log')]
            for file in logs:
                log_file = os.path.join(CONF.log_dir, file)
                lines = [line.strip() for line in open(log_file, "r")]
                lines.reverse()
                print_name = 0
                for index, line in enumerate(lines):
                    if line.find(" ERROR ") > 0:
                        error_found += 1
                        if print_name == 0:
                            print(log_file + ":-")
                            print_name = 1
                        print(_("Line %(dis)d : %(line)s") %
                              {'dis': len(lines) - index, 'line': line})
        if error_found == 0:
            print(_("No errors in logfiles!"))

    @args('num_entries', nargs='?', type=int, default=10,
          help='Number of entries to list (default: %(default)d)')
    def syslog(self, num_entries=10):
        """Get <num_entries> of the cinder syslog events."""
        entries = int(num_entries)
        count = 0
        log_file = ''
        if os.path.exists('/var/log/syslog'):
            log_file = '/var/log/syslog'
        elif os.path.exists('/var/log/messages'):
            log_file = '/var/log/messages'
        else:
            print(_("Unable to find system log file!"))
            sys.exit(1)
        lines = [line.strip() for line in open(log_file, "r")]
        lines.reverse()
        print(_("Last %s cinder syslog entries:-") % (entries))
        for line in lines:
            if line.find("cinder") > 0:
                count += 1
                print(_("%s") % (line))
            if count == entries:
                break

        if count == 0:
            print(_("No cinder entries in syslog!"))


class BackupCommands(object):
    """Methods for managing backups."""

    def list(self):
        """List all backups (including ones in progress) and the host
        on which the backup operation is running.
        """
        ctxt = context.get_admin_context()
        backups = db.backup_get_all(ctxt)

        hdr = "%-32s\t%-32s\t%-32s\t%-24s\t%-24s\t%-12s\t%-12s\t%-12s\t%-12s"
        print(hdr % (_('ID'),
                     _('User ID'),
                     _('Project ID'),
                     _('Host'),
                     _('Name'),
                     _('Container'),
                     _('Status'),
                     _('Size'),
                     _('Object Count')))

        res = "%-32s\t%-32s\t%-32s\t%-24s\t%-24s\t%-12s\t%-12s\t%-12d\t%-12d"
        for backup in backups:
            object_count = 0
            if backup['object_count'] is not None:
                object_count = backup['object_count']
            print(res % (backup['id'],
                         backup['user_id'],
                         backup['project_id'],
                         backup['host'],
                         backup['display_name'],
                         backup['container'],
                         backup['status'],
                         backup['size'],
                         object_count))


class ServiceCommands(object):
    """Methods for managing services."""
    def list(self):
        """Show a list of all cinder services."""
        ctxt = context.get_admin_context()
        services = db.service_get_all(ctxt)
        print_format = "%-16s %-36s %-16s %-10s %-5s %-10s"
        print(print_format % (_('Binary'),
                              _('Host'),
                              _('Zone'),
                              _('Status'),
                              _('State'),
                              _('Updated At')))
        for svc in services:
            alive = utils.service_is_up(svc)
            art = ":-)" if alive else "XXX"
            status = 'enabled'
            if svc['disabled']:
                status = 'disabled'
            print(print_format % (svc['binary'], svc['host'].partition('.')[0],
                                  svc['availability_zone'], status, art,
                                  svc['updated_at']))


CATEGORIES = {
    'backup': BackupCommands,
    'config': ConfigCommands,
    'db': DbCommands,
    'host': HostCommands,
    'logs': GetLogCommands,
    'service': ServiceCommands,
    'shell': ShellCommands,
    'version': VersionCommands,
    'volume': VolumeCommands,
}


def methods_of(obj):
    """Get all callable methods of an object that don't start with underscore
    returns a list of tuples of the form (method_name, method)
    """
    result = []
    for i in dir(obj):
        if callable(getattr(obj, i)) and not i.startswith('_'):
            result.append((i, getattr(obj, i)))
    return result


def add_command_parsers(subparsers):
    for category in CATEGORIES:
        command_object = CATEGORIES[category]()

        parser = subparsers.add_parser(category)
        parser.set_defaults(command_object=command_object)

        category_subparsers = parser.add_subparsers(dest='action')

        for (action, action_fn) in methods_of(command_object):
            parser = category_subparsers.add_parser(action)

            action_kwargs = []
            for args, kwargs in getattr(action_fn, 'args', []):
                parser.add_argument(*args, **kwargs)

            parser.set_defaults(action_fn=action_fn)
            parser.set_defaults(action_kwargs=action_kwargs)


category_opt = cfg.SubCommandOpt('category',
                                 title='Command categories',
                                 handler=add_command_parsers)


def get_arg_string(args):
    arg = None
    if args[0] == '-':
        # (Note)zhiteng: args starts with FLAGS.oparser.prefix_chars
        # is optional args. Notice that cfg module takes care of
        # actual ArgParser so prefix_chars is always '-'.
        if args[1] == '-':
            # This is long optional arg
            arg = args[2:]
        else:
            arg = args[3:]
    else:
        arg = args

    return arg


def fetch_func_args(func):
    fn_args = []
    for args, kwargs in getattr(func, 'args', []):
        arg = get_arg_string(args[0])
        fn_args.append(getattr(CONF.category, arg))

    return fn_args


def main():
    """Parse options and call the appropriate class/method."""
    CONF.register_cli_opt(category_opt)
    script_name = sys.argv[0]
    if len(sys.argv) < 2:
        print(_("\nOpenStack Cinder version: %(version)s\n") %
              {'version': version.version_string()})
        print(script_name + " category action [<args>]")
        print(_("Available categories:"))
        for category in CATEGORIES:
            print(_("\t%s") % category)
        sys.exit(2)

    try:
        CONF(sys.argv[1:], project='cinder',
             version=version.version_string())
        logging.setup(CONF, "cinder")
    except cfg.ConfigFilesNotFoundError:
        cfgfile = CONF.config_file[-1] if CONF.config_file else None
        if cfgfile and not os.access(cfgfile, os.R_OK):
            st = os.stat(cfgfile)
            print(_("Could not read %s. Re-running with sudo") % cfgfile)
            try:
                os.execvp('sudo', ['sudo', '-u', '#%s' % st.st_uid] + sys.argv)
            except Exception:
                print(_('sudo failed, continuing as if nothing happened'))

        print(_('Please re-run cinder-manage as root.'))
        sys.exit(2)

    fn = CONF.category.action_fn
    fn_args = fetch_func_args(fn)
    fn(*fn_args)
