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


from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils
from oslo_utils import units
import taskflow.engines
from taskflow.patterns import linear_flow
from taskflow.types import failure as ft

from cinder import exception
from cinder import flow_utils
from cinder.i18n import _, _LE, _LW
from cinder import objects
from cinder import policy
from cinder import quota
from cinder import utils
from cinder.volume.flows import common
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

ACTION = 'volume:create'
CONF = cfg.CONF
GB = units.Gi
QUOTAS = quota.QUOTAS

# Only in these 'sources' status can we attempt to create a volume from a
# source volume or a source snapshot, other status states we can not create
# from, 'error' being the common example.
SNAPSHOT_PROCEED_STATUS = ('available',)
SRC_VOL_PROCEED_STATUS = ('available', 'in-use',)
REPLICA_PROCEED_STATUS = ('active', 'active-stopped',)
CG_PROCEED_STATUS = ('available', 'creating',)
CGSNAPSHOT_PROCEED_STATUS = ('available',)


class ExtractVolumeRequestTask(flow_utils.CinderTask):
    """Processes an api request values into a validated set of values.

    This tasks responsibility is to take in a set of inputs that will form
    a potential volume request and validates those values against a set of
    conditions and/or translates those values into a valid set and then returns
    the validated/translated values for use by other tasks.

    Reversion strategy: N/A
    """

    # This task will produce the following outputs (said outputs can be
    # saved to durable storage in the future so that the flow can be
    # reconstructed elsewhere and continued).
    default_provides = set(['availability_zone', 'size', 'snapshot_id',
                            'source_volid', 'volume_type', 'volume_type_id',
                            'encryption_key_id', 'source_replicaid',
                            'consistencygroup_id', 'cgsnapshot_id',
                            'qos_specs'])

    def __init__(self, image_service, availability_zones, **kwargs):
        super(ExtractVolumeRequestTask, self).__init__(addons=[ACTION],
                                                       **kwargs)
        self.image_service = image_service
        self.availability_zones = availability_zones

    @staticmethod
    def _extract_resource(resource, allowed_vals, exc, resource_name,
                          props=('status',)):
        """Extracts the resource id from the provided resource.

        This method validates the input resource dict and checks that the
        properties which names are passed in `props` argument match
        corresponding lists in `allowed` argument. In case of mismatch
        exception of type exc is raised.

        :param resource: Resource dict.
        :param allowed_vals: Tuple of allowed values lists.
        :param exc: Exception type to raise.
        :param resource_name: Name of resource - used to construct log message.
        :param props: Tuple of resource properties names to validate.
        :return: Id of a resource.
        """

        resource_id = None
        if resource:
            for prop, allowed_states in zip(props, allowed_vals):
                if resource[prop] not in allowed_states:
                    msg = _("Originating %(res)s %(prop)s must be one of "
                            "'%(vals)s' values")
                    msg = msg % {'res': resource_name,
                                 'prop': prop,
                                 'vals': ', '.join(allowed_states)}
                    # TODO(harlowja): what happens if the status changes after
                    # this initial resource status check occurs??? Seems like
                    # someone could delete the resource after this check passes
                    # but before the volume is officially created?
                    raise exc(reason=msg)
                resource_id = resource['id']
        return resource_id

    def _extract_consistencygroup(self, consistencygroup):
        return self._extract_resource(consistencygroup, (CG_PROCEED_STATUS,),
                                      exception.InvalidConsistencyGroup,
                                      'consistencygroup')

    def _extract_cgsnapshot(self, cgsnapshot):
        return self._extract_resource(cgsnapshot, (CGSNAPSHOT_PROCEED_STATUS,),
                                      exception.InvalidCgSnapshot,
                                      'CGSNAPSHOT')

    def _extract_snapshot(self, snapshot):
        return self._extract_resource(snapshot, (SNAPSHOT_PROCEED_STATUS,),
                                      exception.InvalidSnapshot, 'snapshot')

    def _extract_source_volume(self, source_volume):
        return self._extract_resource(source_volume, (SRC_VOL_PROCEED_STATUS,),
                                      exception.InvalidVolume, 'source volume')

    def _extract_source_replica(self, source_replica):
        return self._extract_resource(source_replica, (SRC_VOL_PROCEED_STATUS,
                                                       REPLICA_PROCEED_STATUS),
                                      exception.InvalidVolume,
                                      'replica', ('status',
                                                  'replication_status'))

    @staticmethod
    def _extract_size(size, source_volume, snapshot):
        """Extracts and validates the volume size.

        This function will validate or when not provided fill in the provided
        size variable from the source_volume or snapshot and then does
        validation on the size that is found and returns said validated size.
        """

        def validate_snap_size(size):
            if snapshot and size < snapshot.volume_size:
                msg = _("Volume size '%(size)s'GB cannot be smaller than"
                        " the snapshot size %(snap_size)sGB. "
                        "They must be >= original snapshot size.")
                msg = msg % {'size': size,
                             'snap_size': snapshot.volume_size}
                raise exception.InvalidInput(reason=msg)

        def validate_source_size(size):
            if source_volume and size < source_volume['size']:
                msg = _("Volume size '%(size)s'GB cannot be smaller than "
                        "original volume size  %(source_size)sGB. "
                        "They must be >= original volume size.")
                msg = msg % {'size': size,
                             'source_size': source_volume['size']}
                raise exception.InvalidInput(reason=msg)

        def validate_int(size):
            if not isinstance(size, int) or size <= 0:
                msg = _("Volume size '%(size)s' must be an integer and"
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
            size = snapshot.volume_size

        size = utils.as_int(size)
        LOG.debug("Validating volume '%(size)s' using %(functors)s" %
                  {'size': size,
                   'functors': ", ".join([common.make_pretty_name(func)
                                          for func in validator_functors])})
        for func in validator_functors:
            func(size)
        return size

    def _check_image_metadata(self, context, image_id, size):
        """Checks image existence and validates that the image metadata."""

        # Check image existence
        if image_id is None:
            return

        # NOTE(harlowja): this should raise an error if the image does not
        # exist, this is expected as it signals that the image_id is missing.
        image_meta = self.image_service.show(context, image_id)

        # check whether image is active
        if image_meta['status'] != 'active':
            msg = _('Image %(image_id)s is not active.')\
                % {'image_id': image_id}
            raise exception.InvalidInput(reason=msg)

        # Check image size is not larger than volume size.
        image_size = utils.as_int(image_meta['size'], quiet=False)
        image_size_in_gb = (image_size + GB - 1) // GB
        if image_size_in_gb > size:
            msg = _('Size of specified image %(image_size)sGB'
                    ' is larger than volume size %(volume_size)sGB.')
            msg = msg % {'image_size': image_size_in_gb, 'volume_size': size}
            raise exception.InvalidInput(reason=msg)

        # Check image min_disk requirement is met for the particular volume
        min_disk = image_meta.get('min_disk', 0)
        if size < min_disk:
            msg = _('Volume size %(volume_size)sGB cannot be smaller'
                    ' than the image minDisk size %(min_disk)sGB.')
            msg = msg % {'volume_size': size, 'min_disk': min_disk}
            raise exception.InvalidInput(reason=msg)

    @staticmethod
    def _check_metadata_properties(metadata=None):
        """Checks that the volume metadata properties are valid."""

        if not metadata:
            metadata = {}

        for (k, v) in metadata.items():
            if len(k) == 0:
                msg = _("Metadata property key blank")
                LOG.warning(msg)
                raise exception.InvalidVolumeMetadata(reason=msg)
            if len(k) > 255:
                msg = _("Metadata property key %s greater than 255 "
                        "characters") % k
                LOG.warning(msg)
                raise exception.InvalidVolumeMetadataSize(reason=msg)
            if len(v) > 255:
                msg = _("Metadata property key %s value greater than"
                        " 255 characters") % k
                LOG.warning(msg)
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
                # For backwards compatibility use the storage_availability_zone
                availability_zone = CONF.storage_availability_zone

        if availability_zone not in self.availability_zones:
            if CONF.allow_availability_zone_fallback:
                original_az = availability_zone
                availability_zone = (
                    CONF.default_availability_zone or
                    CONF.storage_availability_zone)
                LOG.warning(_LW("Availability zone '%(s_az)s' "
                                "not found, falling back to "
                                "'%(s_fallback_az)s'."),
                            {'s_az': original_az,
                             's_fallback_az': availability_zone})
            else:
                msg = _("Availability zone '%(s_az)s' is invalid.")
                msg = msg % {'s_az': availability_zone}
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
                               snapshot, source_volume):
        encryption_key_id = None
        if volume_types.is_encrypted(context, volume_type_id):
            if snapshot is not None:  # creating from snapshot
                encryption_key_id = snapshot['encryption_key_id']
            elif source_volume is not None:  # cloning volume
                encryption_key_id = source_volume['encryption_key_id']

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

    def _get_volume_type_id(self, volume_type, source_volume, snapshot):
        if not volume_type and source_volume:
            return source_volume['volume_type_id']
        elif snapshot is not None:
            if volume_type:
                current_volume_type_id = volume_type.get('id')
                if current_volume_type_id != snapshot['volume_type_id']:
                    msg = _LW("Volume type will be changed to "
                              "be the same as the source volume.")
                    LOG.warning(msg)
            return snapshot['volume_type_id']
        else:
            return volume_type.get('id')

    def execute(self, context, size, snapshot, image_id, source_volume,
                availability_zone, volume_type, metadata, key_manager,
                source_replica, consistencygroup, cgsnapshot):

        utils.check_exclusive_options(snapshot=snapshot,
                                      imageRef=image_id,
                                      source_volume=source_volume)
        policy.enforce_action(context, ACTION)

        # TODO(harlowja): what guarantee is there that the snapshot or source
        # volume will remain available after we do this initial verification??
        snapshot_id = self._extract_snapshot(snapshot)
        source_volid = self._extract_source_volume(source_volume)
        source_replicaid = self._extract_source_replica(source_replica)
        size = self._extract_size(size, source_volume, snapshot)
        consistencygroup_id = self._extract_consistencygroup(consistencygroup)
        cgsnapshot_id = self._extract_cgsnapshot(cgsnapshot)

        self._check_image_metadata(context, image_id, size)

        availability_zone = self._extract_availability_zone(availability_zone,
                                                            snapshot,
                                                            source_volume)

        # TODO(joel-coffman): This special handling of snapshots to ensure that
        # their volume type matches the source volume is too convoluted. We
        # should copy encryption metadata from the encrypted volume type to the
        # volume upon creation and propagate that information to each snapshot.
        # This strategy avoids any dependency upon the encrypted volume type.
        def_vol_type = volume_types.get_default_volume_type()
        if not volume_type and not source_volume and not snapshot:
            volume_type = def_vol_type

        # When creating a clone of a replica (replication test), we can't
        # use the volume type of the replica, therefore, we use the default.
        # NOTE(ronenkat): this assumes the default type is not replicated.
        if source_replicaid:
            volume_type = def_vol_type

        volume_type_id = self._get_volume_type_id(volume_type,
                                                  source_volume, snapshot)

        if image_id and volume_types.is_encrypted(context, volume_type_id):
            msg = _('Create encrypted volumes with type %(type)s '
                    'from image %(image)s is not supported.')
            msg = msg % {'type': volume_type_id,
                         'image': image_id, }
            raise exception.InvalidInput(reason=msg)

        encryption_key_id = self._get_encryption_key_id(key_manager,
                                                        context,
                                                        volume_type_id,
                                                        snapshot,
                                                        source_volume)

        specs = {}
        if volume_type_id:
            qos_specs = volume_types.get_volume_type_qos_specs(volume_type_id)
            if qos_specs['qos_specs']:
                specs = qos_specs['qos_specs'].get('specs', {})
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
            'source_replicaid': source_replicaid,
            'consistencygroup_id': consistencygroup_id,
            'cgsnapshot_id': cgsnapshot_id,
        }


class EntryCreateTask(flow_utils.CinderTask):
    """Creates an entry for the given volume creation in the database.

    Reversion strategy: remove the volume_id created from the database.
    """

    default_provides = set(['volume_properties', 'volume_id', 'volume'])

    def __init__(self, db):
        requires = ['availability_zone', 'description', 'metadata',
                    'name', 'reservations', 'size', 'snapshot_id',
                    'source_volid', 'volume_type_id', 'encryption_key_id',
                    'source_replicaid', 'consistencygroup_id',
                    'cgsnapshot_id', 'multiattach', 'qos_specs']
        super(EntryCreateTask, self).__init__(addons=[ACTION],
                                              requires=requires)
        self.db = db

    def execute(self, context, optional_args, **kwargs):
        """Creates a database entry for the given inputs and returns details.

        Accesses the database and creates a new entry for the to be created
        volume using the given volume properties which are extracted from the
        input kwargs (and associated requirements this task needs). These
        requirements should be previously satisfied and validated by a
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
            'replication_status': 'disabled',
            'multiattach': kwargs.pop('multiattach'),
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
            # just a plain dictionary so that's why we are storing this here.
            #
            # In the future where this task results can be serialized and
            # restored automatically for continued running we will need to
            # resolve the serialization & recreation of this object since raw
            # sqlalchemy objects can't be serialized.
            'volume': volume,
        }

    def revert(self, context, result, optional_args, **kwargs):
        if isinstance(result, ft.Failure):
            # We never produced a result and therefore can't destroy anything.
            return

        if optional_args['is_quota_committed']:
            # If quota got commited we shouldn't rollback as the volume has
            # already been created and the quota has already been absorbed.
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
            LOG.exception(_LE("Failed destroying volume entry %s"), vol_id)


class QuotaReserveTask(flow_utils.CinderTask):
    """Reserves a single volume with the given size & the given volume type.

    Reversion strategy: rollback the quota reservation.

    Warning Warning: if the process that is running this reserve and commit
    process fails (or is killed before the quota is rolled back or committed
    it does appear like the quota will never be rolled back). This makes
    software upgrades hard (inflight operations will need to be stopped or
    allowed to complete before the upgrade can occur). *In the future* when
    taskflow has persistence built-in this should be easier to correct via
    an automated or manual process.
    """

    default_provides = set(['reservations'])

    def __init__(self):
        super(QuotaReserveTask, self).__init__(addons=[ACTION])

    def execute(self, context, size, volume_type_id, optional_args):
        try:
            values = {'per_volume_gigabytes': size}
            QUOTAS.limit_check(context, project_id=context.project_id,
                               **values)
        except exception.OverQuota as e:
            quotas = e.kwargs['quotas']
            raise exception.VolumeSizeExceedsLimit(
                size=size, limit=quotas['per_volume_gigabytes'])

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
                return usages[name]['reserved'] + usages[name]['in_use']

            def _get_over(name):
                for over in overs:
                    if name in over:
                        return over
                return None

            over_name = _get_over('gigabytes')
            exceeded_vol_limit_name = _get_over('volumes')
            if over_name:
                msg = _LW("Quota exceeded for %(s_pid)s, tried to create "
                          "%(s_size)sG volume (%(d_consumed)dG "
                          "of %(d_quota)dG already consumed)")
                LOG.warning(msg, {'s_pid': context.project_id,
                                  's_size': size,
                                  'd_consumed': _consumed(over_name),
                                  'd_quota': quotas[over_name]})
                raise exception.VolumeSizeExceedsAvailableQuota(
                    name=over_name,
                    requested=size,
                    consumed=_consumed(over_name),
                    quota=quotas[over_name])
            elif exceeded_vol_limit_name:
                msg = _LW("Quota %(s_name)s exceeded for %(s_pid)s, tried "
                          "to create volume (%(d_consumed)d volume(s) "
                          "already consumed).")
                LOG.warning(msg,
                            {'s_name': exceeded_vol_limit_name,
                             's_pid': context.project_id,
                             'd_consumed':
                             _consumed(exceeded_vol_limit_name)})
                raise exception.VolumeLimitExceeded(
                    allowed=quotas[exceeded_vol_limit_name],
                    name=exceeded_vol_limit_name)
            else:
                # If nothing was reraised, ensure we reraise the initial error
                raise

    def revert(self, context, result, optional_args, **kwargs):
        # We never produced a result and therefore can't destroy anything.
        if isinstance(result, ft.Failure):
            return

        if optional_args['is_quota_committed']:
            # The reservations have already been committed and can not be
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
            LOG.exception(_LE("Failed rolling back quota for"
                              " %s reservations"), reservations)


class QuotaCommitTask(flow_utils.CinderTask):
    """Commits the reservation.

    Reversion strategy: N/A (the rollback will be handled by the task that did
    the initial reservation (see: QuotaReserveTask).

    Warning Warning: if the process that is running this reserve and commit
    process fails (or is killed before the quota is rolled back or committed
    it does appear like the quota will never be rolled back). This makes
    software upgrades hard (inflight operations will need to be stopped or
    allowed to complete before the upgrade can occur). *In the future* when
    taskflow has persistence built-in this should be easier to correct via
    an automated or manual process.
    """

    def __init__(self):
        super(QuotaCommitTask, self).__init__(addons=[ACTION])

    def execute(self, context, reservations, volume_properties,
                optional_args):
        QUOTAS.commit(context, reservations)
        # updating is_quota_committed attribute of optional_args dictionary
        optional_args['is_quota_committed'] = True
        return {'volume_properties': volume_properties}

    def revert(self, context, result, **kwargs):
        # We never produced a result and therefore can't destroy anything.
        if isinstance(result, ft.Failure):
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
            LOG.exception(_LE("Failed to update quota for deleting "
                              "volume: %s"), volume['id'])


class VolumeCastTask(flow_utils.CinderTask):
    """Performs a volume create cast to the scheduler or to the volume manager.

    This will signal a transition of the api workflow to another child and/or
    related workflow on another component.

    Reversion strategy: rollback source volume status and error out newly
    created volume.
    """

    def __init__(self, scheduler_rpcapi, volume_rpcapi, db):
        requires = ['image_id', 'scheduler_hints', 'snapshot_id',
                    'source_volid', 'volume_id', 'volume_type',
                    'volume_properties', 'source_replicaid',
                    'consistencygroup_id', 'cgsnapshot_id', ]
        super(VolumeCastTask, self).__init__(addons=[ACTION],
                                             requires=requires)
        self.volume_rpcapi = volume_rpcapi
        self.scheduler_rpcapi = scheduler_rpcapi
        self.db = db

    def _cast_create_volume(self, context, request_spec, filter_properties):
        source_volid = request_spec['source_volid']
        source_replicaid = request_spec['source_replicaid']
        volume_id = request_spec['volume_id']
        snapshot_id = request_spec['snapshot_id']
        image_id = request_spec['image_id']
        cgroup_id = request_spec['consistencygroup_id']
        host = None
        cgsnapshot_id = request_spec['cgsnapshot_id']

        if cgroup_id:
            cgroup = objects.ConsistencyGroup.get_by_id(context, cgroup_id)
            host = cgroup.host
        elif snapshot_id and CONF.snapshot_same_host:
            # NOTE(Rongze Zhu): A simple solution for bug 1008866.
            #
            # If snapshot_id is set and CONF.snapshot_same_host is True, make
            # the call create volume directly to the volume host where the
            # snapshot resides instead of passing it through the scheduler, so
            # snapshot can be copied to the new volume.
            snapshot = objects.Snapshot.get_by_id(context, snapshot_id)
            source_volume_ref = self.db.volume_get(context, snapshot.volume_id)
            host = source_volume_ref['host']
        elif source_volid:
            source_volume_ref = self.db.volume_get(context, source_volid)
            host = source_volume_ref['host']
        elif source_replicaid:
            source_volume_ref = self.db.volume_get(context, source_replicaid)
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
            if not cgsnapshot_id:
                self.volume_rpcapi.create_volume(
                    context,
                    volume_ref,
                    volume_ref['host'],
                    request_spec,
                    filter_properties,
                    allow_reschedule=False)

    def execute(self, context, **kwargs):
        scheduler_hints = kwargs.pop('scheduler_hints', None)
        request_spec = kwargs.copy()
        filter_properties = {}
        if scheduler_hints:
            filter_properties['scheduler_hints'] = scheduler_hints
        self._cast_create_volume(context, request_spec, filter_properties)

    def revert(self, context, result, flow_failures, **kwargs):
        if isinstance(result, ft.Failure):
            return

        # Restore the source volume status and set the volume to error status.
        volume_id = kwargs['volume_id']
        common.restore_source_status(context, self.db, kwargs)
        common.error_out_volume(context, self.db, volume_id)
        LOG.error(_LE("Volume %s: create failed"), volume_id)
        exc_info = False
        if all(flow_failures[-1].exc_info):
            exc_info = flow_failures[-1].exc_info
        LOG.error(_LE('Unexpected build error:'), exc_info=exc_info)


def get_flow(db_api, image_service_api, availability_zones, create_what,
             scheduler_rpcapi=None, volume_rpcapi=None):
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

    api_flow.add(ExtractVolumeRequestTask(
        image_service_api,
        availability_zones,
        rebind={'size': 'raw_size',
                'availability_zone': 'raw_availability_zone',
                'volume_type': 'raw_volume_type'}))
    api_flow.add(QuotaReserveTask(),
                 EntryCreateTask(db_api),
                 QuotaCommitTask())

    if scheduler_rpcapi and volume_rpcapi:
        # This will cast it out to either the scheduler or volume manager via
        # the rpc apis provided.
        api_flow.add(VolumeCastTask(scheduler_rpcapi, volume_rpcapi, db_api))

    # Now load (but do not run) the flow using the provided initial data.
    return taskflow.engines.load(api_flow, store=create_what)
