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

from typing import Any, Dict, List, Optional, Tuple, Type, Union  # noqa: H301

from oslo_config import cfg
from oslo_log import log as logging
import taskflow.engines
from taskflow.patterns import linear_flow
from taskflow.types import failure as ft

from cinder import context
from cinder import exception
from cinder import flow_utils
from cinder.i18n import _
from cinder.image import glance
from cinder import objects
from cinder.objects import fields
from cinder.policies import volumes as policy
from cinder import quota
from cinder import quota_utils
from cinder import utils
from cinder.volume.flows import common
from cinder.volume import volume_types
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)

ACTION = 'volume:create'
CONF = cfg.CONF
QUOTAS = quota.QUOTAS

# Only in these 'sources' status can we attempt to create a volume from a
# source volume or a source snapshot, other status states we can not create
# from, 'error' being the common example.
SNAPSHOT_PROCEED_STATUS = (fields.SnapshotStatus.AVAILABLE,)
SRC_VOL_PROCEED_STATUS = ('available', 'in-use',)
REPLICA_PROCEED_STATUS = ('active', 'active-stopped',)
CG_PROCEED_STATUS = ('available', 'creating',)
CGSNAPSHOT_PROCEED_STATUS = ('available',)
GROUP_PROCEED_STATUS = ('available', 'creating',)
BACKUP_PROCEED_STATUS = (fields.BackupStatus.AVAILABLE,)


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
    default_provides = set(['size', 'snapshot_id',
                            'source_volid', 'volume_type', 'volume_type_id',
                            'encryption_key_id', 'consistencygroup_id',
                            'cgsnapshot_id', 'qos_specs', 'group_id',
                            'refresh_az', 'backup_id', 'availability_zones',
                            'multiattach'])

    def __init__(self,
                 image_service: glance.GlanceImageService,
                 availability_zones, **kwargs) -> None:
        super(ExtractVolumeRequestTask, self).__init__(addons=[ACTION],
                                                       **kwargs)
        self.image_service = image_service
        self.availability_zones = availability_zones

    @staticmethod
    def _extract_resource(resource: Optional[dict],
                          allowed_vals: Tuple[Tuple[str, ...]],
                          exc: Type[exception.CinderException],
                          resource_name: str,
                          props: Tuple[str] = ('status',)) -> Optional[str]:
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

    def _extract_consistencygroup(
            self,
            consistencygroup: Optional[dict]) -> Optional[str]:
        return self._extract_resource(consistencygroup, (CG_PROCEED_STATUS,),
                                      exception.InvalidConsistencyGroup,
                                      'consistencygroup')

    def _extract_group(
            self,
            group: Optional[dict]) -> Optional[str]:
        return self._extract_resource(group, (GROUP_PROCEED_STATUS,),
                                      exception.InvalidGroup,
                                      'group')

    def _extract_cgsnapshot(
            self,
            cgsnapshot: Optional[dict]) -> Optional[str]:
        return self._extract_resource(cgsnapshot, (CGSNAPSHOT_PROCEED_STATUS,),
                                      exception.InvalidCgSnapshot,
                                      'CGSNAPSHOT')

    def _extract_snapshot(
            self,
            snapshot: Optional[dict]) -> Optional[str]:
        return self._extract_resource(snapshot, (SNAPSHOT_PROCEED_STATUS,),
                                      exception.InvalidSnapshot, 'snapshot')

    def _extract_source_volume(
            self,
            source_volume: Optional[dict]) -> Optional[str]:
        return self._extract_resource(source_volume, (SRC_VOL_PROCEED_STATUS,),
                                      exception.InvalidVolume, 'source volume')

    def _extract_backup(
            self,
            backup: Optional[dict]) -> Optional[str]:
        return self._extract_resource(backup, (BACKUP_PROCEED_STATUS,),
                                      exception.InvalidBackup,
                                      'backup')

    @staticmethod
    def _extract_size(size: int,
                      source_volume: Optional[objects.Volume],
                      snapshot: Optional[objects.Snapshot],
                      backup: Optional[objects.Backup]) -> int:
        """Extracts and validates the volume size.

        This function will validate or when not provided fill in the provided
        size variable from the source_volume or snapshot and then does
        validation on the size that is found and returns said validated size.
        """

        def validate_snap_size(size: int) -> None:
            if snapshot and size < snapshot.volume_size:
                msg = _("Volume size '%(size)s'GB cannot be smaller than"
                        " the snapshot size %(snap_size)sGB. "
                        "They must be >= original snapshot size.")
                msg = msg % {'size': size,
                             'snap_size': snapshot.volume_size}
                raise exception.InvalidInput(reason=msg)

        def validate_source_size(size: int) -> None:
            if source_volume and size < source_volume['size']:
                msg = _("Volume size '%(size)s'GB cannot be smaller than "
                        "original volume size  %(source_size)sGB. "
                        "They must be >= original volume size.")
                msg = msg % {'size': size,
                             'source_size': source_volume['size']}
                raise exception.InvalidInput(reason=msg)

        def validate_backup_size(size: int) -> None:
            if backup and size < backup['size']:
                msg = _("Volume size %(size)sGB cannot be smaller than "
                        "the backup size %(backup_size)sGB. "
                        "It must be >= backup size.")
                msg = msg % {'size': size,
                             'backup_size': backup['size']}
                raise exception.InvalidInput(reason=msg)

        def validate_int(size: int) -> None:
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
        elif backup:
            validator_functors.append(validate_backup_size)

        # If the size is not provided then try to provide it.
        if not size and source_volume:
            size = source_volume['size']
        elif not size and snapshot:
            size = snapshot.volume_size
        elif not size and backup:
            size = backup['size']

        size = utils.as_int(size)
        LOG.debug("Validating volume size '%(size)s' using %(functors)s",
                  {'size': size,
                   'functors': ", ".join([common.make_pretty_name(func)
                                          for func in validator_functors])})
        for func in validator_functors:
            func(size)
        return size

    def _get_image_metadata(self,
                            context: context.RequestContext,
                            image_id: Optional[str],
                            size: int) -> Optional[Dict[str, Any]]:
        """Checks image existence and validates the image metadata.

        Returns: image metadata or None
        """

        # Check image existence
        if image_id is None:
            return None

        # NOTE(harlowja): this should raise an error if the image does not
        # exist, this is expected as it signals that the image_id is missing.
        image_meta = self.image_service.show(context, image_id)

        volume_utils.check_image_metadata(image_meta, size)

        return image_meta

    def _extract_availability_zones(
            self,
            availability_zone: Optional[str],
            snapshot,
            source_volume,
            group: Optional[dict],
            volume_type: Dict[str, Any] = None) -> Tuple[List[str], bool]:
        """Extracts and returns a validated availability zone list.

        This function will extract the availability zone (if not provided) from
        the snapshot or source_volume and then performs a set of validation
        checks on the provided or extracted availability zone and then returns
        the validated availability zone.
        """
        refresh_az = False
        type_azs = volume_utils.extract_availability_zones_from_volume_type(
            volume_type)
        type_az_configured = type_azs is not None
        if type_az_configured:
            assert type_azs is not None
            safe_azs = list(
                set(type_azs).intersection(self.availability_zones))
            if not safe_azs:
                raise exception.InvalidTypeAvailabilityZones(az=type_azs)
        else:
            safe_azs = self.availability_zones

        # If the volume will be created in a group, it should be placed in
        # in same availability zone as the group.
        if group:
            try:
                availability_zone = group['availability_zone']
            except (TypeError, KeyError):
                pass

        # Try to extract the availability zone from the corresponding snapshot
        # or source volume if either is valid so that we can be in the same
        # availability zone as the source.
        if availability_zone is None:
            if snapshot:
                try:
                    availability_zone = snapshot['volume']['availability_zone']
                except (TypeError, KeyError):
                    pass
            if source_volume:
                try:
                    availability_zone = source_volume['availability_zone']
                except (TypeError, KeyError):
                    pass

        if availability_zone is None and not type_az_configured:
            if CONF.default_availability_zone:
                availability_zone = CONF.default_availability_zone
            else:
                # For backwards compatibility use the storage_availability_zone
                availability_zone = CONF.storage_availability_zone

        if availability_zone and availability_zone not in safe_azs:
            refresh_az = True
            if CONF.allow_availability_zone_fallback:
                original_az = availability_zone
                availability_zone = (
                    CONF.default_availability_zone or
                    CONF.storage_availability_zone)
                LOG.warning("Availability zone '%(s_az)s' "
                            "not found, falling back to "
                            "'%(s_fallback_az)s'.",
                            {'s_az': original_az,
                             's_fallback_az': availability_zone})
            else:
                raise exception.InvalidAvailabilityZone(az=availability_zone)

        # If the configuration only allows cloning to the same availability
        # zone then we need to enforce that.
        if availability_zone and CONF.cloned_volume_same_az:
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

        if availability_zone:
            return [availability_zone], refresh_az
        else:
            return safe_azs, refresh_az

    def _get_encryption_key_id(
            self,
            key_manager,
            context: context.RequestContext,
            volume_type_id: str,
            snapshot: Optional[objects.Snapshot],
            source_volume: Optional[objects.Volume],
            image_metadata: Optional[Dict[str, Any]]) -> Optional[str]:
        if volume_types.is_encrypted(context, volume_type_id):
            encryption_key_id = None

            if snapshot is not None:  # creating from snapshot
                encryption_key_id = snapshot['encryption_key_id']
            elif source_volume is not None:  # cloning volume
                encryption_key_id = source_volume['encryption_key_id']
            elif image_metadata is not None:
                # creating from image
                encryption_key_id = image_metadata.get(
                    'cinder_encryption_key_id')

            # NOTE(joel-coffman): References to the encryption key should *not*
            # be copied because the key is deleted when the volume is deleted.
            # Clone the existing key and associate a separate -- but
            # identical -- key with each volume.
            new_encryption_key_id: Optional[str]
            if encryption_key_id is not None:
                new_encryption_key_id = volume_utils.clone_encryption_key(
                    context,
                    key_manager,
                    encryption_key_id)
            else:
                new_encryption_key_id = volume_utils.create_encryption_key(
                    context,
                    key_manager,
                    volume_type_id)

            return new_encryption_key_id
        else:
            return None

    @staticmethod
    def _get_volume_type(
            context: context.RequestContext,
            volume_type: Optional[Any],
            source_volume: Optional[objects.Volume],
            snapshot: Optional[objects.Snapshot],
            image_volume_type_id: Optional[str]) -> objects.VolumeType:
        """Returns a volume_type object or raises.  Never returns None."""
        if volume_type:
            return volume_type

        identifier = None
        if source_volume:
            identifier = {'source': 'volume',
                          'id': source_volume['volume_type_id']}
        elif snapshot:
            identifier = {'source': 'snapshot',
                          'id': snapshot['volume_type_id']}
        elif image_volume_type_id:
            identifier = {'source': 'image',
                          'id': image_volume_type_id}
        if identifier:
            try:
                return objects.VolumeType.get_by_name_or_id(
                    context, identifier['id'])
            except (exception.VolumeTypeNotFound,
                    exception.VolumeTypeNotFoundByName,
                    exception.InvalidVolumeType):
                LOG.exception("Failed to find volume type from "
                              "source %(source)s, identifier %(id)s",
                              identifier)
                raise

        # otherwise, use the default volume type
        return volume_types.get_default_volume_type(context)

    def execute(self,
                context: context.RequestContext,
                size: int,
                snapshot: Optional[dict],
                image_id: Optional[str],
                source_volume: Optional[dict],
                availability_zone: Optional[str],
                volume_type,
                metadata,
                key_manager,
                consistencygroup,
                cgsnapshot,
                group,
                group_snapshot,
                backup: Optional[dict],
                multiattach: bool = False) -> Dict[str, Any]:

        utils.check_exclusive_options(snapshot=snapshot,
                                      imageRef=image_id,
                                      source_volume=source_volume,
                                      backup=backup)
        context.authorize(policy.CREATE_POLICY)

        # TODO(harlowja): what guarantee is there that the snapshot or source
        # volume will remain available after we do this initial verification??
        snapshot_id = self._extract_snapshot(snapshot)
        source_volid = self._extract_source_volume(source_volume)
        backup_id = self._extract_backup(backup)
        size = self._extract_size(size, source_volume, snapshot, backup)
        consistencygroup_id = self._extract_consistencygroup(consistencygroup)
        cgsnapshot_id = self._extract_cgsnapshot(cgsnapshot)
        group_id = self._extract_group(group)

        image_meta = self._get_image_metadata(context,
                                              image_id,
                                              size)

        image_properties = image_meta.get(
            'properties', {}) if image_meta else {}
        image_volume_type = image_properties.get(
            'cinder_img_volume_type', None) if image_properties else None

        volume_type = self._get_volume_type(
            context, volume_type, source_volume, snapshot, image_volume_type)

        volume_type_id = volume_type.get('id') if volume_type else None

        availability_zones, refresh_az = self._extract_availability_zones(
            availability_zone, snapshot, source_volume, group,
            volume_type=volume_type)

        encryption_key_id = self._get_encryption_key_id(
            key_manager,
            context,
            volume_type_id,
            snapshot,
            source_volume,
            image_meta)   # new key id that's been cloned already

        if volume_type_id:
            volume_type = objects.VolumeType.get_by_name_or_id(
                context, volume_type_id)
            extra_specs = volume_type.get('extra_specs', {})
            # NOTE(tommylikehu): Although the parameter `multiattach` from
            # create volume API is deprecated now, we still need to consider
            # it when multiattach is not enabled in volume type.
            multiattach = (extra_specs.get(
                'multiattach', '') == '<is> True' or multiattach)
            if multiattach and encryption_key_id:
                msg = _('Multiattach cannot be used with encrypted volumes.')
                raise exception.InvalidVolume(reason=msg)

        if multiattach:
            context.authorize(policy.MULTIATTACH_POLICY)

        specs: Optional[Dict] = {}
        if volume_type_id:
            qos_specs = volume_types.get_volume_type_qos_specs(volume_type_id)
            if qos_specs['qos_specs']:
                specs = qos_specs['qos_specs'].get('specs', {})

            # Determine default replication status
            extra_specs = volume_types.get_volume_type_extra_specs(
                volume_type_id)
        if not specs:
            # to make sure we don't pass empty dict
            specs = None
            extra_specs = None

        if volume_utils.is_replicated_spec(extra_specs):
            replication_status = fields.ReplicationStatus.ENABLED
        else:
            replication_status = fields.ReplicationStatus.DISABLED

        return {
            'size': size,
            'snapshot_id': snapshot_id,
            'source_volid': source_volid,
            'volume_type': volume_type,
            'volume_type_id': volume_type_id,
            'encryption_key_id': encryption_key_id,
            'qos_specs': specs,
            'consistencygroup_id': consistencygroup_id,
            'cgsnapshot_id': cgsnapshot_id,
            'group_id': group_id,
            'replication_status': replication_status,
            'refresh_az': refresh_az,
            'backup_id': backup_id,
            'multiattach': multiattach,
            'availability_zones': availability_zones
        }


class EntryCreateTask(flow_utils.CinderTask):
    """Creates an entry for the given volume creation in the database.

    Reversion strategy: remove the volume_id created from the database.
    """

    default_provides = set(['volume_properties', 'volume_id', 'volume'])

    def __init__(self) -> None:
        requires = ['description', 'metadata',
                    'name', 'reservations', 'size', 'snapshot_id',
                    'source_volid', 'volume_type_id', 'encryption_key_id',
                    'consistencygroup_id', 'cgsnapshot_id', 'multiattach',
                    'qos_specs', 'group_id', 'availability_zones']
        super(EntryCreateTask, self).__init__(addons=[ACTION],
                                              requires=requires)

    def execute(self,
                context: context.RequestContext,
                optional_args: dict,
                **kwargs) -> Dict[str, Any]:
        """Creates a database entry for the given inputs and returns details.

        Accesses the database and creates a new entry for the to be created
        volume using the given volume properties which are extracted from the
        input kwargs (and associated requirements this task needs). These
        requirements should be previously satisfied and validated by a
        pre-cursor task.
        """

        src_volid = kwargs.get('source_volid')
        src_vol = None
        if src_volid is not None:
            src_vol = objects.Volume.get_by_id(context, src_volid)
        bootable = False
        if src_vol is not None:
            bootable = src_vol.bootable
        elif kwargs.get('snapshot_id'):
            snapshot = objects.Snapshot.get_by_id(context,
                                                  kwargs.get('snapshot_id'))
            volume_id = snapshot.volume_id
            snp_vol = objects.Volume.get_by_id(context, volume_id)
            if snp_vol is not None:
                bootable = snp_vol.bootable
        availability_zones = kwargs.pop('availability_zones')
        volume_properties = {
            'size': kwargs.pop('size'),
            'user_id': context.user_id,
            'project_id': context.project_id,
            'status': 'creating',
            'attach_status': fields.VolumeAttachStatus.DETACHED,
            'encryption_key_id': kwargs.pop('encryption_key_id'),
            # Rename these to the internal name.
            'display_description': kwargs.pop('description'),
            'display_name': kwargs.pop('name'),
            'multiattach': kwargs.pop('multiattach'),
            'bootable': bootable,
        }
        if len(availability_zones) == 1:
            volume_properties['availability_zone'] = availability_zones[0]

        # Merge in the other required arguments which should provide the rest
        # of the volume property fields (if applicable).
        volume_properties.update(kwargs)
        volume = objects.Volume(context=context, **volume_properties)
        volume.create()

        # FIXME(dulek): We're passing this volume_properties dict through RPC
        # in request_spec. This shouldn't be needed, most data is replicated
        # in both volume and other places. We should make Newton read data
        # from just one correct place and leave just compatibility code.
        #
        # Right now - let's move it to versioned objects to be able to make
        # non-backward compatible changes.

        volume_properties = objects.VolumeProperties(**volume_properties)

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

    def revert(self,
               context: context.RequestContext,
               result: Union[dict, ft.Failure],
               optional_args: dict,
               **kwargs) -> None:
        if isinstance(result, ft.Failure):
            # We never produced a result and therefore can't destroy anything.
            return

        if optional_args['is_quota_committed']:
            # If quota got committed we shouldn't rollback as the volume has
            # already been created and the quota has already been absorbed.
            return

        volume = result['volume']
        try:
            volume.destroy()
        except exception.CinderException:
            # We are already reverting, therefore we should silence this
            # exception since a second exception being active will be bad.
            #
            # NOTE(harlowja): Being unable to destroy a volume is pretty
            # bad though!!
            LOG.exception("Failed destroying volume entry %s", volume.id)


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

    def execute(self,
                context: context.RequestContext,
                size: int,
                volume_type_id,
                group_snapshot: Optional[objects.Snapshot],
                optional_args: dict) -> Optional[dict]:
        try:
            values = {'per_volume_gigabytes': size}
            QUOTAS.limit_check(context, project_id=context.project_id,
                               **values)
        except exception.OverQuota as e:
            quotas = e.kwargs['quotas']
            raise exception.VolumeSizeExceedsLimit(
                size=size, limit=quotas['per_volume_gigabytes'])

        try:
            if group_snapshot:
                reserve_opts = {'volumes': 1}
            else:
                reserve_opts = {'volumes': 1, 'gigabytes': size}
            if ('update_size' in optional_args
                    and optional_args['update_size']):
                reserve_opts.pop('volumes', None)
            QUOTAS.add_volume_type_opts(context, reserve_opts, volume_type_id)
            reservations = QUOTAS.reserve(context, **reserve_opts)
            return {
                'reservations': reservations,
            }
        except exception.OverQuota as e:
            quota_utils.process_reserve_over_quota(context, e,
                                                   resource='volumes',
                                                   size=size)
        return None   # TODO: is this correct?

    def revert(self,
               context: context.RequestContext,
               result: Union[dict, ft.Failure],
               optional_args: dict, **kwargs) -> None:
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
            LOG.exception("Failed rolling back quota for"
                          " %s reservations", reservations)


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

    def execute(self, context: context.RequestContext,
                reservations, volume_properties,
                optional_args: dict) -> dict:
        QUOTAS.commit(context, reservations)
        # updating is_quota_committed attribute of optional_args dictionary
        optional_args['is_quota_committed'] = True
        return {'volume_properties': volume_properties}

    def revert(self,
               context: context.RequestContext,
               result: Union[dict, ft.Failure],
               **kwargs) -> None:
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
            LOG.exception("Failed to update quota for deleting "
                          "volume: %s", volume['id'])


class VolumeCastTask(flow_utils.CinderTask):
    """Performs a volume create cast to the scheduler or to the volume manager.

    This will signal a transition of the api workflow to another child and/or
    related workflow on another component.

    Reversion strategy: rollback source volume status and error out newly
    created volume.
    """

    def __init__(self, scheduler_rpcapi, volume_rpcapi, db) -> None:
        requires = ['image_id', 'scheduler_hints', 'snapshot_id',
                    'source_volid', 'volume_id', 'volume', 'volume_type',
                    'volume_properties', 'consistencygroup_id',
                    'cgsnapshot_id', 'group_id', 'backup_id',
                    'availability_zones']
        super(VolumeCastTask, self).__init__(addons=[ACTION],
                                             requires=requires)
        self.volume_rpcapi = volume_rpcapi
        self.scheduler_rpcapi = scheduler_rpcapi
        self.db = db

    def _cast_create_volume(self,
                            context: context.RequestContext,
                            request_spec: Dict[str, Any],
                            filter_properties: Dict) -> None:
        source_volid = request_spec['source_volid']
        volume = request_spec['volume']
        snapshot_id = request_spec['snapshot_id']
        image_id = request_spec['image_id']
        cgroup_id = request_spec['consistencygroup_id']
        group_id = request_spec['group_id']
        backup_id = request_spec['backup_id']
        if cgroup_id:
            # If cgroup_id existed, we should cast volume to the scheduler
            # to choose a proper pool whose backend is same as CG's backend.
            cgroup = objects.ConsistencyGroup.get_by_id(context, cgroup_id)
            request_spec['resource_backend'] = volume_utils.extract_host(
                cgroup.resource_backend)
        elif group_id:
            # If group_id exists, we should cast volume to the scheduler
            # to choose a proper pool whose backend is same as group's backend.
            group = objects.Group.get_by_id(context, group_id)
            request_spec['resource_backend'] = volume_utils.extract_host(
                group.resource_backend)
        elif snapshot_id and CONF.snapshot_same_host:
            # NOTE(Rongze Zhu): A simple solution for bug 1008866.
            #
            # If snapshot_id is set and CONF.snapshot_same_host is True, make
            # the call create volume directly to the volume host where the
            # snapshot resides instead of passing it through the scheduler, so
            # snapshot can be copied to the new volume.
            # NOTE(tommylikehu): In order to check the backend's capacity
            # before creating volume, we schedule this request to scheduler
            # service with the desired backend information.
            snapshot = objects.Snapshot.get_by_id(context, snapshot_id)
            request_spec['resource_backend'] = snapshot.volume.resource_backend
        elif source_volid:
            source_volume_ref = objects.Volume.get_by_id(context, source_volid)
            request_spec['resource_backend'] = (
                source_volume_ref.resource_backend)

        self.scheduler_rpcapi.create_volume(
            context,
            volume,
            snapshot_id=snapshot_id,
            image_id=image_id,
            request_spec=request_spec,
            filter_properties=filter_properties,
            backup_id=backup_id)

    def execute(self, context: context.RequestContext, **kwargs) -> None:
        scheduler_hints = kwargs.pop('scheduler_hints', None)
        db_vt = kwargs.pop('volume_type')
        kwargs['volume_type'] = None
        if db_vt:
            kwargs['volume_type'] = objects.VolumeType()
            objects.VolumeType()._from_db_object(context,
                                                 kwargs['volume_type'], db_vt)
        request_spec = objects.RequestSpec(**kwargs)
        filter_properties = {}
        if scheduler_hints:
            filter_properties['scheduler_hints'] = scheduler_hints
        self._cast_create_volume(context, request_spec, filter_properties)

    def revert(self,
               context: context.RequestContext,
               result: Union[dict, ft.Failure],
               flow_failures,
               volume: objects.Volume,
               **kwargs) -> None:
        if isinstance(result, ft.Failure):
            return

        # Restore the source volume status and set the volume to error status.
        common.restore_source_status(context, self.db, kwargs)
        common.error_out(volume)
        LOG.error("Volume %s: create failed", volume.id)
        exc_info = False
        if all(flow_failures[-1].exc_info):
            exc_info = flow_failures[-1].exc_info
        LOG.error('Unexpected build error:', exc_info=exc_info)  # noqa


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
                'volume_type': 'raw_volume_type',
                'multiattach': 'raw_multiattach'}))
    api_flow.add(QuotaReserveTask(),
                 EntryCreateTask(),
                 QuotaCommitTask())

    if scheduler_rpcapi and volume_rpcapi:
        # This will cast it out to either the scheduler or volume manager via
        # the rpc apis provided.
        api_flow.add(VolumeCastTask(scheduler_rpcapi, volume_rpcapi, db_api))

    # Now load (but do not run) the flow using the provided initial data.
    return taskflow.engines.load(api_flow, store=create_what)
