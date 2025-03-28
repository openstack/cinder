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


"""CLI interface for cinder management."""

from __future__ import annotations

import collections
import collections.abc as collections_abc
import errno
import glob
import itertools
import logging as python_logging
import os
import re
import sys
import time
import typing
from typing import Any, Callable, Optional, Tuple, Union  # noqa: H301

from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
from oslo_utils import timeutils
import tabulate

# Need to register global_opts
from cinder.backup import rpcapi as backup_rpcapi
from cinder.common import config  # noqa
from cinder import context
from cinder import db
from cinder.db import migration as db_migration
from cinder.db.sqlalchemy import api as db_api
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base as ovo_base
from cinder import quota
from cinder import rpc
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import version
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import volume_utils


CONF = cfg.CONF

LOG = logging.getLogger(__name__)

RPC_VERSIONS = {
    'cinder-scheduler': scheduler_rpcapi.SchedulerAPI.RPC_API_VERSION,
    'cinder-volume': volume_rpcapi.VolumeAPI.RPC_API_VERSION,
    'cinder-backup': backup_rpcapi.BackupAPI.RPC_API_VERSION,
}

OVO_VERSION = ovo_base.OBJ_VERSIONS.get_current()


# Decorators for actions
@typing.no_type_check
def args(*args, **kwargs):
    args = list(args)
    if not args[0].startswith('-') and '-' in args[0]:
        kwargs.setdefault('metavar', args[0])
        args[0] = args[0].replace('-', '_')

    def _decorator(func):
        func.__dict__.setdefault('args', []).insert(0, (args, kwargs))
        return func
    return _decorator


class HostCommands(object):
    """List hosts."""

    @args('zone', nargs='?', default=None,
          help='Availability Zone (default: %(default)s)')
    def list(self, zone: Optional[str] = None) -> None:
        """Show a list of all physical hosts.

        Can be filtered by zone.
        args: [zone]
        """
        print(_("%(host)-25s\t%(zone)-15s") % {'host': 'host', 'zone': 'zone'})
        ctxt = context.get_admin_context()
        services = objects.ServiceList.get_all(ctxt)
        if zone:
            services = [s for s in services if s.availability_zone == zone]
        hosts: list[dict[str, Any]] = []
        for srv in services:
            if not [h for h in hosts if h['host'] == srv['host']]:
                hosts.append(srv)

        for h in hosts:
            print(_("%(host)-25s\t%(availability_zone)-15s")
                  % {'host': h['host'],
                     'availability_zone': h['availability_zone']})


class DbCommands(object):
    """Class for managing the database."""

    # NOTE: Online migrations cannot depend on having Cinder services running.
    # Migrations can be called during Fast-Forward Upgrades without having any
    # Cinder services up.
    # NOTE: Online migrations must be removed at the beginning of the next
    # release to the one they've been introduced.  A comment with the release
    # a migration is introduced and the one where it must be removed must
    # preceed any element of the "online_migrations" tuple, like this:
    #    # Added in Queens remove in Rocky
    #    db.service_uuids_online_data_migration,
    online_migrations: Tuple[Callable[[context.RequestContext, int],
                                      Tuple[int, int]], ...] = (
        # TODO: (Z Release) Remove next line and this comment
        # TODO: (Y Release) Uncomment next line and remove this comment
        # db.remove_temporary_admin_metadata_data_migration,

        # TODO: (Y Release) Remove next 2 line and this comment
        db.volume_use_quota_online_data_migration,
        db.snapshot_use_quota_online_data_migration,
    )

    def __init__(self):
        pass

    @args('version', nargs='?', default=None, type=int,
          help='Database version')
    @args('--bump-versions', dest='bump_versions', default=False,
          action='store_true',
          help='Update RPC and Objects versions when doing offline upgrades, '
               'with this we no longer need to restart the services twice '
               'after the upgrade to prevent ServiceTooOld exceptions.')
    def sync(self,
             version: Optional[int] = None,
             bump_versions: bool = False) -> None:
        """Sync the database up to the most recent version."""
        if version is not None and version > db.MAX_INT:
            print(_('Version should be less than or equal to '
                    '%(max_version)d.') % {'max_version': db.MAX_INT})
            sys.exit(1)
        try:
            db_migration.db_sync(version)
        except db_exc.DBMigrationError as ex:
            print("Error during database migration: %s" % ex)
            sys.exit(1)

        try:
            if bump_versions:
                ctxt = context.get_admin_context()
                services = objects.ServiceList.get_all(ctxt)
                for service in services:
                    rpc_version = RPC_VERSIONS[service.binary]
                    if (service.rpc_current_version != rpc_version or
                            service.object_current_version != OVO_VERSION):
                        service.rpc_current_version = rpc_version
                        service.object_current_version = OVO_VERSION
                        service.save()
        except Exception as ex:
            print(_('Error during service version bump: %s') % ex)
            sys.exit(2)

    def version(self) -> None:
        """Print the current database version."""
        print(db_migration.db_version())

    @args('age_in_days', type=int,
          help='Purge deleted rows older than age in days')
    def purge(self, age_in_days: int) -> None:
        """Purge deleted rows older than a given age from cinder tables."""
        age_in_days = int(age_in_days)
        if age_in_days < 0:
            print(_("Must supply a positive value for age"))
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

    def _run_migration(self,
                       ctxt: context.RequestContext,
                       max_count: int) -> Tuple[dict, bool]:
        ran = 0
        exceptions = False
        migrations = {}
        for migration_meth in self.online_migrations:
            count = max_count - ran
            try:
                found, done = migration_meth(ctxt, count)
            except Exception:
                msg = (_("Error attempting to run %(method)s") %
                       {'method': migration_meth.__name__})
                print(msg)
                LOG.exception(msg)
                exceptions = True
                found = done = 0

            name = migration_meth.__name__
            if found:
                print(_('%(found)i rows matched query %(meth)s, %(done)i '
                        'migrated') % {'found': found,
                                       'meth': name,
                                       'done': done})
            migrations[name] = found, done
            if max_count is not None:
                ran += done
                if ran >= max_count:
                    break
        return migrations, exceptions

    @args('--max_count', metavar='<number>', dest='max_count', type=int,
          help='Maximum number of objects to consider.')
    def online_data_migrations(self, max_count: Optional[int] = None) -> None:
        """Perform online data migrations for the release in batches."""
        ctxt = context.get_admin_context()
        if max_count is not None:
            unlimited = False
            if max_count < 1:
                print(_('Must supply a positive value for max_count.'))
                sys.exit(127)
        else:
            unlimited = True
            max_count = 50
            print(_('Running batches of %i until complete.') % max_count)

        ran = None
        exceptions = False
        migration_info: dict[str, Any] = {}
        while ran is None or ran != 0:
            migrations, exceptions = self._run_migration(ctxt, max_count)
            ran = 0
            for name in migrations:
                migration_info.setdefault(name, (0, 0))
                migration_info[name] = (
                    max(migration_info[name][0], migrations[name][0]),
                    migration_info[name][1] + migrations[name][1],
                )
                ran += migrations[name][1]
            if not unlimited:
                break
        headers = ["{}".format(_('Migration')),
                   "{}".format(_('Total Needed')),
                   "{}".format(_('Completed')), ]
        rows = []
        for name in sorted(migration_info.keys()):
            info = migration_info[name]
            rows.append([name, info[0], info[1]])
        print(tabulate.tabulate(rows, headers=headers, tablefmt='psql'))

        # NOTE(imacdonn): In the "unlimited" case, the loop above will only
        # terminate when all possible migrations have been effected. If we're
        # still getting exceptions, there's a problem that requires
        # intervention. In the max-count case, exceptions are only considered
        # fatal if no work was done by any other migrations ("not ran"),
        # because otherwise work may still remain to be done, and that work
        # may resolve dependencies for the failing migrations.
        if exceptions and (unlimited or not ran):
            print(_("Some migrations failed unexpectedly. Check log for "
                    "details."))
            sys.exit(2)

        sys.exit(1 if ran else 0)

    @args('--enable-replication', action='store_true', default=False,
          help='Set replication status to enabled (default: %(default)s).')
    @args('--active-backend-id', default=None,
          help='Change the active backend ID (default: %(default)s).')
    @args('--backend-host', required=True,
          help='The backend host name.')
    def reset_active_backend(self,
                             enable_replication: bool,
                             active_backend_id: Optional[str],
                             backend_host: str) -> None:
        """Reset the active backend for a host."""

        ctxt = context.get_admin_context()

        try:
            db.reset_active_backend(ctxt, enable_replication,
                                    active_backend_id, backend_host)
        except db_exc.DBReferenceError:
            print(_("Failed to reset active backend for host %s, "
                    "check cinder-manage logs for more details.") %
                  backend_host)
            sys.exit(1)


class QuotaCommands(object):
    """Class for managing quota issues."""

    def __init__(self):
        pass

    @args('--project-id', default=None,
          help=('The ID of the project where we want to sync the quotas '
                '(defaults to all projects).'))
    def check(self, project_id: Optional[str]) -> None:
        """Check if quotas and reservations are correct

        This action checks quotas and reservations, for a specific project or
        for all projects, to see if they are out of sync.

        The check will also look for duplicated entries.

        One way to use this check in combination with the sync action is to
        run the check for all projects, take note of those that are out of
        sync, and then sync them one by one at intervals to reduce stress on
        the DB.
        """
        result = self._check_sync(project_id, do_fix=False)
        if result:
            sys.exit(1)

    @args('--project-id', default=None,
          help=('The ID of the project where we want to sync the quotas '
                '(defaults to all projects).'))
    def sync(self, project_id: Optional[str]) -> None:
        """Fix quotas and reservations

        This action refreshes existing quota usage and reservation count for a
        specific project or for all projects.

        The refresh will also remove duplicated entries.

        This operation is best executed when Cinder is not running, but it can
        be run with cinder services running as well.

        A different transaction is used for each project's quota sync, so an
        action failure will only rollback the current project's changes.
        """
        self._check_sync(project_id, do_fix=True)

    @db_api.main_context_manager.reader
    def _get_quota_projects(self,
                            context: context.RequestContext,
                            project_id: Optional[str]) -> list[str]:
        """Get project ids that have quota_usage entries."""
        if project_id:
            model = models.QuotaUsage
            # If the project does not exist
            if not context.session.query(
                db_api.sql.exists()
                .where(
                    db_api.and_(
                        model.project_id == project_id,
                        ~model.deleted,
                    ),
                )
            ).scalar():
                print(
                    'Project id %s has no quota usage. Nothing to do.' %
                    project_id,
                )
                return []
            return [project_id]

        projects = db_api.model_query(
            context,
            models.QuotaUsage,
            read_deleted="no"
        ).with_entities('project_id').distinct().all()
        project_ids = [row.project_id for row in projects]
        return project_ids

    def _get_usages(self,
                    ctxt: context.RequestContext,
                    resources,
                    project_id: str) -> list:
        """Get data necessary to check out of sync quota usage.

        Returns a list QuotaUsage instances for the specific project
        """
        usages = db_api.model_query(
            context,
            db_api.models.QuotaUsage,
            read_deleted="no",
        ).filter_by(project_id=project_id).with_for_update().all()
        return usages

    def _get_reservations(self,
                          ctxt: context.RequestContext,
                          project_id: str,
                          usage_id: str) -> list:
        """Get reservations for a given project and usage id."""
        reservations = (
            db_api.model_query(
                context,
                models.Reservation,
                read_deleted="no",
            )
            .filter_by(project_id=project_id, usage_id=usage_id)
            .with_for_update()
            .all()
        )
        return reservations

    def _check_duplicates(self,
                          context: context.RequestContext,
                          usages,
                          do_fix: bool) -> tuple[list, bool]:
        """Look for duplicated quota used entries (bug#1484343)

        If we have duplicates and we are fixing them, then we reassign the
        reservations of the usage we are removing.
        """
        resources = collections.defaultdict(list)
        for usage in usages:
            resources[usage.resource].append(usage)

        duplicates_found = False
        result = []
        for resource_usages in resources.values():
            keep_usage = resource_usages[0]
            if len(resource_usages) > 1:
                duplicates_found = True
                print('\t%s: %s duplicated usage entries - ' %
                      (keep_usage.resource, len(resource_usages) - 1),
                      end='')

                if do_fix:
                    # Each of the duplicates can have reservations
                    reassigned = 0
                    for usage in resource_usages[1:]:
                        reservations = self._get_reservations(
                            context,
                            usage.project_id,
                            usage.id,
                        )
                        reassigned += len(reservations)
                        for reservation in reservations:
                            reservation.usage_id = keep_usage.id
                        keep_usage.in_use += usage.in_use
                        keep_usage.reserved += usage.reserved
                        usage.delete(context.session)
                    print('duplicates removed & %s reservations reassigned' %
                          reassigned)
                else:
                    print('ignored')
            result.append(keep_usage)
        return result, duplicates_found

    def _check_sync(self, project_id: Optional[str], do_fix: bool) -> bool:
        """Check the quotas and reservations optionally fixing them."""

        ctxt = context.get_admin_context()
        # Get the quota usage types and their sync methods
        resources = quota.QUOTAS.resources

        # Get all project ids that have quota usage. Method doesn't lock
        # projects, since newly added projects should not be out of sync and
        # projects removed will just turn nothing on the quota usage.
        projects = self._get_quota_projects(ctxt, project_id)

        discrepancy = False

        for project in projects:
            discrepancy &= self._check_project_sync(
                ctxt,
                project,
                do_fix,
                resources,
            )

        print('Action successfully completed')
        return discrepancy

    @db_api.main_context_manager.reader
    def _check_project_sync(self,
                            context: context.RequestContext,
                            project: str,
                            do_fix: bool,
                            resources) -> bool:
        print('Processing quota usage for project %s' % project)

        discrepancy = False
        action_msg = ' - fixed' if do_fix else ''

        # NOTE: It's important to always get the quota first and then the
        # reservations to prevent deadlocks with quota commit and rollback from
        # running Cinder services.

        # We only want to sync existing quota usage rows
        usages = self._get_usages(context, resources, project)

        # Check for duplicated entries (bug#1484343)
        usages, duplicates_found = self._check_duplicates(
            context, usages, do_fix,
        )
        if duplicates_found:
            discrepancy = True

        # Check quota and reservations
        for usage in usages:
            resource_name = usage.resource
            # Get the correct value for this quota usage resource
            updates = db_api._get_sync_updates(
                context,
                project,
                resources,
                resource_name,
            )
            in_use = updates[resource_name]
            if in_use != usage.in_use:
                print(
                    '\t%s: invalid usage saved=%s actual=%s%s' %
                    (resource_name, usage.in_use, in_use, action_msg)
                )
                discrepancy = True
                if do_fix:
                    usage.in_use = in_use

            reservations = self._get_reservations(
                context,
                project,
                usage.id,
            )
            num_reservations = sum(
                r.delta for r in reservations if r.delta > 0
            )
            if num_reservations != usage.reserved:
                print(
                    '\t%s: invalid reserved saved=%s actual=%s%s' %
                    (
                        resource_name,
                        usage.reserved,
                        num_reservations,
                        action_msg,
                    )
                )
                discrepancy = True
                if do_fix:
                    usage.reserved = num_reservations

        return discrepancy


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

    @args('volume_id',
          help='Volume ID to be deleted')
    def delete(self, volume_id: str) -> None:
        """Delete a volume, bypassing the check that it must be available."""
        ctxt = context.get_admin_context()
        volume = objects.Volume.get_by_id(ctxt, volume_id)
        host = volume_utils.extract_host(volume.host) if volume.host else None

        if not host:
            print(_("Volume not yet assigned to host."))
            print(_("Deleting volume from database and skipping rpc."))
            volume.destroy()
            return

        if volume.status == 'in-use':
            print(_("Volume is in-use."))
            print(_("Detach volume from instance and then try again."))
            return

        rpc.init(CONF)
        rpcapi = volume_rpcapi.VolumeAPI()
        rpcapi.delete_volume(ctxt, volume)

    @args('--currenthost', required=True, help='Existing volume host name in '
                                               'the format host@backend#pool')
    @args('--newhost', required=True, help='New volume host name in the '
                                           'format host@backend#pool')
    def update_host(self, currenthost: str, newhost: str) -> None:
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

    def update_service(self):
        """Modify the service uuid associated with a volume.

        In certain upgrade cases, we create new cinder services and delete the
        records of old ones, however, the volumes created with old service
        still contain the service uuid of the old services.
        """
        ctxt = context.get_admin_context()
        db.volume_update_all_by_service(ctxt)


class ConfigCommands(object):
    """Class for exposing the flags defined by flag_file(s)."""

    def __init__(self):
        pass

    @args('param', nargs='?', default=None,
          help='Configuration parameter to display (default: %(default)s)')
    def list(self, param: Optional[str] = None) -> None:
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


class BackupCommands(object):
    """Methods for managing backups."""

    def list(self) -> None:
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
    def update_backup_host(self, currenthost: str, newhost: str) -> None:
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
            print(print_format % (svc.binary, svc.host,
                                  svc.availability_zone, status, art,
                                  updated_at, rpc_version, object_version,
                                  cluster))

    @args('binary', type=str,
          help='Service to delete from the host.')
    @args('host_name', type=str,
          help='Host from which to remove the service.')
    def remove(self, binary: str, host_name: str) -> Optional[int]:
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

        return None


class ClusterCommands(BaseCommand):
    """Methods for managing clusters."""
    def list(self) -> None:
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
    def remove(self,
               recursive: bool,
               binary: str,
               cluster_name: str) -> Optional[int]:
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

        return None

    @args('--full-rename', dest='partial',
          action='store_false', default=True,
          help='Do full cluster rename instead of just replacing provided '
               'current cluster name and preserving backend and/or pool info.')
    @args('current', help='Current cluster name.')
    @args('new', help='New cluster name.')
    def rename(self,
               partial: bool,
               current: Optional[str],
               new: Optional[str]) -> Optional[int]:
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

        return None


class ConsistencyGroupCommands(object):
    """Methods for managing consistency groups."""

    @args('--currenthost', required=True, help='Existing CG host name')
    @args('--newhost', required=True, help='New CG host name')
    def update_cg_host(self, currenthost: str, newhost: str) -> None:
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


class UtilCommands(object):
    """Generic utils."""

    @staticmethod
    def _get_resources_locks() -> Tuple[collections.defaultdict,
                                        collections.defaultdict,
                                        collections.defaultdict]:
        """Get all vol/snap/backup file lock paths."""
        backup_locks_prefix = 'cinder-cleanup_incomplete_backups_'
        oslo_dir = os.path.abspath(cfg.CONF.oslo_concurrency.lock_path)
        filenames = glob.glob(os.path.join(oslo_dir, 'cinder-*'))

        backend_url = cfg.CONF.coordination.backend_url
        if backend_url.startswith('file://'):
            tooz_dir = os.path.abspath(backend_url[7:])
            if tooz_dir != oslo_dir:
                filenames += glob.glob(os.path.join(tooz_dir, 'cinder-*'))

        volumes: collections.defaultdict = collections.defaultdict(list)
        snapshots: collections.defaultdict = collections.defaultdict(list)
        backups = collections.defaultdict(list)
        matcher = re.compile('.*?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
                             '[0-9a-f]{4}-[0-9a-f]{12}).*?', re.IGNORECASE)
        for filename in filenames:
            basename = os.path.basename(filename)
            match = matcher.match(basename)
            if match:
                dest = snapshots if 'snapshot' in basename else volumes
                res_id = match.group(1)
                dest[res_id].append(filename)
            elif basename.startswith(backup_locks_prefix):
                pgrp = basename[34:]
                backups[pgrp].append(filename)

        return volumes, snapshots, backups

    def _exclude_running_backups(self, backups: dict) -> None:
        """Remove backup entries from the dict for running backup services."""
        for backup_pgrp in list(backups.keys()):
            # The PGRP is the same as the PID of the parent process, so we know
            # the lock could be in use if the process is running and it's the
            # cinder-backup command (the PID could have been reused).
            cmdline_file = os.path.join('/proc', backup_pgrp, 'cmdline')
            try:
                with open(cmdline_file, 'r') as f:
                    if 'cinder-backup' in f.read():
                        del backups[backup_pgrp]
            except FileNotFoundError:
                continue
            except Exception:
                # Unexpected error, leaving the lock file just in case
                del backups[backup_pgrp]

    @args('--services-offline', dest='online',
          action='store_false', default=True,
          help='All locks can be deleted as Cinder services are not running.')
    def clean_locks(self, online: bool) -> None:
        """Clean file locks for vols, snaps, and backups on the current host.

        Should be run on any host where we are running a Cinder service (API,
        Scheduler, Volume, Backup) and can be run with the Cinder services
        running or stopped.

        If the services are running it will check existing resources in the
        Cinder database in order to know which resources are still available
        (it's not safe to remove their file locks) and will only remove the
        file locks for the resources that are no longer present.  Deleting
        locks while the services are offline is faster as there's no need to
        check the database.

        For backups, the way to know if we can remove the startup lock is by
        checking if the PGRP in the file name is currently running
        cinder-backup.

        Default assumes that services are online, must pass
        ``--services-offline`` to specify that they are offline.

        Doesn't clean DLM locks (except when using file locks), as those don't
        leave lock leftovers.
        """
        self.ctxt = context.get_admin_context()
        # Find volume and snapshots ids, and backups PGRP based on the existing
        # file locks
        volumes: Union[collections.defaultdict, dict]
        snapshots: Union[collections.defaultdict, dict]
        volumes, snapshots, backups = self._get_resources_locks()

        # If services are online we cannot delete locks for existing resources
        if online:
            # We don't want to delete file locks for existing resources
            volumes = {vol_id: files for vol_id, files in volumes.items()
                       if not objects.Volume.exists(self.ctxt, vol_id)}
            snapshots = {snap_id: files for snap_id, files in snapshots.items()
                         if not objects.Snapshot.exists(self.ctxt, snap_id)}
            self._exclude_running_backups(backups)

        def _err(filename: str, exc: Exception) -> None:
            print('Failed to cleanup lock %(name)s: %(exc)s',
                  {'name': filename, 'exc': exc})

        # Now clean
        for filenames in itertools.chain(volumes.values(),
                                         snapshots.values(),
                                         backups.values()):
            for filename in filenames:
                try:
                    os.remove(filename)
                except OSError as exc:
                    if (exc.errno != errno.ENOENT):
                        _err(filename, exc)
                except Exception as exc:
                    _err(filename, exc)


CATEGORIES = {
    'backup': BackupCommands,
    'config': ConfigCommands,
    'cluster': ClusterCommands,
    'cg': ConsistencyGroupCommands,
    'db': DbCommands,
    'host': HostCommands,
    'quota': QuotaCommands,
    'service': ServiceCommands,
    'version': VersionCommands,
    'volume': VolumeCommands,
    'util': UtilCommands,
}


def methods_of(obj) -> list:
    """Return non-private methods from an object.

    Get all callable methods of an object that don't start with underscore
    :return: a list of tuples of the form (method_name, method)
    """
    result = []
    for i in dir(obj):
        if (isinstance(getattr(obj, i),
                       collections_abc.Callable) and  # type: ignore
                not i.startswith('_')):
            result.append((i, getattr(obj, i)))
    return result


def missing_action(help_func: Callable) -> Callable:
    def wrapped():
        help_func()
        exit(2)
    return wrapped


def add_command_parsers(subparsers):
    for category in sorted(CATEGORIES):
        command_object = CATEGORIES[category]()

        parser = subparsers.add_parser(category)
        parser.set_defaults(command_object=command_object)
        parser.set_defaults(action_fn=missing_action(parser.print_help))

        category_subparsers = parser.add_subparsers(dest='action')

        for (action, action_fn) in methods_of(command_object):
            parser = category_subparsers.add_parser(action)

            action_kwargs: list = []
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
            args = args[1:]  # pylint: disable=E1136

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
