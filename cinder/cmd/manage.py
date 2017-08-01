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


import logging as python_logging
import os
import prettytable
import sys
import time

from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_db.sqlalchemy import migration
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import timeutils

# Need to register global_opts
from cinder.common import config  # noqa
from cinder.common import constants
from cinder import context
from cinder import db
from cinder.db import migration as db_migration
from cinder.db.sqlalchemy import api as db_api
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder import rpc
from cinder import version
from cinder.volume import utils as vutils


CONF = cfg.CONF


# Decorators for actions
def args(*args, **kwargs):
    def _decorator(func):
        func.__dict__.setdefault('args', []).insert(0, (args, kwargs))
        return func
    return _decorator


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

    @args('--shell',
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
        """Runs the script from the specified path with flags set properly."""
        exec(compile(open(path).read(), path, 'exec'), locals(), globals())


def _db_error(caught_exception):
    print('%s' % caught_exception)
    print(_("The above error may show that the database has not "
            "been created.\nPlease create a database using "
            "'cinder-manage db sync' before running this command."))
    sys.exit(1)


class HostCommands(object):
    """List hosts."""

    @args('zone', nargs='?', default=None,
          help='Availability Zone (default: %(default)s)')
    def list(self, zone=None):
        """Show a list of all physical hosts.

        Can be filtered by zone.
        args: [zone]
        """
        print(_("%(host)-25s\t%(zone)-15s") % {'host': 'host', 'zone': 'zone'})
        ctxt = context.get_admin_context()
        services = objects.ServiceList.get_all(ctxt)
        if zone:
            services = [s for s in services if s.availability_zone == zone]
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

    online_migrations = ()

    def __init__(self):
        pass

    @args('version', nargs='?', default=None, type=int,
          help='Database version')
    def sync(self, version=None):
        """Sync the database up to the most recent version."""
        if version is not None and version > db.MAX_INT:
            print(_('Version should be less than or equal to '
                    '%(max_version)d.') % {'max_version': db.MAX_INT})
            sys.exit(1)
        try:
            return db_migration.db_sync(version)
        except db_exc.DbMigrationError as ex:
            print("Error during database migration: %s" % ex)
            sys.exit(1)

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
            sys.exit(1)
        if age_in_days >= (int(time.time()) / 86400):
            print(_("Maximum age is count of days since epoch."))
            sys.exit(1)
        ctxt = context.get_admin_context()

        try:
            db.purge_deleted_rows(ctxt, age_in_days)
        except db_exc.DBReferenceError:
            print(_("Purge command failed, check cinder-manage "
                    "logs for more details."))
            sys.exit(1)

    def _run_migration(self, ctxt, max_count, ignore_state):
        ran = 0
        migrations = {}
        for migration_meth in self.online_migrations:
            count = max_count - ran
            try:
                found, done = migration_meth(ctxt, count, ignore_state)
            except Exception:
                print(_("Error attempting to run %(method)s") %
                      {'method': migration_meth.__name__})
                found = done = 0

            name = migration_meth.__name__
            remaining = found - done
            if found:
                print(_('%(found)i rows matched query %(meth)s, %(done)i '
                        'migrated, %(remaining)i remaining') % {'found': found,
                                                                'meth': name,
                                                                'done': done,
                                                                'remaining':
                                                                remaining})
            migrations.setdefault(name, (0, 0, 0))
            migrations[name] = (migrations[name][0] + found,
                                migrations[name][1] + done,
                                migrations[name][2] + remaining)
            if max_count is not None:
                ran += done
                if ran >= max_count:
                    break
        return migrations

    @args('--max_count', metavar='<number>', dest='max_count', type=int,
          help='Maximum number of objects to consider.')
    @args('--ignore_state', action='store_true', dest='ignore_state',
          help='Force records to migrate even if another operation is '
               'performed on them. This may be dangerous, please refer to '
               'release notes for more information.')
    def online_data_migrations(self, max_count=None, ignore_state=False):
        """Perform online data migrations for the release in batches."""
        ctxt = context.get_admin_context()
        if max_count is not None:
            unlimited = False
            if max_count < 1:
                print(_('Must supply a positive value for max_number.'))
                sys.exit(127)
        else:
            unlimited = True
            max_count = 50
            print(_('Running batches of %i until complete.') % max_count)

        ran = None
        migration_info = {}
        while ran is None or ran != 0:
            migrations = self._run_migration(ctxt, max_count, ignore_state)
            migration_info.update(migrations)
            ran = sum([done for found, done, remaining in migrations.values()])
            if not unlimited:
                break

        t = prettytable.PrettyTable([_('Migration'),
                                     _('Found'),
                                     _('Done'),
                                     _('Remaining')])
        for name in sorted(migration_info.keys()):
            info = migration_info[name]
            t.add_row([name, info[0], info[1], info[2]])
        print(t)

        sys.exit(1 if ran else 0)


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

    def _rpc_client(self):
        if self._client is None:
            if not rpc.initialized():
                rpc.init(CONF)
                target = messaging.Target(topic=constants.VOLUME_TOPIC)
                serializer = objects.base.CinderObjectSerializer()
                self._client = rpc.get_client(target, serializer=serializer)

        return self._client

    @args('volume_id',
          help='Volume ID to be deleted')
    def delete(self, volume_id):
        """Delete a volume, bypassing the check that it must be available."""
        ctxt = context.get_admin_context()
        volume = objects.Volume.get_by_id(ctxt, volume_id)
        host = vutils.extract_host(volume.host) if volume.host else None

        if not host:
            print(_("Volume not yet assigned to host."))
            print(_("Deleting volume from database and skipping rpc."))
            volume.destroy()
            return

        if volume.status == 'in-use':
            print(_("Volume is in-use."))
            print(_("Detach volume from instance and then try again."))
            return

        cctxt = self._rpc_client().prepare(server=host)
        cctxt.cast(ctxt, "delete_volume", volume_id=volume.id, volume=volume)

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
            for key, value in CONF.items():
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
        """List all backups.

        List all backups (including ones in progress) and the host
        on which the backup operation is running.
        """
        ctxt = context.get_admin_context()
        backups = objects.BackupList.get_all(ctxt)

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

    @args('--currenthost', required=True, help='Existing backup host name')
    @args('--newhost', required=True, help='New backup host name')
    def update_backup_host(self, currenthost, newhost):
        """Modify the host name associated with a backup.

        Particularly to recover from cases where one has moved
        their Cinder Backup node, and not set backup_use_same_backend.
        """
        ctxt = context.get_admin_context()
        backups = objects.BackupList.get_all_by_host(ctxt, currenthost)
        for bk in backups:
            bk.host = newhost
            bk.save()


class BaseCommand(object):
    @staticmethod
    def _normalize_time(time_field):
        return time_field and timeutils.normalize_time(time_field)

    @staticmethod
    def _state_repr(is_up):
        return ':-)' if is_up else 'XXX'


class ServiceCommands(BaseCommand):
    """Methods for managing services."""
    def list(self):
        """Show a list of all cinder services."""
        ctxt = context.get_admin_context()
        services = objects.ServiceList.get_all(ctxt)
        print_format = "%-16s %-36s %-16s %-10s %-5s %-20s %-12s %-15s %-36s"
        print(print_format % (_('Binary'),
                              _('Host'),
                              _('Zone'),
                              _('Status'),
                              _('State'),
                              _('Updated At'),
                              _('RPC Version'),
                              _('Object Version'),
                              _('Cluster')))
        for svc in services:
            art = self._state_repr(svc.is_up)
            status = 'disabled' if svc.disabled else 'enabled'
            updated_at = self._normalize_time(svc.updated_at)
            rpc_version = svc.rpc_current_version
            object_version = svc.object_current_version
            cluster = svc.cluster_name or ''
            print(print_format % (svc.binary, svc.host.partition('.')[0],
                                  svc.availability_zone, status, art,
                                  updated_at, rpc_version, object_version,
                                  cluster))

    @args('binary', type=str,
          help='Service to delete from the host.')
    @args('host_name', type=str,
          help='Host from which to remove the service.')
    def remove(self, binary, host_name):
        """Completely removes a service."""
        ctxt = context.get_admin_context()
        try:
            svc = objects.Service.get_by_args(ctxt, host_name, binary)
            svc.destroy()
        except exception.ServiceNotFound as e:
            print(_("Host not found. Failed to remove %(service)s"
                    " on %(host)s.") %
                  {'service': binary, 'host': host_name})
            print(u"%s" % e.args)
            return 2
        print(_("Service %(service)s on host %(host)s removed.") %
              {'service': binary, 'host': host_name})


class ClusterCommands(BaseCommand):
    """Methods for managing clusters."""
    def list(self):
        """Show a list of all cinder services."""
        ctxt = context.get_admin_context()
        clusters = objects.ClusterList.get_all(ctxt, services_summary=True)
        print_format = "%-36s %-16s %-10s %-5s %-20s %-7s %-12s %-20s"
        print(print_format % (_('Name'),
                              _('Binary'),
                              _('Status'),
                              _('State'),
                              _('Heartbeat'),
                              _('Hosts'),
                              _('Down Hosts'),
                              _('Updated At')))
        for cluster in clusters:
            art = self._state_repr(cluster.is_up)
            status = 'disabled' if cluster.disabled else 'enabled'
            heartbeat = self._normalize_time(cluster.last_heartbeat)
            updated_at = self._normalize_time(cluster.updated_at)
            print(print_format % (cluster.name, cluster.binary, status, art,
                                  heartbeat, cluster.num_hosts,
                                  cluster.num_down_hosts, updated_at))

    @args('--recursive', action='store_true', default=False,
          help='Delete associated hosts.')
    @args('binary', type=str,
          help='Service to delete from the cluster.')
    @args('cluster-name', type=str, help='Cluster to delete.')
    def remove(self, recursive, binary, cluster_name):
        """Completely removes a cluster."""
        ctxt = context.get_admin_context()
        try:
            cluster = objects.Cluster.get_by_id(ctxt, None, name=cluster_name,
                                                binary=binary,
                                                get_services=recursive)
        except exception.ClusterNotFound:
            print(_("Couldn't remove cluster %s because it doesn't exist.") %
                  cluster_name)
            return 2

        if recursive:
            for service in cluster.services:
                service.destroy()

        try:
            cluster.destroy()
        except exception.ClusterHasHosts:
            print(_("Couldn't remove cluster %s because it still has hosts.") %
                  cluster_name)
            return 2

        msg = _('Cluster %s successfully removed.') % cluster_name
        if recursive:
            msg = (_('%(msg)s And %(num)s services from the cluster were also '
                     'removed.') % {'msg': msg, 'num': len(cluster.services)})
        print(msg)

    @args('--full-rename', dest='partial',
          action='store_false', default=True,
          help='Do full cluster rename instead of just replacing provided '
               'current cluster name and preserving backend and/or pool info.')
    @args('current', help='Current cluster name.')
    @args('new', help='New cluster name.')
    def rename(self, partial, current, new):
        """Rename cluster name for Volumes and Consistency Groups.

        Useful when you want to rename a cluster, particularly when the
        backend_name has been modified in a multi-backend config or we have
        moved from a single backend to multi-backend.
        """
        ctxt = context.get_admin_context()

        # Convert empty strings to None
        current = current or None
        new = new or None

        # Update Volumes
        num_vols = objects.VolumeList.include_in_cluster(
            ctxt, new, partial_rename=partial, cluster_name=current)

        # Update Consistency Groups
        num_cgs = objects.ConsistencyGroupList.include_in_cluster(
            ctxt, new, partial_rename=partial, cluster_name=current)

        if num_vols or num_cgs:
            msg = _('Successfully renamed %(num_vols)s volumes and '
                    '%(num_cgs)s consistency groups from cluster %(current)s '
                    'to %(new)s')
            print(msg % {'num_vols': num_vols, 'num_cgs': num_cgs, 'new': new,
                         'current': current})
        else:
            msg = _('No volumes or consistency groups exist in cluster '
                    '%(current)s.')
            print(msg % {'current': current})
            return 2


class ConsistencyGroupCommands(object):
    """Methods for managing consistency groups."""

    @args('--currenthost', required=True, help='Existing CG host name')
    @args('--newhost', required=True, help='New CG host name')
    def update_cg_host(self, currenthost, newhost):
        """Modify the host name associated with a Consistency Group.

        Particularly to recover from cases where one has moved
        a host from single backend to multi-backend, or changed the host
        configuration option, or modified the backend_name in a multi-backend
        config.
        """

        ctxt = context.get_admin_context()
        groups = objects.ConsistencyGroupList.get_all(
            ctxt, {'host': currenthost})
        for gr in groups:
            gr.host = newhost
            gr.save()


CATEGORIES = {
    'backup': BackupCommands,
    'config': ConfigCommands,
    'cluster': ClusterCommands,
    'cg': ConsistencyGroupCommands,
    'db': DbCommands,
    'host': HostCommands,
    'logs': GetLogCommands,
    'service': ServiceCommands,
    'shell': ShellCommands,
    'version': VersionCommands,
    'volume': VolumeCommands,
}


def methods_of(obj):
    """Return non-private methods from an object.

    Get all callable methods of an object that don't start with underscore
    :return: a list of tuples of the form (method_name, method)
    """
    result = []
    for i in dir(obj):
        if callable(getattr(obj, i)) and not i.startswith('_'):
            result.append((i, getattr(obj, i)))
    return result


def add_command_parsers(subparsers):
    for category in sorted(CATEGORIES):
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
    if args[0] == '-':
        # (Note)zhiteng: args starts with FLAGS.oparser.prefix_chars
        # is optional args. Notice that cfg module takes care of
        # actual ArgParser so prefix_chars is always '-'.
        if args[1] == '-':
            # This is long optional arg
            args = args[2:]
        else:
            args = args[1:]

    # We convert dashes to underscores so we can have cleaner optional arg
    # names
    if args:
        args = args.replace('-', '_')

    return args


def fetch_func_args(func):
    fn_kwargs = {}
    for args, kwargs in getattr(func, 'args', []):
        # Argparser `dest` configuration option takes precedence for the name
        arg = kwargs.get('dest') or get_arg_string(args[0])
        fn_kwargs[arg] = getattr(CONF.category, arg)

    return fn_kwargs


def main():
    objects.register_all()
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
        python_logging.captureWarnings(True)
    except cfg.ConfigDirNotFoundError as details:
        print(_("Invalid directory: %s") % details)
        sys.exit(2)
    except cfg.ConfigFilesNotFoundError as e:
        cfg_files = e.config_files
        print(_("Failed to read configuration file(s): %s") % cfg_files)
        sys.exit(2)

    fn = CONF.category.action_fn
    fn_kwargs = fetch_func_args(fn)
    fn(**fn_kwargs)
