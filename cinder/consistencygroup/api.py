# Copyright (C) 2012 - 2014 EMC Corporation.
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

"""
Handles all requests relating to consistency groups.
"""


import functools

from oslo.config import cfg

from cinder.db import base
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
import cinder.policy
from cinder import quota
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder.volume import api as volume_api
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import volume_types


CONF = cfg.CONF
CONF.import_opt('storage_availability_zone', 'cinder.volume.manager')

LOG = logging.getLogger(__name__)
CGQUOTAS = quota.CGQUOTAS


def wrap_check_policy(func):
    """Check policy corresponding to the wrapped methods prior to execution.

    This decorator requires the first 3 args of the wrapped function
    to be (self, context, consistencygroup)
    """
    @functools.wraps(func)
    def wrapped(self, context, target_obj, *args, **kwargs):
        check_policy(context, func.__name__, target_obj)
        return func(self, context, target_obj, *args, **kwargs)

    return wrapped


def check_policy(context, action, target_obj=None):
    target = {
        'project_id': context.project_id,
        'user_id': context.user_id,
    }
    target.update(target_obj or {})
    _action = 'consistencygroup:%s' % action
    cinder.policy.enforce(context, _action, target)


class API(base.Base):
    """API for interacting with the volume manager for consistency groups."""

    def __init__(self, db_driver=None):
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()
        self.volume_rpcapi = volume_rpcapi.VolumeAPI()
        self.availability_zone_names = ()
        self.volume_api = volume_api.API()

        super(API, self).__init__(db_driver)

    def _valid_availability_zone(self, availability_zone):
        if availability_zone in self.availability_zone_names:
            return True
        if CONF.storage_availability_zone == availability_zone:
            return True
        azs = self.volume_api.list_availability_zones()
        self.availability_zone_names = [az['name'] for az in azs]
        return availability_zone in self.availability_zone_names

    def _extract_availability_zone(self, availability_zone):
        if availability_zone is None:
            if CONF.default_availability_zone:
                availability_zone = CONF.default_availability_zone
            else:
                # For backwards compatibility use the storage_availability_zone
                availability_zone = CONF.storage_availability_zone

        valid = self._valid_availability_zone(availability_zone)
        if not valid:
            msg = _("Availability zone '%s' is invalid") % (availability_zone)
            LOG.warn(msg)
            raise exception.InvalidInput(reason=msg)

        return availability_zone

    def create(self, context, name, description,
               cg_volume_types, availability_zone=None):

        check_policy(context, 'create')
        volume_type_list = None
        volume_type_list = cg_volume_types.split(',')

        req_volume_types = []
        req_volume_types = (self.db.volume_types_get_by_name_or_id(
            context, volume_type_list))

        req_volume_type_ids = ""
        for voltype in req_volume_types:
            req_volume_type_ids = (
                req_volume_type_ids + voltype.get('id') + ",")
        if len(req_volume_type_ids) == 0:
            req_volume_type_ids = None

        availability_zone = self._extract_availability_zone(availability_zone)

        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'availability_zone': availability_zone,
                   'status': "creating",
                   'name': name,
                   'description': description,
                   'volume_type_id': req_volume_type_ids}

        group = None
        try:
            group = self.db.consistencygroup_create(context, options)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_("Error occurred when creating consistency group"
                            " %s."), name)

        request_spec_list = []
        filter_properties_list = []
        for req_volume_type in req_volume_types:
            request_spec = {'volume_type': req_volume_type.copy(),
                            'consistencygroup_id': group['id']}
            filter_properties = {}
            request_spec_list.append(request_spec)
            filter_properties_list.append(filter_properties)

        # Update quota for consistencygroups
        self.update_quota(context, group['id'], 1)

        self._cast_create_consistencygroup(context, group['id'],
                                           request_spec_list,
                                           filter_properties_list)

        return group

    def _cast_create_consistencygroup(self, context, group_id,
                                      request_spec_list,
                                      filter_properties_list):

        try:
            for request_spec in request_spec_list:
                volume_type = request_spec.get('volume_type', None)
                volume_type_id = None
                if volume_type:
                    volume_type_id = volume_type.get('id', None)

                specs = {}
                if volume_type_id:
                    qos_specs = volume_types.get_volume_type_qos_specs(
                        volume_type_id)
                    specs = qos_specs['qos_specs']
                if not specs:
                    # to make sure we don't pass empty dict
                    specs = None

                volume_properties = {
                    'size': 0,  # Need to populate size for the scheduler
                    'user_id': context.user_id,
                    'project_id': context.project_id,
                    'status': 'creating',
                    'attach_status': 'detached',
                    'encryption_key_id': request_spec.get('encryption_key_id',
                                                          None),
                    'display_description': request_spec.get('description',
                                                            None),
                    'display_name': request_spec.get('name', None),
                    'volume_type_id': volume_type_id,
                }

                request_spec['volume_properties'] = volume_properties
                request_spec['qos_specs'] = specs

        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self.db.consistencygroup_destroy(context, group_id)
                finally:
                    LOG.error(_("Error occurred when building "
                                "request spec list for consistency group "
                                "%s."), group_id)

        # Cast to the scheduler and let it handle whatever is needed
        # to select the target host for this group.
        self.scheduler_rpcapi.create_consistencygroup(
            context,
            CONF.volume_topic,
            group_id,
            request_spec_list=request_spec_list,
            filter_properties_list=filter_properties_list)

    def update_quota(self, context, group_id, num, project_id=None):
        reserve_opts = {'consistencygroups': num}
        try:
            reservations = CGQUOTAS.reserve(context,
                                            project_id=project_id,
                                            **reserve_opts)
            if reservations:
                CGQUOTAS.commit(context, reservations)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self.db.consistencygroup_destroy(context.elevated(),
                                                     group_id)
                finally:
                    LOG.error(_("Failed to update quota for "
                                "consistency group %s."), group_id)

    @wrap_check_policy
    def delete(self, context, group, force=False):
        if not group['host']:
            self.update_quota(context, group['id'], -1, group['project_id'])

            msg = ("No host for consistency group %s. Deleting from "
                   "the database.") % group['id']
            LOG.debug(msg)
            self.db.consistencygroup_destroy(context.elevated(), group['id'])

            return

        if not force and group['status'] not in ["available", "error"]:
            msg = _("Consistency group status must be available or error, "
                    "but current status is: %s") % group['status']
            raise exception.InvalidConsistencyGroup(reason=msg)

        cgsnaps = self.db.cgsnapshot_get_all_by_group(
            context.elevated(),
            group['id'])
        if cgsnaps:
            msg = _("Consistency group %s still has dependent "
                    "cgsnapshots.") % group['id']
            LOG.error(msg)
            raise exception.InvalidConsistencyGroup(reason=msg)

        volumes = self.db.volume_get_all_by_group(context.elevated(),
                                                  group['id'])

        if volumes and not force:
            msg = _("Consistency group %s still contains volumes. "
                    "The force flag is required to delete it.") % group['id']
            LOG.error(msg)
            raise exception.InvalidConsistencyGroup(reason=msg)

        for volume in volumes:
            if volume['attach_status'] == "attached":
                msg = _("Volume in consistency group %s is attached. "
                        "Need to detach first.") % group['id']
                LOG.error(msg)
                raise exception.InvalidConsistencyGroup(reason=msg)

            snapshots = self.db.snapshot_get_all_for_volume(context,
                                                            volume['id'])
            if snapshots:
                msg = _("Volume in consistency group still has "
                        "dependent snapshots.")
                LOG.error(msg)
                raise exception.InvalidConsistencyGroup(reason=msg)

        now = timeutils.utcnow()
        self.db.consistencygroup_update(context, group['id'],
                                        {'status': 'deleting',
                                         'terminated_at': now})

        self.volume_rpcapi.delete_consistencygroup(context, group)

    @wrap_check_policy
    def update(self, context, group, fields):
        self.db.consistencygroup_update(context, group['id'], fields)

    def get(self, context, group_id):
        rv = self.db.consistencygroup_get(context, group_id)
        group = dict(rv.iteritems())
        check_policy(context, 'get', group)
        return group

    def get_all(self, context, marker=None, limit=None, sort_key='created_at',
                sort_dir='desc', filters=None):
        check_policy(context, 'get_all')
        if filters is None:
            filters = {}

        try:
            if limit is not None:
                limit = int(limit)
                if limit < 0:
                    msg = _('limit param must be positive')
                    raise exception.InvalidInput(reason=msg)
        except ValueError:
            msg = _('limit param must be an integer')
            raise exception.InvalidInput(reason=msg)

        if filters:
            LOG.debug("Searching by: %s" % str(filters))

        if (context.is_admin and 'all_tenants' in filters):
            # Need to remove all_tenants to pass the filtering below.
            del filters['all_tenants']
            groups = self.db.consistencygroup_get_all(context)
        else:
            groups = self.db.consistencygroup_get_all_by_project(
                context,
                context.project_id)

        return groups

    def get_group(self, context, group_id):
        check_policy(context, 'get_group')
        rv = self.db.consistencygroup_get(context, group_id)
        return dict(rv.iteritems())

    def create_cgsnapshot(self, context,
                          group, name,
                          description):
        return self._create_cgsnapshot(context, group, name, description)

    def _create_cgsnapshot(self, context,
                           group, name, description):
        options = {'consistencygroup_id': group['id'],
                   'user_id': context.user_id,
                   'project_id': context.project_id,
                   'status': "creating",
                   'name': name,
                   'description': description}

        try:
            cgsnapshot = self.db.cgsnapshot_create(context, options)
            cgsnapshot_id = cgsnapshot['id']

            volumes = self.db.volume_get_all_by_group(
                context.elevated(),
                cgsnapshot['consistencygroup_id'])

            if not volumes:
                msg = _("Consistency group is empty. No cgsnapshot "
                        "will be created.")
                raise exception.InvalidConsistencyGroup(reason=msg)

            snap_name = cgsnapshot['name']
            snap_desc = cgsnapshot['description']
            self.volume_api.create_snapshots_in_db(
                context, volumes, snap_name, snap_desc, True, cgsnapshot_id)

        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self.db.cgsnapshot_destroy(context, cgsnapshot_id)
                finally:
                    LOG.error(_("Error occurred when creating cgsnapshot"
                                " %s."), cgsnapshot_id)

        self.volume_rpcapi.create_cgsnapshot(context, group, cgsnapshot)

        return cgsnapshot

    def delete_cgsnapshot(self, context, cgsnapshot, force=False):
        if cgsnapshot['status'] not in ["available", "error"]:
            msg = _("Cgsnapshot status must be available or error")
            raise exception.InvalidCgSnapshot(reason=msg)
        self.db.cgsnapshot_update(context, cgsnapshot['id'],
                                  {'status': 'deleting'})
        group = self.db.consistencygroup_get(
            context,
            cgsnapshot['consistencygroup_id'])
        self.volume_rpcapi.delete_cgsnapshot(context.elevated(), cgsnapshot,
                                             group['host'])

    def update_cgsnapshot(self, context, cgsnapshot, fields):
        self.db.cgsnapshot_update(context, cgsnapshot['id'], fields)

    def get_cgsnapshot(self, context, cgsnapshot_id):
        check_policy(context, 'get_cgsnapshot')
        rv = self.db.cgsnapshot_get(context, cgsnapshot_id)
        return dict(rv.iteritems())

    def get_all_cgsnapshots(self, context, search_opts=None):
        check_policy(context, 'get_all_cgsnapshots')

        search_opts = search_opts or {}

        if (context.is_admin and 'all_tenants' in search_opts):
            # Need to remove all_tenants to pass the filtering below.
            del search_opts['all_tenants']
            cgsnapshots = self.db.cgsnapshot_get_all(context)
        else:
            cgsnapshots = self.db.cgsnapshot_get_all_by_project(
                context.elevated(), context.project_id)

        if search_opts:
            LOG.debug("Searching by: %s" % search_opts)

            results = []
            not_found = object()
            for cgsnapshot in cgsnapshots:
                for opt, value in search_opts.iteritems():
                    if cgsnapshot.get(opt, not_found) != value:
                        break
                else:
                    results.append(cgsnapshot)
            cgsnapshots = results
        return cgsnapshots
