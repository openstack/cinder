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

import os
import traceback

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import timeutils
import taskflow.engines
from taskflow.patterns import linear_flow
from taskflow.types import failure as ft

from cinder import context as cinder_context
from cinder import coordination
from cinder import exception
from cinder import flow_utils
from cinder.i18n import _
from cinder.image import glance
from cinder.image import image_utils
from cinder.message import api as message_api
from cinder.message import message_field
from cinder import objects
from cinder.objects import consistencygroup
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

    If rescheduling doesn't occur this task errors out the volume.

    Reversion strategy: Triggers the rescheduling mechanism whereby a cast gets
    sent to the scheduler rpc api to allow for an attempt X of Y for scheduling
    this volume elsewhere.
    """

    def __init__(self, reschedule_context, db, driver, scheduler_rpcapi,
                 do_reschedule):
        requires = ['filter_properties', 'request_spec', 'volume',
                    'context']
        super(OnFailureRescheduleTask, self).__init__(addons=[ACTION],
                                                      requires=requires)
        self.do_reschedule = do_reschedule
        self.scheduler_rpcapi = scheduler_rpcapi
        self.db = db
        self.driver = driver
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
            exception.ImageTooBig,
        ]

    def execute(self, **kwargs):
        pass

    def _pre_reschedule(self, volume):
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
                'host': None,
            }
            LOG.debug("Updating volume %(volume_id)s with %(update)s.",
                      {'update': update, 'volume_id': volume.id})
            volume.update(update)
            volume.save()
        except exception.CinderException:
            # Don't let updating the state cause the rescheduling to fail.
            LOG.exception("Volume %s: update volume state failed.",
                          volume.id)

    def _reschedule(self, context, cause, request_spec, filter_properties,
                    volume):
        """Actions that happen during the rescheduling attempt occur here."""

        create_volume = self.scheduler_rpcapi.create_volume
        if not filter_properties:
            filter_properties = {}
        if 'retry' not in filter_properties:
            filter_properties['retry'] = {}

        retry_info = filter_properties['retry']
        num_attempts = retry_info.get('num_attempts', 0)
        request_spec['volume_id'] = volume.id

        LOG.debug("Volume %(volume_id)s: re-scheduling %(method)s "
                  "attempt %(num)d due to %(reason)s",
                  {'volume_id': volume.id,
                   'method': common.make_pretty_name(create_volume),
                   'num': num_attempts,
                   'reason': cause.exception_str})

        if all(cause.exc_info):
            # Stringify to avoid circular ref problem in json serialization
            retry_info['exc'] = traceback.format_exception(*cause.exc_info)

        return create_volume(context, volume, request_spec=request_spec,
                             filter_properties=filter_properties)

    def _post_reschedule(self, volume):
        """Actions that happen after the rescheduling attempt occur here."""

        LOG.debug("Volume %s: re-scheduled", volume.id)

        # NOTE(dulek): Here we should be sure that rescheduling occurred and
        # host field will be erased. Just in case volume was already created at
        # the backend, we attempt to delete it.
        try:
            self.driver.delete_volume(volume)
        except Exception:
            # Most likely the volume weren't created at the backend. We can
            # safely ignore this.
            pass

    def revert(self, context, result, flow_failures, volume, **kwargs):
        # NOTE(dulek): Revert is occurring and manager need to know if
        # rescheduling happened. We're returning boolean flag that will
        # indicate that. It which will be available in flow engine store
        # through get_revert_result method.

        # If do not want to be rescheduled, just set the volume's status to
        # error and return.
        if not self.do_reschedule:
            common.error_out(volume)
            LOG.error("Volume %s: create failed", volume.id)
            return False

        # Check if we have a cause which can tell us not to reschedule and
        # set the volume's status to error.
        for failure in flow_failures.values():
            if failure.check(*self.no_reschedule_types):
                common.error_out(volume)
                LOG.error("Volume %s: create failed", volume.id)
                return False

        # Use a different context when rescheduling.
        if self.reschedule_context:
            cause = list(flow_failures.values())[0]
            context = self.reschedule_context
            try:
                self._pre_reschedule(volume)
                self._reschedule(context, cause, volume=volume, **kwargs)
                self._post_reschedule(volume)
                return True
            except exception.CinderException:
                LOG.exception("Volume %s: rescheduling failed", volume.id)

        return False


class ExtractVolumeRefTask(flow_utils.CinderTask):
    """Extracts volume reference for given volume id."""

    default_provides = 'refreshed'

    def __init__(self, db, host, set_error=True):
        super(ExtractVolumeRefTask, self).__init__(addons=[ACTION])
        self.db = db
        self.host = host
        self.set_error = set_error

    def execute(self, context, volume):
        # NOTE(harlowja): this will fetch the volume from the database, if
        # the volume has been deleted before we got here then this should fail.
        #
        # In the future we might want to have a lock on the volume_id so that
        # the volume can not be deleted while its still being created?
        volume.refresh()
        return volume

    def revert(self, context, volume, result, **kwargs):
        if isinstance(result, ft.Failure) or not self.set_error:
            return

        reason = _('Volume create failed while extracting volume ref.')
        common.error_out(volume, reason)
        LOG.error("Volume %s: create failed", volume.id)


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
        requires = ['volume', 'request_spec']
        super(ExtractVolumeSpecTask, self).__init__(addons=[ACTION],
                                                    requires=requires)
        self.db = db

    def execute(self, context, volume, request_spec):
        get_remote_image_service = glance.get_remote_image_service

        volume_name = volume.name
        volume_size = utils.as_int(volume.size, quiet=False)

        # Create a dictionary that will represent the volume to be so that
        # later tasks can easily switch between the different types and create
        # the volume according to the volume types specifications (which are
        # represented in this dictionary).
        specs = {
            'status': volume.status,
            'type': 'raw',  # This will have the type of the volume to be
                            # created, which should be one of [raw, snap,
                            # source_vol, image]
            'volume_id': volume.id,
            'volume_name': volume_name,
            'volume_size': volume_size,
        }

        if volume.snapshot_id:
            # We are making a snapshot based volume instead of a raw volume.
            specs.update({
                'type': 'snap',
                'snapshot_id': volume.snapshot_id,
            })
        elif volume.source_volid:
            # We are making a source based volume instead of a raw volume.
            #
            # NOTE(harlowja): This will likely fail if the source volume
            # disappeared by the time this call occurred.
            source_volid = volume.source_volid
            source_volume_ref = objects.Volume.get_by_id(context,
                                                         source_volid)
            specs.update({
                'source_volid': source_volid,
                # This is captured incase we have to revert and we want to set
                # back the source volume status to its original status. This
                # may or may not be sketchy to do??
                'source_volstatus': source_volume_ref.status,
                'type': 'source_vol',
            })
        elif request_spec.get('source_replicaid'):
            # We are making a clone based on the replica.
            #
            # NOTE(harlowja): This will likely fail if the replica
            # disappeared by the time this call occurred.
            source_volid = request_spec['source_replicaid']
            source_volume_ref = objects.Volume.get_by_id(context,
                                                         source_volid)
            specs.update({
                'source_replicaid': source_volid,
                'source_replicastatus': source_volume_ref.status,
                'type': 'source_replica',
            })
        elif request_spec.get('image_id'):
            # We are making an image based volume instead of a raw volume.
            image_href = request_spec['image_id']
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

    def execute(self, context, volume):
        try:
            volume_utils.notify_about_volume_usage(context, volume,
                                                   self.event_suffix,
                                                   host=volume.host)
        except exception.CinderException:
            # If notification sending of volume database entry reading fails
            # then we shouldn't error out the whole workflow since this is
            # not always information that must be sent for volumes to operate
            LOG.exception("Failed notifying about the volume"
                          " action %(event)s for volume %(volume_id)s",
                          {'event': self.event_suffix, 'volume_id': volume.id})


class CreateVolumeFromSpecTask(flow_utils.CinderTask):
    """Creates a volume from a provided specification.

    Reversion strategy: N/A
    """

    def __init__(self, manager, db, driver, image_volume_cache=None):
        super(CreateVolumeFromSpecTask, self).__init__(addons=[ACTION])
        self.manager = manager
        self.db = db
        self.driver = driver
        self.image_volume_cache = image_volume_cache
        self.message = message_api.API()

    def _handle_bootable_volume_glance_meta(self, context, volume,
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
        self._enable_bootable_flag(context, volume)
        try:
            if kwargs.get('snapshot_id'):
                src_type = 'snapshot'
                src_id = kwargs['snapshot_id']
                snapshot_id = src_id
                LOG.debug(log_template, {'src_type': src_type,
                                         'src_id': src_id,
                                         'vol_id': volume.id})
                self.db.volume_glance_metadata_copy_to_volume(
                    context, volume.id, snapshot_id)
            elif kwargs.get('source_volid'):
                src_type = 'source volume'
                src_id = kwargs['source_volid']
                source_volid = src_id
                LOG.debug(log_template, {'src_type': src_type,
                                         'src_id': src_id,
                                         'vol_id': volume.id})
                self.db.volume_glance_metadata_copy_from_volume_to_volume(
                    context,
                    source_volid,
                    volume.id)
            elif kwargs.get('source_replicaid'):
                src_type = 'source replica'
                src_id = kwargs['source_replicaid']
                source_replicaid = src_id
                LOG.debug(log_template, {'src_type': src_type,
                                         'src_id': src_id,
                                         'vol_id': volume.id})
                self.db.volume_glance_metadata_copy_from_volume_to_volume(
                    context,
                    source_replicaid,
                    volume.id)
            elif kwargs.get('image_id'):
                src_type = 'image'
                src_id = kwargs['image_id']
                image_id = src_id
                image_meta = kwargs.get('image_meta', {})
                LOG.debug(log_template, {'src_type': src_type,
                                         'src_id': src_id,
                                         'vol_id': volume.id})
                self._capture_volume_image_metadata(context, volume.id,
                                                    image_id, image_meta)
        except exception.GlanceMetadataNotFound:
            # If volume is not created from image, No glance metadata
            # would be available for that volume in
            # volume glance metadata table
            pass
        except exception.CinderException as ex:
            LOG.exception(exception_template, {'src_type': src_type,
                                               'src_id': src_id,
                                               'vol_id': volume.id})
            raise exception.MetadataCopyFailure(reason=ex)

    def _create_from_snapshot(self, context, volume, snapshot_id,
                              **kwargs):
        snapshot = objects.Snapshot.get_by_id(context, snapshot_id)
        model_update = self.driver.create_volume_from_snapshot(volume,
                                                               snapshot)
        self._cleanup_cg_in_volume(volume)
        # NOTE(harlowja): Subtasks would be useful here since after this
        # point the volume has already been created and further failures
        # will not destroy the volume (although they could in the future).
        make_bootable = False
        try:
            originating_vref = objects.Volume.get_by_id(context,
                                                        snapshot.volume_id)
            make_bootable = originating_vref.bootable
        except exception.CinderException as ex:
            LOG.exception("Failed fetching snapshot %(snapshot_id)s bootable"
                          " flag using the provided glance snapshot "
                          "%(snapshot_ref_id)s volume reference",
                          {'snapshot_id': snapshot_id,
                           'snapshot_ref_id': snapshot.volume_id})
            raise exception.MetadataUpdateFailure(reason=ex)
        if make_bootable:
            self._handle_bootable_volume_glance_meta(context, volume,
                                                     snapshot_id=snapshot_id)
        return model_update

    def _enable_bootable_flag(self, context, volume):
        try:
            LOG.debug('Marking volume %s as bootable.', volume.id)
            volume.bootable = True
            volume.save()
        except exception.CinderException as ex:
            LOG.exception("Failed updating volume %(volume_id)s bootable "
                          "flag to true", {'volume_id': volume.id})
            raise exception.MetadataUpdateFailure(reason=ex)

    def _create_from_source_volume(self, context, volume, source_volid,
                                   **kwargs):
        # NOTE(harlowja): if the source volume has disappeared this will be our
        # detection of that since this database call should fail.
        #
        # NOTE(harlowja): likely this is not the best place for this to happen
        # and we should have proper locks on the source volume while actions
        # that use the source volume are underway.
        srcvol_ref = objects.Volume.get_by_id(context, source_volid)
        model_update = self.driver.create_cloned_volume(volume, srcvol_ref)
        self._cleanup_cg_in_volume(volume)
        # NOTE(harlowja): Subtasks would be useful here since after this
        # point the volume has already been created and further failures
        # will not destroy the volume (although they could in the future).
        if srcvol_ref.bootable:
            self._handle_bootable_volume_glance_meta(
                context, volume, source_volid=srcvol_ref.id)
        return model_update

    def _create_from_source_replica(self, context, volume, source_replicaid,
                                    **kwargs):
        # NOTE(harlowja): if the source volume has disappeared this will be our
        # detection of that since this database call should fail.
        #
        # NOTE(harlowja): likely this is not the best place for this to happen
        # and we should have proper locks on the source volume while actions
        # that use the source volume are underway.
        srcvol_ref = objects.Volume.get_by_id(context, source_replicaid)
        model_update = self.driver.create_replica_test_volume(volume,
                                                              srcvol_ref)
        self._cleanup_cg_in_volume(volume)
        # NOTE(harlowja): Subtasks would be useful here since after this
        # point the volume has already been created and further failures
        # will not destroy the volume (although they could in the future).
        if srcvol_ref.bootable:
            self._handle_bootable_volume_glance_meta(
                context,
                volume,
                source_replicaid=source_replicaid)
        return model_update

    def _copy_image_to_volume(self, context, volume,
                              image_meta, image_location, image_service):

        image_id = image_meta['id']
        """Downloads Glance image to the specified volume."""
        LOG.debug("Attempting download of %(image_id)s (%(image_location)s)"
                  " to volume %(volume_id)s.",
                  {'image_id': image_id, 'volume_id': volume.id,
                   'image_location': image_location})
        try:
            image_properties = image_meta.get('properties', {})
            image_encryption_key = image_properties.get(
                'cinder_encryption_key_id')

            if volume.encryption_key_id and image_encryption_key:
                # If the image provided an encryption key, we have
                # already cloned it to the volume's key in
                # _get_encryption_key_id, so we can do a direct copy.
                self.driver.copy_image_to_volume(
                    context, volume, image_service, image_id)
            elif volume.encryption_key_id:
                # Creating an encrypted volume from a normal, unencrypted,
                # image.
                self.driver.copy_image_to_encrypted_volume(
                    context, volume, image_service, image_id)
            else:
                self.driver.copy_image_to_volume(
                    context, volume, image_service, image_id)
        except processutils.ProcessExecutionError as ex:
            LOG.exception("Failed to copy image %(image_id)s to volume: "
                          "%(volume_id)s",
                          {'volume_id': volume.id, 'image_id': image_id})
            raise exception.ImageCopyFailure(reason=ex.stderr)
        except exception.ImageUnacceptable as ex:
            LOG.exception("Failed to copy image to volume: %(volume_id)s",
                          {'volume_id': volume.id})
            raise exception.ImageUnacceptable(ex)
        except exception.ImageTooBig as ex:
            LOG.exception("Failed to copy image %(image_id)s to volume: "
                          "%(volume_id)s",
                          {'volume_id': volume.id, 'image_id': image_id})
            excutils.save_and_reraise_exception()
        except Exception as ex:
            LOG.exception("Failed to copy image %(image_id)s to "
                          "volume: %(volume_id)s",
                          {'volume_id': volume.id, 'image_id': image_id})
            if not isinstance(ex, exception.ImageCopyFailure):
                raise exception.ImageCopyFailure(reason=ex)
            else:
                raise

        LOG.debug("Downloaded image %(image_id)s (%(image_location)s)"
                  " to volume %(volume_id)s successfully.",
                  {'image_id': image_id, 'volume_id': volume.id,
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

        volume_metadata = dict(property_metadata)
        volume_metadata.update(base_metadata)
        LOG.debug("Creating volume glance metadata for volume %(volume_id)s"
                  " backed by image %(image_id)s with: %(vol_metadata)s.",
                  {'volume_id': volume_id, 'image_id': image_id,
                   'vol_metadata': volume_metadata})
        self.db.volume_glance_metadata_bulk_create(context, volume_id,
                                                   volume_metadata)

    def _clone_image_volume(self, context, volume, image_location, image_meta):
        """Create a volume efficiently from an existing image.

        Returns a dict of volume properties eg. provider_location,
        boolean indicating whether cloning occurred
        """
        # NOTE (lixiaoy1): currently can't create volume from source vol with
        # different encryptions, so just return.
        if not image_location or volume.encryption_key_id:
            return None, False

        if (image_meta.get('container_format') != 'bare' or
                image_meta.get('disk_format') != 'raw'):
            LOG.info("Requested image %(id)s is not in raw format.",
                     {'id': image_meta.get('id')})
            return None, False

        image_volume = None
        direct_url, locations = image_location
        urls = set([direct_url] + [loc.get('url') for loc in locations or []])
        image_volume_ids = [url[9:] for url in urls
                            if url and url.startswith('cinder://')]
        image_volumes = self.db.volume_get_all_by_host(
            context, volume['host'], filters={'id': image_volume_ids})

        for image_volume in image_volumes:
            # For the case image volume is stored in the service tenant,
            # image_owner volume metadata should also be checked.
            image_owner = None
            volume_metadata = image_volume.get('volume_metadata') or {}
            for m in volume_metadata:
                if m['key'] == 'image_owner':
                    image_owner = m['value']
            if (image_meta['owner'] != volume['project_id'] and
                    image_meta['owner'] != image_owner):
                LOG.info("Skipping image volume %(id)s because "
                         "it is not accessible by current Tenant.",
                         {'id': image_volume.id})
                continue

            LOG.info("Will clone a volume from the image volume "
                     "%(id)s.", {'id': image_volume.id})
            break
        else:
            LOG.debug("No accessible image volume for image %(id)s found.",
                      {'id': image_meta['id']})
            return None, False

        try:
            ret = self.driver.create_cloned_volume(volume, image_volume)
            self._cleanup_cg_in_volume(volume)
            return ret, True
        except (NotImplementedError, exception.CinderException):
            LOG.exception('Failed to clone image volume %(id)s.',
                          {'id': image_volume['id']})
            return None, False

    def _create_from_image_download(self, context, volume, image_location,
                                    image_meta, image_service):
        # TODO(harlowja): what needs to be rolled back in the clone if this
        # volume create fails?? Likely this should be a subflow or broken
        # out task in the future. That will bring up the question of how
        # do we make said subflow/task which is only triggered in the
        # clone image 'path' resumable and revertable in the correct
        # manner.
        model_update = self.driver.create_volume(volume) or {}
        self._cleanup_cg_in_volume(volume)
        model_update['status'] = 'downloading'
        try:
            volume.update(model_update)
            volume.save()
        except exception.CinderException:
            LOG.exception("Failed updating volume %(volume_id)s with "
                          "%(updates)s",
                          {'volume_id': volume.id,
                           'updates': model_update})
        try:
            self._copy_image_to_volume(context, volume, image_meta,
                                       image_location, image_service)
        except exception.ImageTooBig:
            with excutils.save_and_reraise_exception():
                LOG.exception("Failed to copy image to volume "
                              "%(volume_id)s due to insufficient space",
                              {'volume_id': volume.id})
        return model_update

    def _create_from_image_cache(self, context, internal_context, volume,
                                 image_id, image_meta):
        """Attempt to create the volume using the image cache.

        Best case this will simply clone the existing volume in the cache.
        Worst case the image is out of date and will be evicted. In that case
        a clone will not be created and the image must be downloaded again.
        """
        LOG.debug('Attempting to retrieve cache entry for image = '
                  '%(image_id)s on host %(host)s.',
                  {'image_id': image_id, 'host': volume.host})
        # Currently can't create volume from source vol with different
        # encryptions, so just return
        if volume.encryption_key_id:
            return None, False

        try:
            cache_entry = self.image_volume_cache.get_entry(internal_context,
                                                            volume,
                                                            image_id,
                                                            image_meta)
            if cache_entry:
                LOG.debug('Creating from source image-volume %(volume_id)s',
                          {'volume_id': cache_entry['volume_id']})
                model_update = self._create_from_source_volume(
                    context,
                    volume,
                    cache_entry['volume_id']
                )
                return model_update, True
        except NotImplementedError:
            LOG.warning('Backend does not support creating image-volume '
                        'clone. Image will be downloaded from Glance.')
        except exception.CinderException as e:
            LOG.warning('Failed to create volume from image-volume cache, '
                        'image will be downloaded from Glance. Error: '
                        '%(exception)s', {'exception': e})
        return None, False

    @coordination.synchronized('{image_id}')
    def _prepare_image_cache_entry(self, context, volume,
                                   image_location, image_id,
                                   image_meta, image_service):
        internal_context = cinder_context.get_internal_tenant_context()
        if not internal_context:
            return None, False

        cache_entry = self.image_volume_cache.get_entry(internal_context,
                                                        volume,
                                                        image_id,
                                                        image_meta)

        # If the entry is in the cache then return ASAP in order to minimize
        # the scope of the lock. If it isn't in the cache then do the work
        # that adds it. The work is done inside the locked region to ensure
        # only one cache entry is created.
        if cache_entry:
            LOG.debug('Found cache entry for image = '
                      '%(image_id)s on host %(host)s.',
                      {'image_id': image_id, 'host': volume.host})
            return None, False
        else:
            LOG.debug('Preparing cache entry for image = '
                      '%(image_id)s on host %(host)s.',
                      {'image_id': image_id, 'host': volume.host})
            model_update = self._create_from_image_cache_or_download(
                context,
                volume,
                image_location,
                image_id,
                image_meta,
                image_service,
                update_cache=True)
            return model_update, True

    def _create_from_image_cache_or_download(self, context, volume,
                                             image_location, image_id,
                                             image_meta, image_service,
                                             update_cache=False):
        # NOTE(e0ne): check for free space in image_conversion_dir before
        # image downloading.
        # NOTE(mnaser): This check *only* happens if the backend is not able
        #               to clone volumes and we have to resort to downloading
        #               the image from Glance and uploading it.
        if (CONF.image_conversion_dir and not
                os.path.exists(CONF.image_conversion_dir)):
            os.makedirs(CONF.image_conversion_dir)
        try:
            image_utils.check_available_space(
                CONF.image_conversion_dir,
                image_meta['size'], image_id)
        except exception.ImageTooBig as err:
            with excutils.save_and_reraise_exception():
                self.message.create(
                    context,
                    message_field.Action.COPY_IMAGE_TO_VOLUME,
                    resource_uuid=volume.id,
                    detail=message_field.Detail.NOT_ENOUGH_SPACE_FOR_IMAGE,
                    exception=err)

        # Try and use the image cache.
        should_create_cache_entry = False
        cloned = False
        model_update = None
        if self.image_volume_cache:
            internal_context = cinder_context.get_internal_tenant_context()
            if not internal_context:
                LOG.info('Unable to get Cinder internal context, will '
                         'not use image-volume cache.')
            else:
                model_update, cloned = self._create_from_image_cache(
                    context,
                    internal_context,
                    volume,
                    image_id,
                    image_meta
                )
                # Don't cache unless directed.
                if not cloned and update_cache:
                    should_create_cache_entry = True

        # Fall back to default behavior of creating volume,
        # download the image data and copy it into the volume.
        original_size = volume.size
        backend_name = volume_utils.extract_host(volume.service_topic_queue)
        try:
            if not cloned:
                try:
                    with image_utils.TemporaryImages.fetch(
                            image_service, context, image_id,
                            backend_name) as tmp_image:
                        # Try to create the volume as the minimal size,
                        # then we can extend once the image has been
                        # downloaded.
                        data = image_utils.qemu_img_info(tmp_image)

                        virtual_size = image_utils.check_virtual_size(
                            data.virtual_size, volume.size, image_id)

                        if should_create_cache_entry:
                            if virtual_size and virtual_size != original_size:
                                    volume.size = virtual_size
                                    volume.save()
                        model_update = self._create_from_image_download(
                            context,
                            volume,
                            image_location,
                            image_meta,
                            image_service
                        )
                except exception.ImageTooBig as e:
                    with excutils.save_and_reraise_exception():
                        self.message.create(
                            context,
                            message_field.Action.COPY_IMAGE_TO_VOLUME,
                            resource_uuid=volume.id,
                            detail=
                            message_field.Detail.NOT_ENOUGH_SPACE_FOR_IMAGE,
                            exception=e)

            if should_create_cache_entry:
                # Update the newly created volume db entry before we clone it
                # for the image-volume creation.
                if model_update:
                    volume.update(model_update)
                    volume.save()
                self.manager._create_image_cache_volume_entry(internal_context,
                                                              volume,
                                                              image_id,
                                                              image_meta)
        finally:
            # If we created the volume as the minimal size, extend it back to
            # what was originally requested. If an exception has occurred or
            # extending it back failed, we still need to put this back before
            # letting it be raised further up the stack.
            if volume.size != original_size:
                try:
                    self.driver.extend_volume(volume, original_size)
                finally:
                    volume.size = original_size
                    volume.save()

        return model_update

    def _create_from_image(self, context, volume,
                           image_location, image_id, image_meta,
                           image_service, **kwargs):
        LOG.debug("Cloning %(volume_id)s from image %(image_id)s "
                  " at location %(image_location)s.",
                  {'volume_id': volume.id,
                   'image_location': image_location, 'image_id': image_id})

        virtual_size = image_meta.get('virtual_size')
        if virtual_size:
            virtual_size = image_utils.check_virtual_size(virtual_size,
                                                          volume.size,
                                                          image_id)

        # Create the volume from an image.
        #
        # First see if the driver can clone the image directly.
        #
        # NOTE (singn): two params need to be returned
        # dict containing provider_location for cloned volume
        # and clone status.
        # NOTE (lixiaoy1): Currently all images are raw data, we can't
        # use clone_image to copy data if new volume is encrypted.
        volume_is_encrypted = volume.encryption_key_id is not None
        cloned = False
        model_update = None
        if not volume_is_encrypted:
            model_update, cloned = self.driver.clone_image(context,
                                                           volume,
                                                           image_location,
                                                           image_meta,
                                                           image_service)

        # Try and clone the image if we have it set as a glance location.
        if not cloned and 'cinder' in CONF.allowed_direct_url_schemes:
            model_update, cloned = self._clone_image_volume(context,
                                                            volume,
                                                            image_location,
                                                            image_meta)

        # If we're going to try using the image cache then prepare the cache
        # entry. Note: encrypted volume images are not cached.
        if not cloned and self.image_volume_cache and not volume_is_encrypted:
            # If _prepare_image_cache_entry() has to create the cache entry
            # then it will also create the volume. But if the volume image
            # is already in the cache then it returns (None, False), and
            # _create_from_image_cache_or_download() will use the cache.
            model_update, cloned = self._prepare_image_cache_entry(
                context,
                volume,
                image_location,
                image_id,
                image_meta,
                image_service)

        # Try and use the image cache, and download if not cached.
        if not cloned:
            model_update = self._create_from_image_cache_or_download(
                context,
                volume,
                image_location,
                image_id,
                image_meta,
                image_service)

        self._handle_bootable_volume_glance_meta(context, volume,
                                                 image_id=image_id,
                                                 image_meta=image_meta)
        return model_update

    def _create_raw_volume(self, volume, **kwargs):
        ret = self.driver.create_volume(volume)
        self._cleanup_cg_in_volume(volume)
        return ret

    def execute(self, context, volume, volume_spec):
        volume_spec = dict(volume_spec)
        volume_id = volume_spec.pop('volume_id', None)
        if not volume_id:
            volume_id = volume.id

        # we can't do anything if the driver didn't init
        if not self.driver.initialized:
            driver_name = self.driver.__class__.__name__
            LOG.error("Unable to create volume. "
                      "Volume driver %s not initialized", driver_name)
            raise exception.DriverNotInitialized()

        # NOTE(xyang): Populate consistencygroup_id and consistencygroup
        # fields before passing to the driver. This is to support backward
        # compatibility of consistencygroup.
        if volume.group_id:
            volume.consistencygroup_id = volume.group_id
            cg = consistencygroup.ConsistencyGroup()
            cg.from_group(volume.group)
            volume.consistencygroup = cg

        create_type = volume_spec.pop('type', None)
        LOG.info("Volume %(volume_id)s: being created as %(create_type)s "
                 "with specification: %(volume_spec)s",
                 {'volume_spec': volume_spec, 'volume_id': volume_id,
                  'create_type': create_type})
        if create_type == 'raw':
            model_update = self._create_raw_volume(volume, **volume_spec)
        elif create_type == 'snap':
            model_update = self._create_from_snapshot(context, volume,
                                                      **volume_spec)
        elif create_type == 'source_vol':
            model_update = self._create_from_source_volume(
                context, volume, **volume_spec)
        elif create_type == 'source_replica':
            model_update = self._create_from_source_replica(
                context, volume, **volume_spec)
        elif create_type == 'image':
            model_update = self._create_from_image(context,
                                                   volume,
                                                   **volume_spec)
        else:
            raise exception.VolumeTypeNotFound(volume_type_id=create_type)

        # Persist any model information provided on creation.
        try:
            if model_update:
                with volume.obj_as_admin():
                    volume.update(model_update)
                    volume.save()
        except exception.CinderException:
            # If somehow the update failed we want to ensure that the
            # failure is logged (but not try rescheduling since the volume at
            # this point has been created).
            LOG.exception("Failed updating model of volume %(volume_id)s "
                          "with creation provided model %(model)s",
                          {'volume_id': volume_id, 'model': model_update})
            raise

    def _cleanup_cg_in_volume(self, volume):
        # NOTE(xyang): Cannot have both group_id and consistencygroup_id.
        # consistencygroup_id needs to be removed to avoid DB reference
        # error because there isn't an entry in the consistencygroups table.
        if (('group_id' in volume and volume.group_id) and
                ('consistencygroup_id' in volume and
                 volume.consistencygroup_id)):
            volume.consistencygroup_id = None
            if 'consistencygroup' in volume:
                volume.consistencygroup = None


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
            # 'creating' if this fails)??
            volume.update(update)
            volume.save()
            # Now use the parent to notify.
            super(CreateVolumeOnFinishTask, self).execute(context, volume)
        except exception.CinderException:
            LOG.exception("Failed updating volume %(volume_id)s with "
                          "%(update)s", {'volume_id': volume.id,
                                         'update': update})
        # Even if the update fails, the volume is ready.
        LOG.info("Volume %(volume_name)s (%(volume_id)s): "
                 "created successfully",
                 {'volume_name': volume_spec['volume_name'],
                  'volume_id': volume.id})


def get_flow(context, manager, db, driver, scheduler_rpcapi, host, volume,
             allow_reschedule, reschedule_context, request_spec,
             filter_properties, image_volume_cache=None):

    """Constructs and returns the manager entrypoint flow.

    This flow will do the following:

    1. Determines if rescheduling is enabled (ahead of time).
    2. Inject keys & values for dependent tasks.
    3. Selects 1 of 2 activated only on *failure* tasks (one to update the db
       status & notify or one to update the db status & notify & *reschedule*).
    4. Extracts a volume specification from the provided inputs.
    5. Notifies that the volume has started to be created.
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
        'request_spec': request_spec,
        'volume': volume,
    }

    volume_flow.add(ExtractVolumeRefTask(db, host, set_error=False))

    retry = filter_properties.get('retry', None)

    # Always add OnFailureRescheduleTask and we handle the change of volume's
    # status when reverting the flow. Meanwhile, no need to revert process of
    # ExtractVolumeRefTask.
    do_reschedule = allow_reschedule and request_spec and retry
    volume_flow.add(OnFailureRescheduleTask(reschedule_context, db, driver,
                                            scheduler_rpcapi, do_reschedule))

    LOG.debug("Volume reschedule parameters: %(allow)s "
              "retry: %(retry)s", {'allow': allow_reschedule, 'retry': retry})

    volume_flow.add(ExtractVolumeSpecTask(db),
                    NotifyVolumeActionTask(db, "create.start"),
                    CreateVolumeFromSpecTask(manager,
                                             db,
                                             driver,
                                             image_volume_cache),
                    CreateVolumeOnFinishTask(db, "create.end"))

    # Now load (but do not run) the flow using the provided initial data.
    return taskflow.engines.load(volume_flow, store=create_what)
