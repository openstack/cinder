# -*- coding: utf-8 -*-

# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (C) 2013 Yahoo! Inc. All Rights Reserved.
#    Copyright (c) 2013 OpenStack Foundation
#    Copyright 2010 United States Government as represented by the
#    Administrator of the National Aeronautics and Space Administration.
#    All Rights Reserved.
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

import traceback

from oslo.config import cfg

from cinder import exception
from cinder.image import glance
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder.openstack.common.notifier import api as notifier
from cinder.openstack.common import processutils
from cinder.openstack.common import strutils
from cinder.openstack.common import timeutils
from cinder import policy
from cinder import quota
from cinder.taskflow import decorators
from cinder.taskflow.patterns import linear_flow
from cinder.taskflow import task
from cinder import units
from cinder import utils
from cinder.volume.flows import base
from cinder.volume.flows import utils as flow_utils
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

ACTION = 'volume:create'
CONF = cfg.CONF
GB = units.GiB
QUOTAS = quota.QUOTAS

# Only in these 'sources' status can we attempt to create a volume from a
# source volume or a source snapshot, other status states we can not create
# from, 'error' being the common example.
SNAPSHOT_PROCEED_STATUS = ('available',)
SRC_VOL_PROCEED_STATUS = ('available', 'in-use',)

# When a volume errors out we have the ability to save a piece of the exception
# that caused said failure, but we don't want to save the whole message since
# that could be very large, just save up to this number of characters.
REASON_LENGTH = 128

# These attributes we will attempt to save for the volume if they exist
# in the source image metadata.
IMAGE_ATTRIBUTES = (
    'checksum',
    'container_format',
    'disk_format',
    'min_disk',
    'min_ram',
    'size',
)


def _make_pretty_name(method):
    """Makes a pretty name for a function/method."""
    meth_pieces = [method.__name__]
    # If its an instance method attempt to tack on the class name
    if hasattr(method, 'im_self') and method.im_self is not None:
        try:
            meth_pieces.insert(0, method.im_self.__class__.__name__)
        except AttributeError:
            pass
    return ".".join(meth_pieces)


def _find_result_spec(flow):
    """Find the last task that produced a valid volume_spec and returns it."""
    for there_result in flow.results.values():
        if not there_result or not 'volume_spec' in there_result:
            continue
        if there_result['volume_spec']:
            return there_result['volume_spec']
    return None


def _restore_source_status(context, db, volume_spec):
    # NOTE(harlowja): Only if the type of the volume that was being created is
    # the source volume type should we try to reset the source volume status
    # back to its original value.
    if not volume_spec or volume_spec.get('type') != 'source_vol':
        return
    source_volid = volume_spec['source_volid']
    source_status = volume_spec['source_volstatus']
    try:
        LOG.debug(_('Restoring source %(source_volid)s status to %(status)s') %
                  {'status': source_status, 'source_volid': source_volid})
        db.volume_update(context, source_volid, {'status': source_status})
    except exception.CinderException:
        # NOTE(harlowja): Don't let this cause further exceptions since this is
        # a non-critical failure.
        LOG.exception(_("Failed setting source volume %(source_volid)s back to"
                        " its initial %(source_status)s status") %
                      {'source_status': source_status,
                       'source_volid': source_volid})


def _error_out_volume(context, db, volume_id, reason=None):

    def _clean_reason(reason):
        if reason is None:
            return '???'
        reason = str(reason)
        if len(reason) <= REASON_LENGTH:
            return reason
        else:
            return reason[0:REASON_LENGTH] + '...'

    update = {
        'status': 'error',
    }
    reason = _clean_reason(reason)
    # TODO(harlowja): re-enable when we can support this in the database.
    # if reason:
    #     status['details'] = reason
    try:
        LOG.debug(_('Updating volume: %(volume_id)s with %(update)s'
                    ' due to: %(reason)s') % {'volume_id': volume_id,
                                              'reason': reason,
                                              'update': update})
        db.volume_update(context, volume_id, update)
    except exception.CinderException:
        # Don't let this cause further exceptions.
        LOG.exception(_("Failed updating volume %(volume_id)s with"
                        " %(update)s") % {'volume_id': volume_id,
                                          'update': update})


def _exception_to_unicode(exc):
    try:
        return unicode(exc)
    except UnicodeError:
        try:
            return strutils.safe_decode(str(exc), errors='ignore')
        except UnicodeError:
            msg = (_("Caught '%(exception)s' exception.") %
                   {"exception": exc.__class__.__name__})
            return strutils.safe_decode(msg, errors='ignore')


class ExtractVolumeRequestTask(base.CinderTask):
    """Processes an api request values into a validated set of values.

    This tasks responsibility is to take in a set of inputs that will form
    a potential volume request and validates those values against a set of
    conditions and/or translates those values into a valid set and then returns
    the validated/translated values for use by other tasks.

    Reversion strategy: N/A
    """

    def __init__(self, image_service, az_check_functor=None):
        super(ExtractVolumeRequestTask, self).__init__(addons=[ACTION])
        # This task will produce the following outputs (said outputs can be
        # saved to durable storage in the future so that the flow can be
        # reconstructed elsewhere and continued).
        self.provides.update(['availability_zone', 'size', 'snapshot_id',
                              'source_volid', 'volume_type', 'volume_type_id',
                              'encryption_key_id'])
        # This task requires the following inputs to operate (provided
        # automatically to __call__(). This is done so that the flow can
        # be reconstructed elsewhere and continue running (in the future).
        #
        # It also is used to be able to link tasks that produce items to tasks
        # that consume items (thus allowing the linking of the flow to be
        # mostly automatic).
        self.requires.update(['availability_zone', 'image_id', 'metadata',
                              'size', 'snapshot', 'source_volume',
                              'volume_type', 'key_manager',
                              'backup_source_volume'])
        self.image_service = image_service
        self.az_check_functor = az_check_functor
        if not self.az_check_functor:
            self.az_check_functor = lambda az: True

    @staticmethod
    def _extract_snapshot(snapshot):
        """Extracts the snapshot id from the provided snapshot (if provided).

        This function validates the input snapshot dict and checks that the
        status of that snapshot is valid for creating a volume from.
        """

        snapshot_id = None
        if snapshot is not None:
            if snapshot['status'] not in SNAPSHOT_PROCEED_STATUS:
                msg = _("Originating snapshot status must be one"
                        " of %s values")
                msg = msg % (", ".join(SNAPSHOT_PROCEED_STATUS))
                # TODO(harlowja): what happens if the status changes after this
                # initial snapshot status check occurs??? Seems like someone
                # could delete the snapshot after this check passes but before
                # the volume is offically created?
                raise exception.InvalidSnapshot(reason=msg)
            snapshot_id = snapshot['id']
        return snapshot_id

    @staticmethod
    def _extract_source_volume(source_volume):
        """Extracts the volume id from the provided volume (if provided).

        This function validates the input source_volume dict and checks that
        the status of that source_volume is valid for creating a volume from.
        """

        source_volid = None
        if source_volume is not None:
            if source_volume['status'] not in SRC_VOL_PROCEED_STATUS:
                msg = _("Unable to create a volume from an originating source"
                        " volume when its status is not one of %s"
                        " values")
                msg = msg % (", ".join(SRC_VOL_PROCEED_STATUS))
                # TODO(harlowja): what happens if the status changes after this
                # initial volume status check occurs??? Seems like someone
                # could delete the volume after this check passes but before
                # the volume is offically created?
                raise exception.InvalidVolume(reason=msg)
            source_volid = source_volume['id']
        return source_volid

    @staticmethod
    def _extract_size(size, source_volume, snapshot):
        """Extracts and validates the volume size.

        This function will validate or when not provided fill in the provided
        size variable from the source_volume or snapshot and then does
        validation on the size that is found and returns said validated size.
        """

        def validate_snap_size(size):
            if snapshot and size < snapshot['volume_size']:
                msg = _("Volume size %(size)s cannot be lesser than"
                        " the snapshot size %(snap_size)s. "
                        "They must be >= original snapshot size.")
                msg = msg % {'size': size,
                             'snap_size': snapshot['volume_size']}
                raise exception.InvalidInput(reason=msg)

        def validate_source_size(size):
            if source_volume and size < source_volume['size']:
                msg = _("Clones currently disallowed when "
                        "%(size)s < %(source_size)s. "
                        "They must be >= original volume size.")
                msg = msg % {'size': size,
                             'source_size': source_volume['size']}
                raise exception.InvalidInput(reason=msg)

        def validate_int(size):
            if not isinstance(size, int) or size <= 0:
                msg = _("Volume size %(size)s must be an integer and"
                        " greater than 0") % {'size': size}
                raise exception.InvalidInput(reason=msg)

        # Figure out which validation functions we should be applying
        # on the size value that we extract.
        validator_functors = [validate_int]
        if source_volume:
            validator_functors.append(validate_source_size)
        elif snapshot:
            validator_functors.append(validate_snap_size)

        # If the size is not provided then try to provide it.
        if not size and source_volume:
            size = source_volume['size']
        elif not size and snapshot:
            size = snapshot['volume_size']

        size = utils.as_int(size)
        LOG.debug("Validating volume %(size)s using %(functors)s" %
                  {'size': size,
                   'functors': ", ".join([_make_pretty_name(func)
                                          for func in validator_functors])})
        for func in validator_functors:
            func(size)
        return size

    def _check_image_metadata(self, context, image_id, size):
        """Checks image existence and validates that the image metadata."""

        # Check image existence
        if not image_id:
            return

        # NOTE(harlowja): this should raise an error if the image does not
        # exist, this is expected as it signals that the image_id is missing.
        image_meta = self.image_service.show(context, image_id)

        # Check image size is not larger than volume size.
        image_size = utils.as_int(image_meta['size'], quiet=False)
        image_size_in_gb = (image_size + GB - 1) / GB
        if image_size_in_gb > size:
            msg = _('Size of specified image %(image_size)s'
                    ' is larger than volume size %(volume_size)s.')
            msg = msg % {'image_size': image_size_in_gb, 'volume_size': size}
            raise exception.InvalidInput(reason=msg)

        # Check image min_disk requirement is met for the particular volume
        min_disk = image_meta.get('min_disk', 0)
        if size < min_disk:
            msg = _('Image minDisk size %(min_disk)s is larger'
                    ' than the volume size %(volume_size)s.')
            msg = msg % {'min_disk': min_disk, 'volume_size': size}
            raise exception.InvalidInput(reason=msg)

    @staticmethod
    def _check_metadata_properties(metadata=None):
        """Checks that the volume metadata properties are valid."""

        if not metadata:
            metadata = {}

        for (k, v) in metadata.iteritems():
            if len(k) == 0:
                msg = _("Metadata property key blank")
                LOG.warn(msg)
                raise exception.InvalidVolumeMetadata(reason=msg)
            if len(k) > 255:
                msg = _("Metadata property key %s greater than 255 "
                        "characters") % k
                LOG.warn(msg)
                raise exception.InvalidVolumeMetadataSize(reason=msg)
            if len(v) > 255:
                msg = _("Metadata property key %s value greater than"
                        " 255 characters") % k
                LOG.warn(msg)
                raise exception.InvalidVolumeMetadataSize(reason=msg)

    def _extract_availability_zone(self, availability_zone, snapshot,
                                   source_volume):
        """Extracts and returns a validated availability zone.

        This function will extract the availability zone (if not provided) from
        the snapshot or source_volume and then performs a set of validation
        checks on the provided or extracted availability zone and then returns
        the validated availability zone.
        """

        # Try to extract the availability zone from the corresponding snapshot
        # or source volume if either is valid so that we can be in the same
        # availability zone as the source.
        if availability_zone is None:
            if snapshot:
                try:
                    availability_zone = snapshot['volume']['availability_zone']
                except (TypeError, KeyError):
                    pass
            if source_volume and availability_zone is None:
                try:
                    availability_zone = source_volume['availability_zone']
                except (TypeError, KeyError):
                    pass

        if availability_zone is None:
            if CONF.default_availability_zone:
                availability_zone = CONF.default_availability_zone
            else:
                # For backwards compatibility use the storge_availability_zone
                availability_zone = CONF.storage_availability_zone
        if not self.az_check_functor(availability_zone):
            msg = _("Availability zone '%s' is invalid") % (availability_zone)
            LOG.warn(msg)
            raise exception.InvalidInput(reason=msg)

        # If the configuration only allows cloning to the same availability
        # zone then we need to enforce that.
        if CONF.cloned_volume_same_az:
            snap_az = None
            try:
                snap_az = snapshot['volume']['availability_zone']
            except (TypeError, KeyError):
                pass
            if snap_az and snap_az != availability_zone:
                msg = _("Volume must be in the same "
                        "availability zone as the snapshot")
                raise exception.InvalidInput(reason=msg)
            source_vol_az = None
            try:
                source_vol_az = source_volume['availability_zone']
            except (TypeError, KeyError):
                pass
            if source_vol_az and source_vol_az != availability_zone:
                msg = _("Volume must be in the same "
                        "availability zone as the source volume")
                raise exception.InvalidInput(reason=msg)

        return availability_zone

    def _get_encryption_key_id(self, key_manager, context, volume_type_id,
                               snapshot, source_volume, backup_source_volume):
        encryption_key_id = None
        if volume_types.is_encrypted(context, volume_type_id):
            if snapshot is not None:  # creating from snapshot
                encryption_key_id = snapshot['encryption_key_id']
            elif source_volume is not None:  # cloning volume
                encryption_key_id = source_volume['encryption_key_id']
            elif backup_source_volume is not None:  # creating from backup
                encryption_key_id = backup_source_volume['encryption_key_id']

            # NOTE(joel-coffman): References to the encryption key should *not*
            # be copied because the key is deleted when the volume is deleted.
            # Clone the existing key and associate a separate -- but
            # identical -- key with each volume.
            if encryption_key_id is not None:
                encryption_key_id = key_manager.copy_key(context,
                                                         encryption_key_id)
            else:
                encryption_key_id = key_manager.create_key(context)

        return encryption_key_id

    def _get_volume_type_id(self, volume_type, source_volume, snapshot,
                            backup_source_volume):
        volume_type_id = None
        if not volume_type and source_volume:
            volume_type_id = source_volume['volume_type_id']
        elif snapshot is not None:
            if volume_type:
                current_volume_type_id = volume_type.get('id')
                if (current_volume_type_id !=
                        snapshot['volume_type_id']):
                    msg = _("Volume type will be changed to "
                            "be the same as the source volume.")
                    LOG.warn(msg)
            volume_type_id = snapshot['volume_type_id']
        elif backup_source_volume is not None:
            volume_type_id = backup_source_volume['volume_type_id']
        else:
            volume_type_id = volume_type.get('id')

        return volume_type_id

    def __call__(self, context, size, snapshot, image_id, source_volume,
                 availability_zone, volume_type, metadata,
                 key_manager, backup_source_volume):

        utils.check_exclusive_options(snapshot=snapshot,
                                      imageRef=image_id,
                                      source_volume=source_volume)
        policy.enforce_action(context, ACTION)

        # TODO(harlowja): what guarantee is there that the snapshot or source
        # volume will remain available after we do this initial verification??
        snapshot_id = self._extract_snapshot(snapshot)
        source_volid = self._extract_source_volume(source_volume)
        size = self._extract_size(size, source_volume, snapshot)

        self._check_image_metadata(context, image_id, size)

        availability_zone = self._extract_availability_zone(availability_zone,
                                                            snapshot,
                                                            source_volume)

        # TODO(joel-coffman): This special handling of snapshots to ensure that
        # their volume type matches the source volume is too convoluted. We
        # should copy encryption metadata from the encrypted volume type to the
        # volume upon creation and propogate that information to each snapshot.
        # This strategy avoid any dependency upon the encrypted volume type.
        if not volume_type and not source_volume and not snapshot:
            volume_type = volume_types.get_default_volume_type()

        volume_type_id = self._get_volume_type_id(volume_type,
                                                  source_volume, snapshot,
                                                  backup_source_volume)

        encryption_key_id = self._get_encryption_key_id(key_manager,
                                                        context,
                                                        volume_type_id,
                                                        snapshot,
                                                        source_volume,
                                                        backup_source_volume)

        specs = {}
        if volume_type_id:
            qos_specs = volume_types.get_volume_type_qos_specs(volume_type_id)
            specs = qos_specs['qos_specs']
        if not specs:
            # to make sure we don't pass empty dict
            specs = None

        self._check_metadata_properties(metadata)

        return {
            'size': size,
            'snapshot_id': snapshot_id,
            'source_volid': source_volid,
            'availability_zone': availability_zone,
            'volume_type': volume_type,
            'volume_type_id': volume_type_id,
            'encryption_key_id': encryption_key_id,
            'qos_specs': specs,
        }


class EntryCreateTask(base.CinderTask):
    """Creates an entry for the given volume creation in the database.

    Reversion strategy: remove the volume_id created from the database.
    """

    def __init__(self, db):
        super(EntryCreateTask, self).__init__(addons=[ACTION])
        self.db = db
        self.requires.update(['availability_zone', 'description', 'metadata',
                              'name', 'reservations', 'size', 'snapshot_id',
                              'source_volid', 'volume_type_id',
                              'encryption_key_id'])
        self.provides.update(['volume_properties', 'volume_id'])

    def __call__(self, context, **kwargs):
        """Creates a database entry for the given inputs and returns details.

        Accesses the database and creates a new entry for the to be created
        volume using the given volume properties which are extracted from the
        input kwargs (and associated requirements this task needs). These
        requirements should be previously satisifed and validated by a
        pre-cursor task.
        """

        volume_properties = {
            'size': kwargs.pop('size'),
            'user_id': context.user_id,
            'project_id': context.project_id,
            'status': 'creating',
            'attach_status': 'detached',
            'encryption_key_id': kwargs.pop('encryption_key_id'),
            # Rename these to the internal name.
            'display_description': kwargs.pop('description'),
            'display_name': kwargs.pop('name'),
        }

        # Merge in the other required arguments which should provide the rest
        # of the volume property fields (if applicable).
        volume_properties.update(kwargs)
        volume = self.db.volume_create(context, volume_properties)

        return {
            'volume_id': volume['id'],
            'volume_properties': volume_properties,
            # NOTE(harlowja): it appears like further usage of this volume
            # result actually depend on it being a sqlalchemy object and not
            # just a plain dictionary so thats why we are storing this here.
            #
            # In the future where this task results can be serialized and
            # restored automatically for continued running we will need to
            # resolve the serialization & recreation of this object since raw
            # sqlalchemy objects can't be serialized.
            'volume': volume,
        }

    def revert(self, context, result, cause):
        # We never produced a result and therefore can't destroy anything.
        if not result:
            return
        if context.quota_committed:
            # Committed quota doesn't rollback as the volume has already been
            # created at this point, and the quota has already been absorbed.
            return
        vol_id = result['volume_id']
        try:
            self.db.volume_destroy(context.elevated(), vol_id)
        except exception.CinderException:
            # We are already reverting, therefore we should silence this
            # exception since a second exception being active will be bad.
            #
            # NOTE(harlowja): Being unable to destroy a volume is pretty
            # bad though!!
            LOG.exception(_("Failed destroying volume entry %s"), vol_id)


class QuotaReserveTask(base.CinderTask):
    """Reserves a single volume with the given size & the given volume type.

    Reversion strategy: rollback the quota reservation.

    Warning Warning: if the process that is running this reserve and commit
    process fails (or is killed before the quota is rolled back or commited
    it does appear like the quota will never be rolled back). This makes
    software upgrades hard (inflight operations will need to be stopped or
    allowed to complete before the upgrade can occur). *In the future* when
    taskflow has persistence built-in this should be easier to correct via
    an automated or manual process.
    """

    def __init__(self):
        super(QuotaReserveTask, self).__init__(addons=[ACTION])
        self.requires.update(['size', 'volume_type_id'])
        self.provides.update(['reservations'])

    def __call__(self, context, size, volume_type_id):
        try:
            reserve_opts = {'volumes': 1, 'gigabytes': size}
            QUOTAS.add_volume_type_opts(context, reserve_opts, volume_type_id)
            reservations = QUOTAS.reserve(context, **reserve_opts)
            return {
                'reservations': reservations,
            }
        except exception.OverQuota as e:
            overs = e.kwargs['overs']
            quotas = e.kwargs['quotas']
            usages = e.kwargs['usages']

            def _consumed(name):
                return (usages[name]['reserved'] + usages[name]['in_use'])

            def _is_over(name):
                for over in overs:
                    if name in over:
                        return True
                return False

            if _is_over('gigabytes'):
                msg = _("Quota exceeded for %(s_pid)s, tried to create "
                        "%(s_size)sG volume (%(d_consumed)dG "
                        "of %(d_quota)dG already consumed)")
                LOG.warn(msg % {'s_pid': context.project_id,
                                's_size': size,
                                'd_consumed': _consumed('gigabytes'),
                                'd_quota': quotas['gigabytes']})
                raise exception.VolumeSizeExceedsAvailableQuota()
            elif _is_over('volumes'):
                msg = _("Quota exceeded for %(s_pid)s, tried to create "
                        "volume (%(d_consumed)d volumes "
                        "already consumed)")
                LOG.warn(msg % {'s_pid': context.project_id,
                                'd_consumed': _consumed('volumes')})
                allowed = quotas['volumes']
                raise exception.VolumeLimitExceeded(allowed=quotas['volumes'])
            else:
                # If nothing was reraised, ensure we reraise the initial error
                raise

    def revert(self, context, result, cause):
        # We never produced a result and therefore can't destroy anything.
        if not result:
            return
        if context.quota_committed:
            # The reservations have already been commited and can not be
            # rolled back at this point.
            return
        # We actually produced an output that we can revert so lets attempt
        # to use said output to rollback the reservation.
        reservations = result['reservations']
        try:
            QUOTAS.rollback(context, reservations)
        except exception.CinderException:
            # We are already reverting, therefore we should silence this
            # exception since a second exception being active will be bad.
            LOG.exception(_("Failed rolling back quota for"
                            " %s reservations"), reservations)


class QuotaCommitTask(base.CinderTask):
    """Commits the reservation.

    Reversion strategy: N/A (the rollback will be handled by the task that did
    the initial reservation (see: QuotaReserveTask).

    Warning Warning: if the process that is running this reserve and commit
    process fails (or is killed before the quota is rolled back or commited
    it does appear like the quota will never be rolled back). This makes
    software upgrades hard (inflight operations will need to be stopped or
    allowed to complete before the upgrade can occur). *In the future* when
    taskflow has persistence built-in this should be easier to correct via
    an automated or manual process.
    """

    def __init__(self):
        super(QuotaCommitTask, self).__init__(addons=[ACTION])
        self.requires.update(['reservations', 'volume_properties'])

    def __call__(self, context, reservations, volume_properties):
        QUOTAS.commit(context, reservations)
        context.quota_committed = True
        return {'volume_properties': volume_properties}

    def revert(self, context, result, cause):
        # We never produced a result and therefore can't destroy anything.
        if not result:
            return
        volume = result['volume_properties']
        try:
            reserve_opts = {'volumes': -1, 'gigabytes': -volume['size']}
            QUOTAS.add_volume_type_opts(context,
                                        reserve_opts,
                                        volume['volume_type_id'])
            reservations = QUOTAS.reserve(context,
                                          project_id=context.project_id,
                                          **reserve_opts)
            if reservations:
                QUOTAS.commit(context, reservations,
                              project_id=context.project_id)
        except Exception:
            LOG.exception(_("Failed to update quota for deleting volume: %s"),
                          volume['id'])


class VolumeCastTask(base.CinderTask):
    """Performs a volume create cast to the scheduler or to the volume manager.

    This which will signal a transition of the api workflow to another child
    and/or related workflow on another component.

    Reversion strategy: N/A
    """

    def __init__(self, scheduler_rpcapi, volume_rpcapi, db):
        super(VolumeCastTask, self).__init__(addons=[ACTION])
        self.volume_rpcapi = volume_rpcapi
        self.scheduler_rpcapi = scheduler_rpcapi
        self.db = db
        self.requires.update(['image_id', 'scheduler_hints', 'snapshot_id',
                              'source_volid', 'volume_id', 'volume_type',
                              'volume_properties'])

    def _cast_create_volume(self, context, request_spec, filter_properties):
        source_volid = request_spec['source_volid']
        volume_id = request_spec['volume_id']
        snapshot_id = request_spec['snapshot_id']
        image_id = request_spec['image_id']
        host = None

        if snapshot_id and CONF.snapshot_same_host:
            # NOTE(Rongze Zhu): A simple solution for bug 1008866.
            #
            # If snapshot_id is set, make the call create volume directly to
            # the volume host where the snapshot resides instead of passing it
            # through the scheduler. So snapshot can be copy to new volume.
            snapshot_ref = self.db.snapshot_get(context, snapshot_id)
            source_volume_ref = self.db.volume_get(context,
                                                   snapshot_ref['volume_id'])
            host = source_volume_ref['host']
        elif source_volid:
            source_volume_ref = self.db.volume_get(context, source_volid)
            host = source_volume_ref['host']

        if not host:
            # Cast to the scheduler and let it handle whatever is needed
            # to select the target host for this volume.
            self.scheduler_rpcapi.create_volume(
                context,
                CONF.volume_topic,
                volume_id,
                snapshot_id=snapshot_id,
                image_id=image_id,
                request_spec=request_spec,
                filter_properties=filter_properties)
        else:
            # Bypass the scheduler and send the request directly to the volume
            # manager.
            now = timeutils.utcnow()
            values = {'host': host, 'scheduled_at': now}
            volume_ref = self.db.volume_update(context, volume_id, values)
            self.volume_rpcapi.create_volume(
                context,
                volume_ref,
                volume_ref['host'],
                request_spec,
                filter_properties,
                allow_reschedule=False,
                snapshot_id=snapshot_id,
                image_id=image_id,
                source_volid=source_volid)

    def __call__(self, context, **kwargs):
        scheduler_hints = kwargs.pop('scheduler_hints', None)
        request_spec = kwargs.copy()
        filter_properties = {}
        if scheduler_hints:
            filter_properties['scheduler_hints'] = scheduler_hints
        self._cast_create_volume(context, request_spec, filter_properties)


class OnFailureChangeStatusTask(base.CinderTask):
    """Helper task that sets a volume id to status error.

    Reversion strategy: On failure of any flow that includes this task the
    volume id that is associated with this task will be have its status set
    to error. If a volume specification is provided and the type of that spec
    is a source volume said source volume will have its status status updated
    as well.
    """

    def __init__(self, db):
        super(OnFailureChangeStatusTask, self).__init__(addons=[ACTION])
        self.db = db
        self.requires.update(['volume_id'])
        self.optional.update(['volume_spec'])

    def __call__(self, context, volume_id, volume_spec=None):
        # Save these items since we only use them if a reversion is triggered.
        return {
            'volume_id': volume_id,
            'volume_spec': volume_spec,
        }

    def revert(self, context, result, cause):
        volume_spec = result.get('volume_spec')
        if not volume_spec:
            # Attempt to use it from a later task that *should* have populated
            # this from the database. It is not needed to be found since
            # reverting will continue without it.
            volume_spec = _find_result_spec(cause.flow)

        # Restore the source volume status and set the volume to error status.
        volume_id = result['volume_id']
        _restore_source_status(context, self.db, volume_spec)
        _error_out_volume(context, self.db, volume_id, reason=cause.exc)
        LOG.error(_("Volume %s: create failed"), volume_id)
        exc_info = False
        if all(cause.exc_info):
            exc_info = cause.exc_info
        LOG.error(_('Unexpected build error:'), exc_info=exc_info)


class OnFailureRescheduleTask(base.CinderTask):
    """Triggers a rescheduling request to be sent when reverting occurs.

    Reversion strategy: Triggers the rescheduling mechanism whereby a cast gets
    sent to the scheduler rpc api to allow for an attempt X of Y for scheduling
    this volume elsewhere.
    """

    def __init__(self, reschedule_context, db, scheduler_rpcapi):
        super(OnFailureRescheduleTask, self).__init__(addons=[ACTION])
        self.requires.update(['filter_properties', 'image_id', 'request_spec',
                              'snapshot_id', 'volume_id'])
        self.optional.update(['volume_spec'])
        self.scheduler_rpcapi = scheduler_rpcapi
        self.db = db
        self.reschedule_context = reschedule_context
        # These exception types will trigger the volume to be set into error
        # status rather than being rescheduled.
        self.no_reschedule_types = [
            # The volume has already finished being created when the exports
            # occur, rescheduling would be bad if it happened due to exports
            # not succeeding.
            exception.ExportFailure,
            # Image copying happens after volume creation so rescheduling due
            # to copy failure will mean the same volume will be created at
            # another place when it still exists locally.
            exception.ImageCopyFailure,
            # Metadata updates happen after the volume has been created so if
            # they fail, rescheduling will likely attempt to create the volume
            # on another machine when it still exists locally.
            exception.MetadataCopyFailure,
            exception.MetadataCreateFailure,
            exception.MetadataUpdateFailure,
            # The volume/snapshot has been removed from the database, that
            # can not be fixed by rescheduling.
            exception.VolumeNotFound,
            exception.SnapshotNotFound,
            exception.VolumeTypeNotFound,
            exception.ImageUnacceptable,
        ]

    def _is_reschedulable(self, cause):
        # Figure out the type of the causes exception and compare it against
        # our black-list of exception types that will not cause rescheduling.
        exc_type, value = cause.exc_info[:2]
        # If we don't have a type from exc_info but we do have a exception in
        # the cause, try to get the type from that instead.
        if not value:
            value = cause.exc
        if not exc_type and value:
            exc_type = type(value)
        if exc_type and exc_type in self.no_reschedule_types:
            return False
        # Couldn't figure it out, by default assume whatever the cause was can
        # be fixed by rescheduling.
        #
        # NOTE(harlowja): Crosses fingers.
        return True

    def __call__(self, context, *args, **kwargs):
        # Save these items since we only use them if a reversion is triggered.
        return kwargs.copy()

    def _reschedule(self, context, cause, request_spec, filter_properties,
                    snapshot_id, image_id, volume_id, **kwargs):
        """Actions that happen during the rescheduling attempt occur here."""

        create_volume = self.scheduler_rpcapi.create_volume
        if not filter_properties:
            filter_properties = {}
        if 'retry' not in filter_properties:
            filter_properties['retry'] = {}

        retry_info = filter_properties['retry']
        num_attempts = retry_info.get('num_attempts', 0)
        request_spec['volume_id'] = volume_id

        LOG.debug(_("Volume %(volume_id)s: re-scheduling %(method)s "
                    "attempt %(num)d due to %(reason)s") %
                  {'volume_id': volume_id,
                   'method': _make_pretty_name(create_volume),
                   'num': num_attempts,
                   'reason': _exception_to_unicode(cause.exc)})

        if all(cause.exc_info):
            # Stringify to avoid circular ref problem in json serialization
            retry_info['exc'] = traceback.format_exception(*cause.exc_info)

        return create_volume(context, CONF.volume_topic, volume_id,
                             snapshot_id=snapshot_id, image_id=image_id,
                             request_spec=request_spec,
                             filter_properties=filter_properties)

    def _post_reschedule(self, context, volume_id):
        """Actions that happen after the rescheduling attempt occur here."""

        LOG.debug(_("Volume %s: re-scheduled"), volume_id)

    def _pre_reschedule(self, context, volume_id):
        """Actions that happen before the rescheduling attempt occur here."""

        try:
            # Reset the volume state.
            #
            # NOTE(harlowja): this is awkward to be done here, shouldn't
            # this happen at the scheduler itself and not before it gets
            # sent to the scheduler? (since what happens if it never gets
            # there??). It's almost like we need a status of 'on-the-way-to
            # scheduler' in the future.
            update = {
                'status': 'creating',
                'scheduled_at': timeutils.utcnow(),
            }
            LOG.debug(_("Updating volume %(volume_id)s with %(update)s") %
                      {'update': update, 'volume_id': volume_id})
            self.db.volume_update(context, volume_id, update)
        except exception.CinderException:
            # Don't let resetting the status cause the rescheduling to fail.
            LOG.exception(_("Volume %s: resetting 'creating' status failed"),
                          volume_id)

    def revert(self, context, result, cause):
        volume_spec = result.get('volume_spec')
        if not volume_spec:
            # Find it from a prior task that populated this from the database.
            volume_spec = _find_result_spec(cause.flow)
        volume_id = result['volume_id']

        # Use a different context when rescheduling.
        if self.reschedule_context:
            context = self.reschedule_context

        # If we are now supposed to reschedule (or unable to), then just
        # restore the source volume status and set the volume to error status.
        def do_error_revert():
            LOG.debug(_("Failing volume %s creation by altering volume status"
                        " instead of rescheduling"), volume_id)
            _restore_source_status(context, self.db, volume_spec)
            _error_out_volume(context, self.db, volume_id, reason=cause.exc)
            LOG.error(_("Volume %s: create failed"), volume_id)

        # Check if we have a cause which can tell us not to reschedule.
        if not self._is_reschedulable(cause):
            do_error_revert()
        else:
            try:
                self._pre_reschedule(context, volume_id)
                self._reschedule(context, cause, **result)
                self._post_reschedule(context, volume_id)
            except exception.CinderException:
                LOG.exception(_("Volume %s: rescheduling failed"), volume_id)
                # NOTE(harlowja): Do error volume status changing instead.
                do_error_revert()
        exc_info = False
        if all(cause.exc_info):
            exc_info = cause.exc_info
        LOG.error(_('Unexpected build error:'), exc_info=exc_info)


class NotifySchedulerFailureTask(base.CinderTask):
    """Helper task that notifies some external service on failure.

    Reversion strategy: On failure of any flow that includes this task the
    request specification associated with that flow will be extracted and
    sent as a payload to the notification service under the given methods
    scheduler topic.
    """

    def __init__(self, method):
        super(NotifySchedulerFailureTask, self).__init__(addons=[ACTION])
        self.requires.update(['request_spec', 'volume_id'])
        self.method = method
        self.topic = 'scheduler.%s' % self.method
        self.publisher_id = notifier.publisher_id("scheduler")

    def __call__(self, context, **kwargs):
        # Save these items since we only use them if a reversion is triggered.
        return kwargs.copy()

    def revert(self, context, result, cause):
        request_spec = result['request_spec']
        volume_id = result['volume_id']
        volume_properties = request_spec['volume_properties']
        payload = {
            'request_spec': request_spec,
            'volume_properties': volume_properties,
            'volume_id': volume_id,
            'state': 'error',
            'method': self.method,
            'reason': unicode(cause.exc),
        }
        try:
            notifier.notify(context, self.publisher_id, self.topic,
                            notifier.ERROR, payload)
        except exception.CinderException:
            LOG.exception(_("Failed notifying on %(topic)s "
                            "payload %(payload)s") % {'topic': self.topic,
                                                      'payload': payload})


class ExtractSchedulerSpecTask(base.CinderTask):
    """Extracts a spec object from a partial and/or incomplete request spec.

    Reversion strategy: N/A
    """

    def __init__(self, db):
        super(ExtractSchedulerSpecTask, self).__init__(addons=[ACTION])
        self.db = db
        self.requires.update(['image_id', 'request_spec', 'snapshot_id',
                              'volume_id'])
        self.provides.update(['request_spec'])

    def _populate_request_spec(self, context, volume_id, snapshot_id,
                               image_id):
        # Create the full request spec using the volume_id.
        #
        # NOTE(harlowja): this will fetch the volume from the database, if
        # the volume has been deleted before we got here then this should fail.
        #
        # In the future we might want to have a lock on the volume_id so that
        # the volume can not be deleted while its still being created?
        if not volume_id:
            msg = _("No volume_id provided to populate a request_spec from")
            raise exception.InvalidInput(reason=msg)
        volume_ref = self.db.volume_get(context, volume_id)
        volume_type_id = volume_ref.get('volume_type_id')
        vol_type = self.db.volume_type_get(context, volume_type_id)
        return {
            'volume_id': volume_id,
            'snapshot_id': snapshot_id,
            'image_id': image_id,
            'volume_properties': {
                'size': utils.as_int(volume_ref.get('size'), quiet=False),
                'availability_zone': volume_ref.get('availability_zone'),
                'volume_type_id': volume_type_id,
            },
            'volume_type': list(dict(vol_type).iteritems()),
        }

    def __call__(self, context, request_spec, volume_id, snapshot_id,
                 image_id):
        # For RPC version < 1.2 backward compatibility
        if request_spec is None:
            request_spec = self._populate_request_spec(context, volume_id,
                                                       snapshot_id, image_id)
        return {
            'request_spec': request_spec,
        }


class ExtractVolumeSpecTask(base.CinderTask):
    """Extracts a spec of a volume to be created into a common structure.

    This task extracts and organizes the input requirements into a common
    and easier to analyze structure for later tasks to use. It will also
    attach the underlying database volume reference which can be used by
    other tasks to reference for further details about the volume to be.

    Reversion strategy: N/A
    """

    def __init__(self, db):
        super(ExtractVolumeSpecTask, self).__init__(addons=[ACTION])
        self.db = db
        self.requires.update(['filter_properties', 'image_id', 'snapshot_id',
                              'source_volid', 'volume_id'])
        self.provides.update(['volume_spec', 'volume_ref'])

    def __call__(self, context, volume_id, **kwargs):
        get_remote_image_service = glance.get_remote_image_service

        # NOTE(harlowja): this will fetch the volume from the database, if
        # the volume has been deleted before we got here then this should fail.
        #
        # In the future we might want to have a lock on the volume_id so that
        # the volume can not be deleted while its still being created?
        volume_ref = self.db.volume_get(context, volume_id)
        volume_name = volume_ref['name']
        volume_size = utils.as_int(volume_ref['size'], quiet=False)

        # Create a dictionary that will represent the volume to be so that
        # later tasks can easily switch between the different types and create
        # the volume according to the volume types specifications (which are
        # represented in this dictionary).
        specs = {
            'status': volume_ref['status'],
            'type': 'raw',  # This will have the type of the volume to be
                            # created, which should be one of [raw, snap,
                            # source_vol, image]
            'volume_id': volume_ref['id'],
            'volume_name': volume_name,
            'volume_size': volume_size,
        }

        if kwargs.get('snapshot_id'):
            # We are making a snapshot based volume instead of a raw volume.
            specs.update({
                'type': 'snap',
                'snapshot_id': kwargs['snapshot_id'],
            })
        elif kwargs.get('source_volid'):
            # We are making a source based volume instead of a raw volume.
            #
            # NOTE(harlowja): This will likely fail if the source volume
            # disappeared by the time this call occurred.
            source_volid = kwargs['source_volid']
            source_volume_ref = self.db.volume_get(context, source_volid)
            specs.update({
                'source_volid': source_volid,
                # This is captured incase we have to revert and we want to set
                # back the source volume status to its original status. This
                # may or may not be sketchy to do??
                'source_volstatus': source_volume_ref['status'],
                'type': 'source_vol',
            })
        elif kwargs.get('image_id'):
            # We are making a image based volume instead of a raw volume.
            image_href = kwargs['image_id']
            image_service, image_id = get_remote_image_service(context,
                                                               image_href)
            specs.update({
                'type': 'image',
                'image_id': image_id,
                'image_location': image_service.get_location(context,
                                                             image_id),
                'image_meta': image_service.show(context, image_id),
                # Instead of refetching the image service later just save it.
                #
                # NOTE(harlowja): if we have to later recover this tasks output
                # on another 'node' that this object won't be able to be
                # serialized, so we will have to recreate this object on
                # demand in the future.
                'image_service': image_service,
            })

        return {
            'volume_spec': specs,
            # NOTE(harlowja): it appears like further usage of this volume_ref
            # result actually depend on it being a sqlalchemy object and not
            # just a plain dictionary so thats why we are storing this here.
            #
            # It was attempted to refetch it when needed in subsequent tasks,
            # but that caused sqlalchemy errors to occur (volume already open
            # or similar).
            #
            # In the future where this task could fail and be recovered from we
            # will need to store the volume_spec and recreate the volume_ref
            # on demand.
            'volume_ref': volume_ref,
        }


class NotifyVolumeActionTask(base.CinderTask):
    """Performs a notification about the given volume when called.

    Reversion strategy: N/A
    """

    def __init__(self, db, host, event_suffix):
        super(NotifyVolumeActionTask, self).__init__(addons=[ACTION,
                                                             event_suffix])
        self.requires.update(['volume_ref'])
        self.db = db
        self.event_suffix = event_suffix
        self.host = host

    def __call__(self, context, volume_ref):
        volume_id = volume_ref['id']
        try:
            volume_utils.notify_about_volume_usage(context, volume_ref,
                                                   self.event_suffix,
                                                   host=self.host)
        except exception.CinderException:
            # If notification sending of volume database entry reading fails
            # then we shouldn't error out the whole workflow since this is
            # not always information that must be sent for volumes to operate
            LOG.exception(_("Failed notifying about the volume"
                            " action %(event)s for volume %(volume_id)s") %
                          {'event': self.event_suffix,
                           'volume_id': volume_id})


class CreateVolumeFromSpecTask(base.CinderTask):
    """Creates a volume from a provided specification.

    Reversion strategy: N/A
    """

    def __init__(self, db, host, driver):
        super(CreateVolumeFromSpecTask, self).__init__(addons=[ACTION])
        self.db = db
        self.driver = driver
        self.requires.update(['volume_spec', 'volume_ref'])
        # This maps the different volume specification types into the methods
        # that can create said volume type (aka this is a jump table).
        self._create_func_mapping = {
            'raw': self._create_raw_volume,
            'snap': self._create_from_snapshot,
            'source_vol': self._create_from_source_volume,
            'image': self._create_from_image,
        }
        self.host = host

    def _handle_bootable_volume_glance_meta(self, context, volume_id,
                                            **kwargs):
        """Enable bootable flag and properly handle glance metadata.

        Caller should provide one and only one of snapshot_id,source_volid
        and image_id. If an image_id specified, a image_meta should also be
        provided, otherwise will be treated as an empty dictionary.
        """

        log_template = _("Copying metadata from %(src_type)s %(src_id)s to "
                         "%(vol_id)s")
        exception_template = _("Failed updating volume %(vol_id)s metadata"
                               " using the provided %(src_type)s"
                               " %(src_id)s metadata")
        src_type = None
        src_id = None
        self._enable_bootable_flag(context, volume_id)
        try:
            if kwargs.get('snapshot_id'):
                src_type = 'snapshot'
                src_id = kwargs['snapshot_id']
                snapshot_id = src_id
                LOG.debug(log_template % {'src_type': src_type,
                                          'src_id': src_id,
                                          'vol_id': volume_id})
                self.db.volume_glance_metadata_copy_to_volume(
                    context, volume_id, snapshot_id)
            elif kwargs.get('source_volid'):
                src_type = 'source volume'
                src_id = kwargs['source_volid']
                source_volid = src_id
                LOG.debug(log_template % {'src_type': src_type,
                                          'src_id': src_id,
                                          'vol_id': volume_id})
                self.db.volume_glance_metadata_copy_from_volume_to_volume(
                    context,
                    source_volid,
                    volume_id)
            elif kwargs.get('image_id'):
                src_type = 'image'
                src_id = kwargs['image_id']
                image_id = src_id
                image_meta = kwargs.get('image_meta', {})
                LOG.debug(log_template % {'src_type': src_type,
                                          'src_id': src_id,
                                          'vol_id': volume_id})
                self._capture_volume_image_metadata(context, volume_id,
                                                    image_id, image_meta)
        except exception.CinderException as ex:
            LOG.exception(exception_template % {'src_type': src_type,
                                                'src_id': src_id,
                                                'vol_id': volume_id})
            raise exception.MetadataCopyFailure(reason=ex)

    def _create_from_snapshot(self, context, volume_ref, snapshot_id,
                              **kwargs):
        volume_id = volume_ref['id']
        snapshot_ref = self.db.snapshot_get(context, snapshot_id)
        model_update = self.driver.create_volume_from_snapshot(volume_ref,
                                                               snapshot_ref)
        # NOTE(harlowja): Subtasks would be useful here since after this
        # point the volume has already been created and further failures
        # will not destroy the volume (although they could in the future).
        make_bootable = False
        try:
            originating_vref = self.db.volume_get(context,
                                                  snapshot_ref['volume_id'])
            make_bootable = originating_vref.bootable
        except exception.CinderException as ex:
            LOG.exception(_("Failed fetching snapshot %(snapshot_id)s bootable"
                            " flag using the provided glance snapshot "
                            "%(snapshot_ref_id)s volume reference") %
                          {'snapshot_id': snapshot_id,
                           'snapshot_ref_id': snapshot_ref['volume_id']})
            raise exception.MetadataUpdateFailure(reason=ex)
        if make_bootable:
            self._handle_bootable_volume_glance_meta(context, volume_id,
                                                     snapshot_id=snapshot_id)
        return model_update

    def _enable_bootable_flag(self, context, volume_id):
        try:
            LOG.debug(_('Marking volume %s as bootable'), volume_id)
            self.db.volume_update(context, volume_id, {'bootable': True})
        except exception.CinderException as ex:
            LOG.exception(_("Failed updating volume %(volume_id)s bootable"
                            " flag to true") % {'volume_id': volume_id})
            raise exception.MetadataUpdateFailure(reason=ex)

    def _create_from_source_volume(self, context, volume_ref,
                                   source_volid, **kwargs):
        # NOTE(harlowja): if the source volume has disappeared this will be our
        # detection of that since this database call should fail.
        #
        # NOTE(harlowja): likely this is not the best place for this to happen
        # and we should have proper locks on the source volume while actions
        # that use the source volume are underway.
        srcvol_ref = self.db.volume_get(context, source_volid)
        model_update = self.driver.create_cloned_volume(volume_ref, srcvol_ref)
        # NOTE(harlowja): Subtasks would be useful here since after this
        # point the volume has already been created and further failures
        # will not destroy the volume (although they could in the future).
        if srcvol_ref.bootable:
            self._handle_bootable_volume_glance_meta(context, volume_ref['id'],
                                                     source_volid=source_volid)
        return model_update

    def _copy_image_to_volume(self, context, volume_ref,
                              image_id, image_location, image_service):
        """Downloads Glance image to the specified volume. """
        copy_image_to_volume = self.driver.copy_image_to_volume
        volume_id = volume_ref['id']
        LOG.debug(_("Attempting download of %(image_id)s (%(image_location)s)"
                    " to volume %(volume_id)s") %
                  {'image_id': image_id, 'volume_id': volume_id,
                   'image_location': image_location})
        try:
            copy_image_to_volume(context, volume_ref, image_service, image_id)
        except processutils.ProcessExecutionError as ex:
            LOG.error(_("Failed to copy image %(image_id)s to volume: "
                        "%(volume_id)s, error: %(error)s") %
                      {'volume_id': volume_id,
                       'error': ex.stderr, 'image_id': image_id})
            raise exception.ImageCopyFailure(reason=ex.stderr)
        except exception.ImageUnacceptable as ex:
            LOG.error(_("Failed to copy image to volume: %(volume_id)s, "
                        "error: %(error)s") % {'volume_id': volume_id,
                                               'error': ex})
            raise exception.ImageUnacceptable(ex)
        except Exception as ex:
            LOG.error(_("Failed to copy image %(image_id)s to "
                        "volume: %(volume_id)s, error: %(error)s") %
                      {'volume_id': volume_id, 'error': ex,
                       'image_id': image_id})
            if not isinstance(ex, exception.ImageCopyFailure):
                raise exception.ImageCopyFailure(reason=ex)
            else:
                raise

        LOG.debug(_("Downloaded image %(image_id)s (%(image_location)s)"
                    " to volume %(volume_id)s successfully") %
                  {'image_id': image_id, 'volume_id': volume_id,
                   'image_location': image_location})

    def _capture_volume_image_metadata(self, context, volume_id,
                                       image_id, image_meta):

        # Save some base attributes into the volume metadata
        base_metadata = {
            'image_id': image_id,
        }
        name = image_meta.get('name', None)
        if name:
            base_metadata['image_name'] = name

        # Save some more attributes into the volume metadata from the image
        # metadata
        for key in IMAGE_ATTRIBUTES:
            if key not in image_meta:
                continue
            value = image_meta.get(key, None)
            if value is not None:
                base_metadata[key] = value

        # Save all the image metadata properties into the volume metadata
        property_metadata = {}
        image_properties = image_meta.get('properties', {})
        for (key, value) in image_properties.items():
            if value is not None:
                property_metadata[key] = value

        # NOTE(harlowja): The best way for this to happen would be in bulk,
        # but that doesn't seem to exist (yet), so we go through one by one
        # which means we can have partial create/update failure.
        volume_metadata = dict(property_metadata)
        volume_metadata.update(base_metadata)
        LOG.debug(_("Creating volume glance metadata for volume %(volume_id)s"
                    " backed by image %(image_id)s with: %(vol_metadata)s") %
                  {'volume_id': volume_id, 'image_id': image_id,
                   'vol_metadata': volume_metadata})
        for (key, value) in volume_metadata.items():
            try:
                self.db.volume_glance_metadata_create(context, volume_id,
                                                      key, value)
            except exception.GlanceMetadataExists:
                pass

    def _create_from_image(self, context, volume_ref,
                           image_location, image_id, image_meta,
                           image_service, **kwargs):
        LOG.debug(_("Cloning %(volume_id)s from image %(image_id)s "
                    " at location %(image_location)s") %
                  {'volume_id': volume_ref['id'],
                   'image_location': image_location, 'image_id': image_id})
        # Create the volume from an image.
        #
        # NOTE (singn): two params need to be returned
        # dict containing provider_location for cloned volume
        # and clone status.
        model_update, cloned = self.driver.clone_image(
            volume_ref, image_location, image_id)
        if not cloned:
            # TODO(harlowja): what needs to be rolled back in the clone if this
            # volume create fails?? Likely this should be a subflow or broken
            # out task in the future. That will bring up the question of how
            # do we make said subflow/task which is only triggered in the
            # clone image 'path' resumable and revertable in the correct
            # manner.
            #
            # Create the volume and then download the image onto the volume.
            model_update = self.driver.create_volume(volume_ref)
            updates = dict(model_update or dict(), status='downloading')
            try:
                volume_ref = self.db.volume_update(context,
                                                   volume_ref['id'], updates)
            except exception.CinderException:
                LOG.exception(_("Failed updating volume %(volume_id)s with "
                                "%(updates)s") %
                              {'volume_id': volume_ref['id'],
                               'updates': updates})
            self._copy_image_to_volume(context, volume_ref,
                                       image_id, image_location, image_service)

        self._handle_bootable_volume_glance_meta(context, volume_ref['id'],
                                                 image_id=image_id,
                                                 image_meta=image_meta)
        return model_update

    def _create_raw_volume(self, context, volume_ref, **kwargs):
        return self.driver.create_volume(volume_ref)

    def __call__(self, context, volume_ref, volume_spec):
        volume_spec = dict(volume_spec)
        volume_id = volume_spec.pop('volume_id', None)

        # we can't do anything if the driver didn't init
        if not self.driver.initialized:
            driver_name = self.driver.__class__.__name__
            LOG.error(_("Unable to create volume. "
                        "Volume driver %s not initialized") % driver_name)

            # NOTE(flaper87): Set the error status before
            # raising any exception.
            self.db.volume_update(context, volume_id, dict(status='error'))
            raise exception.DriverNotInitialized()

        create_type = volume_spec.pop('type', None)
        create_functor = self._create_func_mapping.get(create_type)
        if not create_functor:
            raise exception.VolumeTypeNotFound(volume_type_id=create_type)

        if not volume_id:
            volume_id = volume_ref['id']
        LOG.info(_("Volume %(volume_id)s: being created using %(functor)s "
                   "with specification: %(volume_spec)s") %
                 {'volume_spec': volume_spec, 'volume_id': volume_id,
                  'functor': _make_pretty_name(create_functor)})

        # NOTE(vish): so we don't have to get volume from db again before
        # passing it to the driver.
        volume_ref['host'] = self.host

        # Call the given functor to make the volume.
        model_update = create_functor(context, volume_ref=volume_ref,
                                      **volume_spec)

        # Persist any model information provided on creation.
        try:
            if model_update:
                volume_ref = self.db.volume_update(context, volume_ref['id'],
                                                   model_update)
        except exception.CinderException as ex:
            # If somehow the update failed we want to ensure that the
            # failure is logged (but not try rescheduling since the volume at
            # this point has been created).
            if model_update:
                LOG.exception(_("Failed updating model of volume %(volume_id)s"
                                " with creation provided model %(model)s") %
                              {'volume_id': volume_id, 'model': model_update})
                raise exception.ExportFailure(reason=ex)

        # Persist any driver exported model information.
        model_update = None
        try:
            LOG.debug(_("Volume %s: creating export"), volume_ref['id'])
            model_update = self.driver.create_export(context, volume_ref)
            if model_update:
                self.db.volume_update(context, volume_ref['id'], model_update)
        except exception.CinderException as ex:
            # If somehow the read *or* create export failed we want to ensure
            # that the failure is logged (but not try rescheduling since
            # the volume at this point has been created).
            #
            # NOTE(harlowja): Notice that since the model_update is initially
            # empty, the only way it will still be empty is if there is no
            # model_update (which we don't care about) or there was an
            # model_update and updating failed.
            if model_update:
                LOG.exception(_("Failed updating model of volume %(volume_id)s"
                              " with driver provided model %(model)s") %
                              {'volume_id': volume_id, 'model': model_update})
                raise exception.ExportFailure(reason=ex)


class CreateVolumeOnFinishTask(NotifyVolumeActionTask):
    """On successful volume creation this will perform final volume actions.

    When a volume is created successfully it is expected that MQ notifications
    and database updates will occur to 'signal' to others that the volume is
    now ready for usage. This task does those notifications and updates in a
    reliable manner (not re-raising exceptions if said actions can not be
    triggered).

    Reversion strategy: N/A
    """

    def __init__(self, db, host, event_suffix):
        super(CreateVolumeOnFinishTask, self).__init__(db, host, event_suffix)
        self.requires.update(['volume_spec'])
        self.status_translation = {
            'migration_target_creating': 'migration_target',
        }

    def __call__(self, context, volume_ref, volume_spec):
        volume_id = volume_ref['id']
        new_status = self.status_translation.get(volume_spec.get('status'),
                                                 'available')
        update = {
            'status': new_status,
            'launched_at': timeutils.utcnow(),
        }
        try:
            # TODO(harlowja): is it acceptable to only log if this fails??
            # or are there other side-effects that this will cause if the
            # status isn't updated correctly (aka it will likely be stuck in
            # 'building' if this fails)??
            volume_ref = self.db.volume_update(context, volume_id, update)
            # Now use the parent to notify.
            super(CreateVolumeOnFinishTask, self).__call__(context, volume_ref)
        except exception.CinderException:
            LOG.exception(_("Failed updating volume %(volume_id)s with "
                            "%(update)s") % {'volume_id': volume_id,
                                             'update': update})
        # Even if the update fails, the volume is ready.
        msg = _("Volume %(volume_name)s (%(volume_id)s): created successfully")
        LOG.info(msg % {
            'volume_name': volume_spec['volume_name'],
            'volume_id': volume_id,
        })


def get_api_flow(scheduler_rpcapi, volume_rpcapi, db,
                 image_service,
                 az_check_functor,
                 create_what):
    """Constructs and returns the api entrypoint flow.

    This flow will do the following:

    1. Inject keys & values for dependent tasks.
    2. Extracts and validates the input keys & values.
    3. Reserves the quota (reverts quota on any failures).
    4. Creates the database entry.
    5. Commits the quota.
    6. Casts to volume manager or scheduler for further processing.
    """

    flow_name = ACTION.replace(":", "_") + "_api"
    api_flow = linear_flow.Flow(flow_name)

    # This injects the initial starting flow values into the workflow so that
    # the dependency order of the tasks provides/requires can be correctly
    # determined.
    api_flow.add(base.InjectTask(create_what, addons=[ACTION]))
    api_flow.add(ExtractVolumeRequestTask(image_service,
                                          az_check_functor))
    api_flow.add(QuotaReserveTask())
    v_uuid = api_flow.add(EntryCreateTask(db))
    api_flow.add(QuotaCommitTask())

    # If after commiting something fails, ensure we set the db to failure
    # before reverting any prior tasks.
    api_flow.add(OnFailureChangeStatusTask(db))

    # This will cast it out to either the scheduler or volume manager via
    # the rpc apis provided.
    api_flow.add(VolumeCastTask(scheduler_rpcapi, volume_rpcapi, db))

    # Note(harlowja): this will return the flow as well as the uuid of the
    # task which will produce the 'volume' database reference (since said
    # reference is returned to other callers in the api for further usage).
    return (flow_utils.attach_debug_listeners(api_flow), v_uuid)


def get_scheduler_flow(db, driver, request_spec=None, filter_properties=None,
                       volume_id=None, snapshot_id=None, image_id=None):

    """Constructs and returns the scheduler entrypoint flow.

    This flow will do the following:

    1. Inject keys & values for dependent tasks.
    2. Extracts a scheduler specification from the provided inputs.
    3. Attaches 2 activated only on *failure* tasks (one to update the db
       status and one to notify on the MQ of the failure that occured).
    4. Uses provided driver to to then select and continue processing of
       volume request.
    """

    flow_name = ACTION.replace(":", "_") + "_scheduler"
    scheduler_flow = linear_flow.Flow(flow_name)

    # This injects the initial starting flow values into the workflow so that
    # the dependency order of the tasks provides/requires can be correctly
    # determined.
    scheduler_flow.add(base.InjectTask({
        'request_spec': request_spec,
        'filter_properties': filter_properties,
        'volume_id': volume_id,
        'snapshot_id': snapshot_id,
        'image_id': image_id,
    }, addons=[ACTION]))

    # This will extract and clean the spec from the starting values.
    scheduler_flow.add(ExtractSchedulerSpecTask(db))

    # The decorator application here ensures that the method gets the right
    # requires attributes automatically by examining the underlying functions
    # arguments.

    @decorators.task
    def schedule_create_volume(context, request_spec, filter_properties):

        def _log_failure(cause):
            LOG.error(_("Failed to schedule_create_volume: %(cause)s") %
                      {'cause': cause})

        def _notify_failure(cause):
            """When scheduling fails send out a event that it failed."""
            topic = "scheduler.create_volume"
            payload = {
                'request_spec': request_spec,
                'volume_properties': request_spec.get('volume_properties', {}),
                'volume_id': volume_id,
                'state': 'error',
                'method': 'create_volume',
                'reason': cause,
            }
            try:
                publisher_id = notifier.publisher_id("scheduler")
                notifier.notify(context, publisher_id, topic, notifier.ERROR,
                                payload)
            except exception.CinderException:
                LOG.exception(_("Failed notifying on %(topic)s "
                                "payload %(payload)s") % {'topic': topic,
                                                          'payload': payload})

        try:
            driver.schedule_create_volume(context, request_spec,
                                          filter_properties)
        except exception.NoValidHost as e:
            # Not host found happened, notify on the scheduler queue and log
            # that this happened and set the volume to errored out and
            # *do not* reraise the error (since whats the point).
            _notify_failure(e)
            _log_failure(e)
            _error_out_volume(context, db, volume_id, reason=e)
        except Exception as e:
            # Some other error happened, notify on the scheduler queue and log
            # that this happened and set the volume to errored out and
            # *do* reraise the error.
            with excutils.save_and_reraise_exception():
                _notify_failure(e)
                _log_failure(e)
                _error_out_volume(context, db, volume_id, reason=e)

    scheduler_flow.add(schedule_create_volume)

    return flow_utils.attach_debug_listeners(scheduler_flow)


def get_manager_flow(db, driver, scheduler_rpcapi, host, volume_id,
                     request_spec=None, filter_properties=None,
                     allow_reschedule=True,
                     snapshot_id=None, image_id=None, source_volid=None,
                     reschedule_context=None):
    """Constructs and returns the manager entrypoint flow.

    This flow will do the following:

    1. Determines if rescheduling is enabled (ahead of time).
    2. Inject keys & values for dependent tasks.
    3. Selects 1 of 2 activated only on *failure* tasks (one to update the db
       status & notify or one to update the db status & notify & *reschedule*).
    4. Extracts a volume specification from the provided inputs.
    5. Notifies that the volume has start to be created.
    6. Creates a volume from the extracted volume specification.
    7. Attaches a on-success *only* task that notifies that the volume creation
       has ended and performs further database status updates.
    """

    flow_name = ACTION.replace(":", "_") + "_manager"
    volume_flow = linear_flow.Flow(flow_name)

    # Determine if we are allowed to reschedule since this affects how
    # failures will be handled.
    if not filter_properties:
        filter_properties = {}
    if not request_spec and allow_reschedule:
        LOG.debug(_("No request spec, will not reschedule"))
        allow_reschedule = False
    if not filter_properties.get('retry', None) and allow_reschedule:
        LOG.debug(_("No retry filter property or associated "
                    "retry info, will not reschedule"))
        allow_reschedule = False

    # This injects the initial starting flow values into the workflow so that
    # the dependency order of the tasks provides/requires can be correctly
    # determined.
    volume_flow.add(base.InjectTask({
        'filter_properties': filter_properties,
        'image_id': image_id,
        'request_spec': request_spec,
        'snapshot_id': snapshot_id,
        'source_volid': source_volid,
        'volume_id': volume_id,
    }, addons=[ACTION]))

    # We can actually just check if we should reschedule on failure ahead of
    # time instead of trying to determine this later, certain values are needed
    # to reschedule and without them we should just avoid rescheduling.
    if not allow_reschedule:
        # On failure ensure that we just set the volume status to error.
        LOG.debug(_("Retry info not present, will not reschedule"))
        volume_flow.add(OnFailureChangeStatusTask(db))
    else:
        volume_flow.add(OnFailureRescheduleTask(reschedule_context,
                                                db, scheduler_rpcapi))

    volume_flow.add(ExtractVolumeSpecTask(db))
    volume_flow.add(NotifyVolumeActionTask(db, host, "create.start"))
    volume_flow.add(CreateVolumeFromSpecTask(db, host, driver))
    volume_flow.add(CreateVolumeOnFinishTask(db, host, "create.end"))

    return flow_utils.attach_debug_listeners(volume_flow)
