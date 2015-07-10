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

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils
import taskflow.engines
from taskflow.patterns import linear_flow
from taskflow.types import failure as ft

from cinder import exception
from cinder import flow_utils
from cinder.i18n import _, _LE, _LI
from cinder.image import glance
from cinder import objects
from cinder import utils
from cinder.volume.flows import common
from cinder.volume import utils as volume_utils

LOG = logging.getLogger(__name__)

ACTION = 'volume:create'
CONF = cfg.CONF

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


class OnFailureRescheduleTask(flow_utils.CinderTask):
    """Triggers a rescheduling request to be sent when reverting occurs.

    Reversion strategy: Triggers the rescheduling mechanism whereby a cast gets
    sent to the scheduler rpc api to allow for an attempt X of Y for scheduling
    this volume elsewhere.
    """

    def __init__(self, reschedule_context, db, scheduler_rpcapi,
                 do_reschedule):
        requires = ['filter_properties', 'image_id', 'request_spec',
                    'snapshot_id', 'volume_id', 'context']
        super(OnFailureRescheduleTask, self).__init__(addons=[ACTION],
                                                      requires=requires)
        self.do_reschedule = do_reschedule
        self.scheduler_rpcapi = scheduler_rpcapi
        self.db = db
        self.reschedule_context = reschedule_context
        # These exception types will trigger the volume to be set into error
        # status rather than being rescheduled.
        self.no_reschedule_types = [
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

    def execute(self, **kwargs):
        pass

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

        LOG.debug("Volume %(volume_id)s: re-scheduling %(method)s "
                  "attempt %(num)d due to %(reason)s",
                  {'volume_id': volume_id,
                   'method': common.make_pretty_name(create_volume),
                   'num': num_attempts,
                   'reason': cause.exception_str})

        if all(cause.exc_info):
            # Stringify to avoid circular ref problem in json serialization
            retry_info['exc'] = traceback.format_exception(*cause.exc_info)

        return create_volume(context, CONF.volume_topic, volume_id,
                             snapshot_id=snapshot_id, image_id=image_id,
                             request_spec=request_spec,
                             filter_properties=filter_properties)

    def _post_reschedule(self, context, volume_id):
        """Actions that happen after the rescheduling attempt occur here."""

        LOG.debug("Volume %s: re-scheduled", volume_id)

    def _pre_reschedule(self, context, volume_id):
        """Actions that happen before the rescheduling attempt occur here."""

        try:
            # Update volume's timestamp and host.
            #
            # NOTE(harlowja): this is awkward to be done here, shouldn't
            # this happen at the scheduler itself and not before it gets
            # sent to the scheduler? (since what happens if it never gets
            # there??). It's almost like we need a status of 'on-the-way-to
            # scheduler' in the future.
            # We don't need to update the volume's status to creating, since
            # we haven't changed it to error.
            update = {
                'scheduled_at': timeutils.utcnow(),
                'host': None
            }
            LOG.debug("Updating volume %(volume_id)s with %(update)s.",
                      {'update': update, 'volume_id': volume_id})
            self.db.volume_update(context, volume_id, update)
        except exception.CinderException:
            # Don't let updating the state cause the rescheduling to fail.
            LOG.exception(_LE("Volume %s: update volume state failed."),
                          volume_id)

    def revert(self, context, result, flow_failures, **kwargs):
        volume_id = kwargs['volume_id']

        # If do not want to be rescheduled, just set the volume's status to
        # error and return.
        if not self.do_reschedule:
            common.error_out_volume(context, self.db, volume_id)
            LOG.error(_LE("Volume %s: create failed"), volume_id)
            return

        # NOTE(dulek): Revert is occurring and manager need to know if
        # rescheduling happened. We're injecting this information into
        # exception that will be caught there. This is ugly and we need
        # TaskFlow to support better way of returning data from reverted flow.
        cause = list(flow_failures.values())[0]
        cause.exception.rescheduled = False

        # Check if we have a cause which can tell us not to reschedule and
        # set the volume's status to error.
        for failure in flow_failures.values():
            if failure.check(*self.no_reschedule_types):
                common.error_out_volume(context, self.db, volume_id)
                LOG.error(_LE("Volume %s: create failed"), volume_id)
                return

        # Use a different context when rescheduling.
        if self.reschedule_context:
            context = self.reschedule_context
            try:
                self._pre_reschedule(context, volume_id)
                self._reschedule(context, cause, **kwargs)
                self._post_reschedule(context, volume_id)
                # Inject information that we rescheduled
                cause.exception.rescheduled = True
            except exception.CinderException:
                LOG.exception(_LE("Volume %s: rescheduling failed"), volume_id)


class ExtractVolumeRefTask(flow_utils.CinderTask):
    """Extracts volume reference for given volume id."""

    default_provides = 'volume_ref'

    def __init__(self, db, host, set_error=True):
        super(ExtractVolumeRefTask, self).__init__(addons=[ACTION])
        self.db = db
        self.host = host
        self.set_error = set_error

    def execute(self, context, volume_id):
        # NOTE(harlowja): this will fetch the volume from the database, if
        # the volume has been deleted before we got here then this should fail.
        #
        # In the future we might want to have a lock on the volume_id so that
        # the volume can not be deleted while its still being created?
        volume_ref = self.db.volume_get(context, volume_id)
        return volume_ref

    def revert(self, context, volume_id, result, **kwargs):
        if isinstance(result, ft.Failure):
            return
        if self.set_error:
            common.error_out_volume(context, self.db, volume_id)
            LOG.error(_LE("Volume %s: create failed"), volume_id)


class ExtractVolumeSpecTask(flow_utils.CinderTask):
    """Extracts a spec of a volume to be created into a common structure.

    This task extracts and organizes the input requirements into a common
    and easier to analyze structure for later tasks to use. It will also
    attach the underlying database volume reference which can be used by
    other tasks to reference for further details about the volume to be.

    Reversion strategy: N/A
    """

    default_provides = 'volume_spec'

    def __init__(self, db):
        requires = ['image_id', 'snapshot_id', 'source_volid',
                    'source_replicaid']
        super(ExtractVolumeSpecTask, self).__init__(addons=[ACTION],
                                                    requires=requires)
        self.db = db

    def execute(self, context, volume_ref, **kwargs):
        get_remote_image_service = glance.get_remote_image_service

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
        elif kwargs.get('source_replicaid'):
            # We are making a clone based on the replica.
            #
            # NOTE(harlowja): This will likely fail if the replica
            # disappeared by the time this call occurred.
            source_volid = kwargs['source_replicaid']
            source_volume_ref = self.db.volume_get(context, source_volid)
            specs.update({
                'source_replicaid': source_volid,
                'source_replicastatus': source_volume_ref['status'],
                'type': 'source_replica',
            })
        elif kwargs.get('image_id'):
            # We are making an image based volume instead of a raw volume.
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

        return specs

    def revert(self, context, result, **kwargs):
        if isinstance(result, ft.Failure):
            return
        volume_spec = result.get('volume_spec')
        # Restore the source volume status and set the volume to error status.
        common.restore_source_status(context, self.db, volume_spec)


class NotifyVolumeActionTask(flow_utils.CinderTask):
    """Performs a notification about the given volume when called.

    Reversion strategy: N/A
    """

    def __init__(self, db, event_suffix):
        super(NotifyVolumeActionTask, self).__init__(addons=[ACTION,
                                                             event_suffix])
        self.db = db
        self.event_suffix = event_suffix

    def execute(self, context, volume_ref):
        volume_id = volume_ref['id']
        try:
            volume_utils.notify_about_volume_usage(context, volume_ref,
                                                   self.event_suffix,
                                                   host=volume_ref['host'])
        except exception.CinderException:
            # If notification sending of volume database entry reading fails
            # then we shouldn't error out the whole workflow since this is
            # not always information that must be sent for volumes to operate
            LOG.exception(_LE("Failed notifying about the volume"
                              " action %(event)s for volume %(volume_id)s"),
                          {'event': self.event_suffix, 'volume_id': volume_id})


class CreateVolumeFromSpecTask(flow_utils.CinderTask):
    """Creates a volume from a provided specification.

    Reversion strategy: N/A
    """

    default_provides = 'volume'

    def __init__(self, db, driver):
        super(CreateVolumeFromSpecTask, self).__init__(addons=[ACTION])
        self.db = db
        self.driver = driver

    def _handle_bootable_volume_glance_meta(self, context, volume_id,
                                            **kwargs):
        """Enable bootable flag and properly handle glance metadata.

        Caller should provide one and only one of snapshot_id,source_volid
        and image_id. If an image_id specified, an image_meta should also be
        provided, otherwise will be treated as an empty dictionary.
        """

        log_template = _("Copying metadata from %(src_type)s %(src_id)s to "
                         "%(vol_id)s.")
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
                LOG.debug(log_template, {'src_type': src_type,
                                         'src_id': src_id,
                                         'vol_id': volume_id})
                self.db.volume_glance_metadata_copy_to_volume(
                    context, volume_id, snapshot_id)
            elif kwargs.get('source_volid'):
                src_type = 'source volume'
                src_id = kwargs['source_volid']
                source_volid = src_id
                LOG.debug(log_template, {'src_type': src_type,
                                         'src_id': src_id,
                                         'vol_id': volume_id})
                self.db.volume_glance_metadata_copy_from_volume_to_volume(
                    context,
                    source_volid,
                    volume_id)
            elif kwargs.get('source_replicaid'):
                src_type = 'source replica'
                src_id = kwargs['source_replicaid']
                source_replicaid = src_id
                LOG.debug(log_template, {'src_type': src_type,
                                         'src_id': src_id,
                                         'vol_id': volume_id})
                self.db.volume_glance_metadata_copy_from_volume_to_volume(
                    context,
                    source_replicaid,
                    volume_id)
            elif kwargs.get('image_id'):
                src_type = 'image'
                src_id = kwargs['image_id']
                image_id = src_id
                image_meta = kwargs.get('image_meta', {})
                LOG.debug(log_template, {'src_type': src_type,
                                         'src_id': src_id,
                                         'vol_id': volume_id})
                self._capture_volume_image_metadata(context, volume_id,
                                                    image_id, image_meta)
        except exception.GlanceMetadataNotFound:
            # If volume is not created from image, No glance metadata
            # would be available for that volume in
            # volume glance metadata table
            pass
        except exception.CinderException as ex:
            LOG.exception(exception_template, {'src_type': src_type,
                                               'src_id': src_id,
                                               'vol_id': volume_id})
            raise exception.MetadataCopyFailure(reason=ex)

    def _create_from_snapshot(self, context, volume_ref, snapshot_id,
                              **kwargs):
        volume_id = volume_ref['id']
        snapshot = objects.Snapshot.get_by_id(context, snapshot_id)
        model_update = self.driver.create_volume_from_snapshot(volume_ref,
                                                               snapshot)
        # NOTE(harlowja): Subtasks would be useful here since after this
        # point the volume has already been created and further failures
        # will not destroy the volume (although they could in the future).
        make_bootable = False
        try:
            originating_vref = self.db.volume_get(context,
                                                  snapshot.volume_id)
            make_bootable = originating_vref.bootable
        except exception.CinderException as ex:
            LOG.exception(_LE("Failed fetching snapshot %(snapshot_id)s "
                              "bootable"
                              " flag using the provided glance snapshot "
                              "%(snapshot_ref_id)s volume reference"),
                          {'snapshot_id': snapshot_id,
                           'snapshot_ref_id': snapshot.volume_id})
            raise exception.MetadataUpdateFailure(reason=ex)
        if make_bootable:
            self._handle_bootable_volume_glance_meta(context, volume_id,
                                                     snapshot_id=snapshot_id)
        return model_update

    def _enable_bootable_flag(self, context, volume_id):
        try:
            LOG.debug('Marking volume %s as bootable.', volume_id)
            self.db.volume_update(context, volume_id, {'bootable': True})
        except exception.CinderException as ex:
            LOG.exception(_LE("Failed updating volume %(volume_id)s bootable "
                              "flag to true"), {'volume_id': volume_id})
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

    def _create_from_source_replica(self, context, volume_ref,
                                    source_replicaid, **kwargs):
        # NOTE(harlowja): if the source volume has disappeared this will be our
        # detection of that since this database call should fail.
        #
        # NOTE(harlowja): likely this is not the best place for this to happen
        # and we should have proper locks on the source volume while actions
        # that use the source volume are underway.
        srcvol_ref = self.db.volume_get(context, source_replicaid)
        model_update = self.driver.create_replica_test_volume(volume_ref,
                                                              srcvol_ref)
        # NOTE(harlowja): Subtasks would be useful here since after this
        # point the volume has already been created and further failures
        # will not destroy the volume (although they could in the future).
        if srcvol_ref.bootable:
            self._handle_bootable_volume_glance_meta(
                context,
                volume_ref['id'],
                source_replicaid=source_replicaid)
        return model_update

    def _copy_image_to_volume(self, context, volume_ref,
                              image_id, image_location, image_service):
        """Downloads Glance image to the specified volume."""
        copy_image_to_volume = self.driver.copy_image_to_volume
        volume_id = volume_ref['id']
        LOG.debug("Attempting download of %(image_id)s (%(image_location)s)"
                  " to volume %(volume_id)s.",
                  {'image_id': image_id, 'volume_id': volume_id,
                   'image_location': image_location})
        try:
            copy_image_to_volume(context, volume_ref, image_service, image_id)
        except processutils.ProcessExecutionError as ex:
            LOG.exception(_LE("Failed to copy image %(image_id)s to volume: "
                              "%(volume_id)s"),
                          {'volume_id': volume_id, 'image_id': image_id})
            raise exception.ImageCopyFailure(reason=ex.stderr)
        except exception.ImageUnacceptable as ex:
            LOG.exception(_LE("Failed to copy image to volume: %(volume_id)s"),
                          {'volume_id': volume_id})
            raise exception.ImageUnacceptable(ex)
        except Exception as ex:
            LOG.exception(_LE("Failed to copy image %(image_id)s to "
                              "volume: %(volume_id)s"),
                          {'volume_id': volume_id, 'image_id': image_id})
            if not isinstance(ex, exception.ImageCopyFailure):
                raise exception.ImageCopyFailure(reason=ex)
            else:
                raise

        LOG.debug("Downloaded image %(image_id)s (%(image_location)s)"
                  " to volume %(volume_id)s successfully.",
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
        LOG.debug("Creating volume glance metadata for volume %(volume_id)s"
                  " backed by image %(image_id)s with: %(vol_metadata)s.",
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
        LOG.debug("Cloning %(volume_id)s from image %(image_id)s "
                  " at location %(image_location)s.",
                  {'volume_id': volume_ref['id'],
                   'image_location': image_location, 'image_id': image_id})
        # Create the volume from an image.
        #
        # NOTE (singn): two params need to be returned
        # dict containing provider_location for cloned volume
        # and clone status.
        model_update, cloned = self.driver.clone_image(context,
                                                       volume_ref,
                                                       image_location,
                                                       image_meta,
                                                       image_service)
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
                LOG.exception(_LE("Failed updating volume %(volume_id)s with "
                                  "%(updates)s"),
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

    def execute(self, context, volume_ref, volume_spec):
        volume_spec = dict(volume_spec)
        volume_id = volume_spec.pop('volume_id', None)
        if not volume_id:
            volume_id = volume_ref['id']

        # we can't do anything if the driver didn't init
        if not self.driver.initialized:
            driver_name = self.driver.__class__.__name__
            LOG.exception(_LE("Unable to create volume. "
                              "Volume driver %s not initialized"), driver_name)
            raise exception.DriverNotInitialized()

        create_type = volume_spec.pop('type', None)
        LOG.info(_LI("Volume %(volume_id)s: being created as %(create_type)s "
                     "with specification: %(volume_spec)s"),
                 {'volume_spec': volume_spec, 'volume_id': volume_id,
                  'create_type': create_type})
        if create_type == 'raw':
            model_update = self._create_raw_volume(context,
                                                   volume_ref=volume_ref,
                                                   **volume_spec)
        elif create_type == 'snap':
            model_update = self._create_from_snapshot(context,
                                                      volume_ref=volume_ref,
                                                      **volume_spec)
        elif create_type == 'source_vol':
            model_update = self._create_from_source_volume(
                context, volume_ref=volume_ref, **volume_spec)
        elif create_type == 'source_replica':
            model_update = self._create_from_source_replica(
                context, volume_ref=volume_ref, **volume_spec)
        elif create_type == 'image':
            model_update = self._create_from_image(context,
                                                   volume_ref=volume_ref,
                                                   **volume_spec)
        else:
            raise exception.VolumeTypeNotFound(volume_type_id=create_type)

        # Persist any model information provided on creation.
        try:
            if model_update:
                volume_ref = self.db.volume_update(context, volume_ref['id'],
                                                   model_update)
        except exception.CinderException:
            # If somehow the update failed we want to ensure that the
            # failure is logged (but not try rescheduling since the volume at
            # this point has been created).
            LOG.exception(_LE("Failed updating model of volume %(volume_id)s "
                              "with creation provided model %(model)s"),
                          {'volume_id': volume_id, 'model': model_update})
            raise

        return volume_ref


class CreateVolumeOnFinishTask(NotifyVolumeActionTask):
    """On successful volume creation this will perform final volume actions.

    When a volume is created successfully it is expected that MQ notifications
    and database updates will occur to 'signal' to others that the volume is
    now ready for usage. This task does those notifications and updates in a
    reliable manner (not re-raising exceptions if said actions can not be
    triggered).

    Reversion strategy: N/A
    """

    def __init__(self, db, event_suffix):
        super(CreateVolumeOnFinishTask, self).__init__(db, event_suffix)
        self.status_translation = {
            'migration_target_creating': 'migration_target',
        }

    def execute(self, context, volume, volume_spec):
        volume_id = volume['id']
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
            super(CreateVolumeOnFinishTask, self).execute(context, volume_ref)
        except exception.CinderException:
            LOG.exception(_LE("Failed updating volume %(volume_id)s with "
                              "%(update)s"), {'volume_id': volume_id,
                                              'update': update})
        # Even if the update fails, the volume is ready.
        LOG.info(_LI("Volume %(volume_name)s (%(volume_id)s): "
                     "created successfully"),
                 {'volume_name': volume_spec['volume_name'],
                  'volume_id': volume_id})


def get_flow(context, db, driver, scheduler_rpcapi, host, volume_id,
             allow_reschedule, reschedule_context, request_spec,
             filter_properties, snapshot_id=None, image_id=None,
             source_volid=None, source_replicaid=None,
             consistencygroup_id=None, cgsnapshot_id=None):
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

    # This injects the initial starting flow values into the workflow so that
    # the dependency order of the tasks provides/requires can be correctly
    # determined.
    create_what = {
        'context': context,
        'filter_properties': filter_properties,
        'image_id': image_id,
        'request_spec': request_spec,
        'snapshot_id': snapshot_id,
        'source_volid': source_volid,
        'volume_id': volume_id,
        'source_replicaid': source_replicaid,
        'consistencygroup_id': consistencygroup_id,
        'cgsnapshot_id': cgsnapshot_id,
    }

    volume_flow.add(ExtractVolumeRefTask(db, host, set_error=False))

    retry = filter_properties.get('retry', None)

    # Always add OnFailureRescheduleTask and we handle the change of volume's
    # status when revert task flow. Meanwhile, no need to revert process of
    # ExtractVolumeRefTask.
    do_reschedule = allow_reschedule and request_spec and retry
    volume_flow.add(OnFailureRescheduleTask(reschedule_context, db,
                                            scheduler_rpcapi,
                                            do_reschedule))

    LOG.debug("Volume reschedule parameters: %(allow)s "
              "retry: %(retry)s", {'allow': allow_reschedule, 'retry': retry})

    volume_flow.add(ExtractVolumeSpecTask(db),
                    NotifyVolumeActionTask(db, "create.start"),
                    CreateVolumeFromSpecTask(db, driver),
                    CreateVolumeOnFinishTask(db, "create.end"))

    # Now load (but do not run) the flow using the provided initial data.
    return taskflow.engines.load(volume_flow, store=create_what)
