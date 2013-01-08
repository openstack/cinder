# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""
Handles all requests relating to volumes.
"""

import functools

from cinder.db import base
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder import flags
from cinder.image import glance
from cinder.openstack.common import cfg
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import rpc
from cinder.openstack.common import timeutils
import cinder.policy
from cinder import quota
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import volume_types

volume_host_opt = cfg.BoolOpt('snapshot_same_host',
                              default=True,
                              help='Create volume from snapshot at the host '
                                   'where snapshot resides')

FLAGS = flags.FLAGS
FLAGS.register_opt(volume_host_opt)
flags.DECLARE('storage_availability_zone', 'cinder.volume.manager')

LOG = logging.getLogger(__name__)
GB = 1048576 * 1024
QUOTAS = quota.QUOTAS


def wrap_check_policy(func):
    """Check policy corresponding to the wrapped methods prior to execution

    This decorator requires the first 3 args of the wrapped function
    to be (self, context, volume)
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
    _action = 'volume:%s' % action
    cinder.policy.enforce(context, _action, target)


class API(base.Base):
    """API for interacting with the volume manager."""

    def __init__(self, db_driver=None, image_service=None):
        self.image_service = (image_service or
                              glance.get_default_image_service())
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()
        self.volume_rpcapi = volume_rpcapi.VolumeAPI()
        super(API, self).__init__(db_driver)

    def create(self, context, size, name, description, snapshot=None,
               image_id=None, volume_type=None, metadata=None,
               availability_zone=None, source_volume=None):

        if ((snapshot is not None) and (source_volume is not None)):
            msg = (_("May specify either snapshot, "
                     "or src volume but not both!"))
            raise exception.InvalidInput(reason=msg)

        check_policy(context, 'create')
        if snapshot is not None:
            if snapshot['status'] != "available":
                msg = _("status must be available")
                raise exception.InvalidSnapshot(reason=msg)
            if not size:
                size = snapshot['volume_size']

            snapshot_id = snapshot['id']
        else:
            snapshot_id = None

        if source_volume is not None:
            if source_volume['status'] == "error":
                msg = _("Unable to clone volumes that are in an error state")
                raise exception.InvalidSourceVolume(reason=msg)
            if not size:
                size = source_volume['size']
            else:
                if size < source_volume['size']:
                    msg = _("Clones currently must be "
                            ">= original volume size.")
                    raise exception.InvalidInput(reason=msg)
            source_volid = source_volume['id']
        else:
            source_volid = None

        def as_int(s):
            try:
                return int(s)
            except (ValueError, TypeError):
                return s

        # tolerate size as stringified int
        size = as_int(size)

        if not isinstance(size, int) or size <= 0:
            msg = (_("Volume size '%s' must be an integer and greater than 0")
                   % size)
            raise exception.InvalidInput(reason=msg)

        if (image_id and not (source_volume or snapshot)):
            # check image existence
            image_meta = self.image_service.show(context, image_id)
            image_size_in_gb = (int(image_meta['size']) + GB - 1) / GB
            #check image size is not larger than volume size.
            if image_size_in_gb > size:
                msg = _('Size of specified image is larger than volume size.')
                raise exception.InvalidInput(reason=msg)

        try:
            reservations = QUOTAS.reserve(context, volumes=1, gigabytes=size)
        except exception.OverQuota as e:
            overs = e.kwargs['overs']
            usages = e.kwargs['usages']
            quotas = e.kwargs['quotas']

            def _consumed(name):
                return (usages[name]['reserved'] + usages[name]['in_use'])

            pid = context.project_id
            if 'gigabytes' in overs:
                consumed = _consumed('gigabytes')
                quota = quotas['gigabytes']
                LOG.warn(_("Quota exceeded for %(pid)s, tried to create "
                           "%(size)sG volume (%(consumed)dG of %(quota)dG "
                           "already consumed)") % locals())
                raise exception.VolumeSizeExceedsAvailableQuota()
            elif 'volumes' in overs:
                consumed = _consumed('volumes')
                LOG.warn(_("Quota exceeded for %(pid)s, tried to create "
                           "volume (%(consumed)d volumes "
                           "already consumed)") % locals())
                raise exception.VolumeLimitExceeded(allowed=quotas['volumes'])

        if availability_zone is None:
            availability_zone = FLAGS.storage_availability_zone

        if not volume_type and not source_volume:
            volume_type = volume_types.get_default_volume_type()

        if not volume_type and source_volume:
            volume_type_id = source_volume['volume_type_id']
        else:
            volume_type_id = volume_type.get('id')

        options = {'size': size,
                   'user_id': context.user_id,
                   'project_id': context.project_id,
                   'snapshot_id': snapshot_id,
                   'availability_zone': availability_zone,
                   'status': "creating",
                   'attach_status': "detached",
                   'display_name': name,
                   'display_description': description,
                   'volume_type_id': volume_type_id,
                   'metadata': metadata,
                   'source_volid': source_volid}

        try:
            volume = self.db.volume_create(context, options)
            QUOTAS.commit(context, reservations)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self.db.volume_destroy(context, volume['id'])
                finally:
                    QUOTAS.rollback(context, reservations)

        request_spec = {'volume_properties': options,
                        'volume_type': volume_type,
                        'volume_id': volume['id'],
                        'snapshot_id': volume['snapshot_id'],
                        'image_id': image_id,
                        'source_volid': volume['source_volid']}

        filter_properties = {}

        self._cast_create_volume(context, request_spec, filter_properties)

        return volume

    def _cast_create_volume(self, context, request_spec, filter_properties):

        # NOTE(Rongze Zhu): It is a simple solution for bug 1008866
        # If snapshot_id is set, make the call create volume directly to
        # the volume host where the snapshot resides instead of passing it
        # through the scheduler. So snapshot can be copy to new volume.

        source_volid = request_spec['source_volid']
        volume_id = request_spec['volume_id']
        snapshot_id = request_spec['snapshot_id']
        image_id = request_spec['image_id']

        if snapshot_id and FLAGS.snapshot_same_host:
            snapshot_ref = self.db.snapshot_get(context, snapshot_id)
            source_volume_ref = self.db.volume_get(context,
                                                   snapshot_ref['volume_id'])
            now = timeutils.utcnow()
            values = {'host': source_volume_ref['host'], 'scheduled_at': now}
            volume_ref = self.db.volume_update(context, volume_id, values)

            # bypass scheduler and send request directly to volume
            self.volume_rpcapi.create_volume(context,
                                             volume_ref,
                                             volume_ref['host'],
                                             snapshot_id,
                                             image_id)
        elif source_volid:
            source_volume_ref = self.db.volume_get(context,
                                                   source_volid)
            now = timeutils.utcnow()
            values = {'host': source_volume_ref['host'], 'scheduled_at': now}
            volume_ref = self.db.volume_update(context, volume_id, values)

            # bypass scheduler and send request directly to volume
            self.volume_rpcapi.create_volume(context,
                                             volume_ref,
                                             volume_ref['host'],
                                             snapshot_id,
                                             image_id,
                                             source_volid)
        else:
            self.scheduler_rpcapi.create_volume(
                context,
                FLAGS.volume_topic,
                volume_id,
                snapshot_id,
                image_id,
                request_spec=request_spec,
                filter_properties=filter_properties)

    @wrap_check_policy
    def delete(self, context, volume, force=False):
        volume_id = volume['id']
        if not volume['host']:
            # NOTE(vish): scheduling failed, so delete it
            # Note(zhiteng): update volume quota reservation
            try:
                reservations = QUOTAS.reserve(context, volumes=-1,
                                              gigabytes=-volume['size'])
            except Exception:
                reservations = None
                LOG.exception(_("Failed to update quota for deleting volume"))

            self.db.volume_destroy(context, volume_id)

            if reservations:
                QUOTAS.commit(context, reservations)
            return
        if not force and volume['status'] not in ["available", "error"]:
            msg = _("Volume status must be available or error")
            raise exception.InvalidVolume(reason=msg)

        snapshots = self.db.snapshot_get_all_for_volume(context, volume_id)
        if len(snapshots):
            msg = _("Volume still has %d dependent snapshots") % len(snapshots)
            raise exception.InvalidVolume(reason=msg)

        now = timeutils.utcnow()
        self.db.volume_update(context, volume_id, {'status': 'deleting',
                                                   'terminated_at': now})

        self.volume_rpcapi.delete_volume(context, volume)

    @wrap_check_policy
    def update(self, context, volume, fields):
        self.db.volume_update(context, volume['id'], fields)

    def get(self, context, volume_id):
        rv = self.db.volume_get(context, volume_id)
        volume = dict(rv.iteritems())
        check_policy(context, 'get', volume)
        return volume

    def get_all(self, context, marker=None, limit=None, sort_key='created_at',
                sort_dir='desc', filters={}):
        check_policy(context, 'get_all')

        if (context.is_admin and 'all_tenants' in filters):
            # Need to remove all_tenants to pass the filtering below.
            del filters['all_tenants']
            volumes = self.db.volume_get_all(context, marker, limit, sort_key,
                                             sort_dir)
        else:
            volumes = self.db.volume_get_all_by_project(context,
                                                        context.project_id,
                                                        marker, limit,
                                                        sort_key, sort_dir)

        if filters:
            LOG.debug(_("Searching by: %s") % str(filters))

            def _check_metadata_match(volume, searchdict):
                volume_metadata = {}
                for i in volume.get('volume_metadata'):
                    volume_metadata[i['key']] = i['value']

                for k, v in searchdict.iteritems():
                    if (k not in volume_metadata.keys() or
                            volume_metadata[k] != v):
                        return False
                return True

            # search_option to filter_name mapping.
            filter_mapping = {'metadata': _check_metadata_match}

            result = []
            not_found = object()
            for volume in volumes:
                # go over all filters in the list
                for opt, values in filters.iteritems():
                    try:
                        filter_func = filter_mapping[opt]
                    except KeyError:
                        def filter_func(volume, value):
                            return volume.get(opt, not_found) == value
                    if not filter_func(volume, values):
                        break  # volume doesn't match this filter
                else:  # did not break out loop
                    result.append(volume)  # volume matches all filters
            volumes = result

        return volumes

    def get_snapshot(self, context, snapshot_id):
        check_policy(context, 'get_snapshot')
        rv = self.db.snapshot_get(context, snapshot_id)
        return dict(rv.iteritems())

    def get_volume(self, context, volume_id):
        check_policy(context, 'get_volume')
        rv = self.db.volume_get(context, volume_id)
        return dict(rv.iteritems())

    def get_all_snapshots(self, context, search_opts=None):
        check_policy(context, 'get_all_snapshots')

        search_opts = search_opts or {}

        if (context.is_admin and 'all_tenants' in search_opts):
            # Need to remove all_tenants to pass the filtering below.
            del search_opts['all_tenants']
            snapshots = self.db.snapshot_get_all(context)
        else:
            snapshots = self.db.snapshot_get_all_by_project(
                context, context.project_id)

        if search_opts:
            LOG.debug(_("Searching by: %s") % str(search_opts))

            results = []
            not_found = object()
            for snapshot in snapshots:
                for opt, value in search_opts.iteritems():
                    if snapshot.get(opt, not_found) != value:
                        break
                else:
                    results.append(snapshot)
            snapshots = results
        return snapshots

    @wrap_check_policy
    def check_attach(self, context, volume):
        # TODO(vish): abstract status checking?
        if volume['status'] != "available":
            msg = _("status must be available")
            raise exception.InvalidVolume(reason=msg)
        if volume['attach_status'] == "attached":
            msg = _("already attached")
            raise exception.InvalidVolume(reason=msg)

    @wrap_check_policy
    def check_detach(self, context, volume):
        # TODO(vish): abstract status checking?
        if volume['status'] == "available":
            msg = _("already detached")
            raise exception.InvalidVolume(reason=msg)

    @wrap_check_policy
    def reserve_volume(self, context, volume):
        self.update(context, volume, {"status": "attaching"})

    @wrap_check_policy
    def unreserve_volume(self, context, volume):
        if volume['status'] == "attaching":
            self.update(context, volume, {"status": "available"})

    @wrap_check_policy
    def begin_detaching(self, context, volume):
        self.update(context, volume, {"status": "detaching"})

    @wrap_check_policy
    def roll_detaching(self, context, volume):
        if volume['status'] == "detaching":
            self.update(context, volume, {"status": "in-use"})

    @wrap_check_policy
    def attach(self, context, volume, instance_uuid, mountpoint):
        return self.volume_rpcapi.attach_volume(context,
                                                volume,
                                                instance_uuid,
                                                mountpoint)

    @wrap_check_policy
    def detach(self, context, volume):
        return self.volume_rpcapi.detach_volume(context, volume)

    @wrap_check_policy
    def initialize_connection(self, context, volume, connector):
        return self.volume_rpcapi.initialize_connection(context,
                                                        volume,
                                                        connector)

    @wrap_check_policy
    def terminate_connection(self, context, volume, connector, force=False):
        self.unreserve_volume(context, volume)
        return self.volume_rpcapi.terminate_connection(context,
                                                       volume,
                                                       connector,
                                                       force)

    def _create_snapshot(self, context, volume, name, description,
                         force=False):
        check_policy(context, 'create_snapshot', volume)

        if ((not force) and (volume['status'] != "available")):
            msg = _("must be available")
            raise exception.InvalidVolume(reason=msg)

        options = {'volume_id': volume['id'],
                   'user_id': context.user_id,
                   'project_id': context.project_id,
                   'status': "creating",
                   'progress': '0%',
                   'volume_size': volume['size'],
                   'display_name': name,
                   'display_description': description}

        snapshot = self.db.snapshot_create(context, options)
        self.volume_rpcapi.create_snapshot(context, volume, snapshot)

        return snapshot

    def create_snapshot(self, context, volume, name, description):
        return self._create_snapshot(context, volume, name, description,
                                     False)

    def create_snapshot_force(self, context, volume, name, description):
        return self._create_snapshot(context, volume, name, description,
                                     True)

    @wrap_check_policy
    def delete_snapshot(self, context, snapshot, force=False):
        if not force and snapshot['status'] not in ["available", "error"]:
            msg = _("Volume Snapshot status must be available or error")
            raise exception.InvalidVolume(reason=msg)
        self.db.snapshot_update(context, snapshot['id'],
                                {'status': 'deleting'})
        volume = self.db.volume_get(context, snapshot['volume_id'])
        self.volume_rpcapi.delete_snapshot(context, snapshot, volume['host'])

    @wrap_check_policy
    def update_snapshot(self, context, snapshot, fields):
        self.db.snapshot_update(context, snapshot['id'], fields)

    @wrap_check_policy
    def get_volume_metadata(self, context, volume):
        """Get all metadata associated with a volume."""
        rv = self.db.volume_metadata_get(context, volume['id'])
        return dict(rv.iteritems())

    @wrap_check_policy
    def delete_volume_metadata(self, context, volume, key):
        """Delete the given metadata item from a volume."""
        self.db.volume_metadata_delete(context, volume['id'], key)

    @wrap_check_policy
    def update_volume_metadata(self, context, volume, metadata, delete=False):
        """Updates or creates volume metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        if delete:
            _metadata = metadata
        else:
            _metadata = self.get_volume_metadata(context, volume['id'])
            _metadata.update(metadata)

        self.db.volume_metadata_update(context, volume['id'], _metadata, True)
        return _metadata

    def get_volume_metadata_value(self, volume, key):
        """Get value of particular metadata key."""
        metadata = volume.get('volume_metadata')
        if metadata:
            for i in volume['volume_metadata']:
                if i['key'] == key:
                    return i['value']
        return None

    @wrap_check_policy
    def get_volume_image_metadata(self, context, volume):
        db_data = self.db.volume_glance_metadata_get(context, volume['id'])
        return dict(
            (meta_entry.key, meta_entry.value) for meta_entry in db_data
        )

    def _check_volume_availability(self, context, volume, force):
        """Check if the volume can be used."""
        if volume['status'] not in ['available', 'in-use']:
            msg = _('Volume status must be available/in-use.')
            raise exception.InvalidVolume(reason=msg)
        if not force and 'in-use' == volume['status']:
            msg = _('Volume status is in-use.')
            raise exception.InvalidVolume(reason=msg)

    @wrap_check_policy
    def copy_volume_to_image(self, context, volume, metadata, force):
        """Create a new image from the specified volume."""
        self._check_volume_availability(context, volume, force)

        recv_metadata = self.image_service.create(context, metadata)
        self.update(context, volume, {'status': 'uploading'})
        self.volume_rpcapi.copy_volume_to_image(context,
                                                volume,
                                                recv_metadata['id'])

        response = {"id": volume['id'],
                    "updated_at": volume['updated_at'],
                    "status": 'uploading',
                    "display_description": volume['display_description'],
                    "size": volume['size'],
                    "volume_type": volume['volume_type'],
                    "image_id": recv_metadata['id'],
                    "container_format": recv_metadata['container_format'],
                    "disk_format": recv_metadata['disk_format'],
                    "image_name": recv_metadata.get('name', None)}
        return response


class HostAPI(base.Base):
    def __init__(self):
        super(HostAPI, self).__init__()

    """Sub-set of the Volume Manager API for managing host operations."""
    def set_host_enabled(self, context, host, enabled):
        """Sets the specified host's ability to accept new volumes."""
        raise NotImplementedError()

    def get_host_uptime(self, context, host):
        """Returns the result of calling "uptime" on the target host."""
        raise NotImplementedError()

    def host_power_action(self, context, host, action):
        raise NotImplementedError()

    def set_host_maintenance(self, context, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        volume evacuation."""
        raise NotImplementedError()
