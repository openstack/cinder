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
Volume manager manages creating, attaching, detaching, and persistent storage.

Persistent storage volumes keep their state independent of instances.  You can
attach to an instance, terminate the instance, spawn a new instance (even
one from a different image) and re-attach the volume with the same data
intact.

**Related Flags**

:volume_topic:  What :mod:`rpc` topic to listen to (default: `cinder-volume`).
:volume_manager:  The module name of a class derived from
                  :class:`manager.Manager` (default:
                  :class:`cinder.volume.manager.Manager`).
:volume_driver:  Used by :class:`Manager`.  Defaults to
                 :class:`cinder.volume.driver.ISCSIDriver`.
:volume_group:  Name of the group that will contain exported volumes (default:
                `cinder-volumes`)
:num_shell_tries:  Number of times to attempt to run commands (default: 3)

"""

from cinder import context
from cinder import exception
from cinder import flags
from cinder.image import glance
from cinder import manager
from cinder.openstack.common import cfg
from cinder.openstack.common import excutils
from cinder.openstack.common import importutils
from cinder.openstack.common import lockutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
from cinder.openstack.common import uuidutils
from cinder import quota
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)

QUOTAS = quota.QUOTAS

volume_manager_opts = [
    cfg.StrOpt('volume_driver',
               default='cinder.volume.driver.ISCSIDriver',
               help='Driver to use for volume creation'),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(volume_manager_opts)

MAPPING = {
    'cinder.volume.driver.RBDDriver': 'cinder.volume.drivers.rbd.RBDDriver',
    'cinder.volume.driver.SheepdogDriver':
    'cinder.volume.drivers.sheepdog.SheepdogDriver',
    'cinder.volume.nexenta.volume.NexentaDriver':
    'cinder.volume.drivers.nexenta.volume.NexentaDriver',
    'cinder.volume.san.SanISCSIDriver':
    'cinder.volume.drivers.san.san.SanISCSIDriver',
    'cinder.volume.san.SolarisISCSIDriver':
    'cinder.volume.drivers.san.solaris.SolarisISCSIDriver',
    'cinder.volume.san.HpSanISCSIDriver':
    'cinder.volume.drivers.san.hp_lefthand.HpSanISCSIDriver',
    'cinder.volume.netapp.NetAppISCSIDriver':
    'cinder.volume.drivers.netapp.NetAppISCSIDriver',
    'cinder.volume.netapp.NetAppCmodeISCSIDriver':
    'cinder.volume.drivers.netapp.NetAppCmodeISCSIDriver',
    'cinder.volume.netapp_nfs.NetAppNFSDriver':
    'cinder.volume.drivers.netapp_nfs.NetAppNFSDriver',
    'cinder.volume.nfs.NfsDriver':
    'cinder.volume.drivers.nfs.NfsDriver',
    'cinder.volume.solidfire.SolidFire':
    'cinder.volume.drivers.solidfire.SolidFire',
    'cinder.volume.storwize_svc.StorwizeSVCDriver':
    'cinder.volume.drivers.storwize_svc.StorwizeSVCDriver',
    'cinder.volume.windows.WindowsDriver':
    'cinder.volume.drivers.windows.WindowsDriver',
    'cinder.volume.xiv.XIVDriver':
    'cinder.volume.drivers.xiv.XIVDriver',
    'cinder.volume.zadara.ZadaraVPSAISCSIDriver':
    'cinder.volume.drivers.zadara.ZadaraVPSAISCSIDriver'}


class VolumeManager(manager.SchedulerDependentManager):
    """Manages attachable block storage devices."""

    RPC_API_VERSION = '1.2'

    def __init__(self, volume_driver=None, *args, **kwargs):
        """Load the driver from the one specified in args, or from flags."""
        if not volume_driver:
            volume_driver = FLAGS.volume_driver
        if volume_driver in MAPPING:
            LOG.warn(_("Driver path %s is deprecated, update your "
                       "configuration to the new path."), volume_driver)
            self.driver = importutils.import_object(MAPPING[volume_driver])
        else:
            self.driver = importutils.import_object(volume_driver)
        super(VolumeManager, self).__init__(service_name='volume',
                                            *args, **kwargs)
        # NOTE(vish): Implementation specific db handling is done
        #             by the driver.
        self.driver.db = self.db

    def init_host(self):
        """Do any initialization that needs to be run if this is a
           standalone service."""

        ctxt = context.get_admin_context()
        self.driver.do_setup(ctxt)
        self.driver.check_for_setup_error()

        volumes = self.db.volume_get_all_by_host(ctxt, self.host)
        LOG.debug(_("Re-exporting %s volumes"), len(volumes))
        for volume in volumes:
            if volume['status'] in ['available', 'in-use']:
                self.driver.ensure_export(ctxt, volume)
            else:
                LOG.info(_("volume %s: skipping export"), volume['name'])

        LOG.debug(_('Resuming any in progress delete operations'))
        for volume in volumes:
            if volume['status'] == 'deleting':
                LOG.info(_('Resuming delete on volume: %s') % volume['id'])
                self.delete_volume(ctxt, volume['id'])

        # collect and publish service capabilities
        self.publish_service_capabilities(ctxt)

    def create_volume(self, context, volume_id, snapshot_id=None,
                      image_id=None, source_volid=None):
        """Creates and exports the volume."""
        context = context.elevated()
        volume_ref = self.db.volume_get(context, volume_id)
        self._notify_about_volume_usage(context, volume_ref, "create.start")
        LOG.info(_("volume %s: creating"), volume_ref['name'])

        # NOTE(vish): so we don't have to get volume from db again
        #             before passing it to the driver.
        volume_ref['host'] = self.host

        status = 'available'
        model_update = False
        image_meta = None

        try:
            vol_name = volume_ref['name']
            vol_size = volume_ref['size']
            LOG.debug(_("volume %(vol_name)s: creating lv of"
                        " size %(vol_size)sG") % locals())
            if all(x is None for x in(snapshot_id, image_id, source_volid)):
                model_update = self.driver.create_volume(volume_ref)
            elif snapshot_id is not None:
                snapshot_ref = self.db.snapshot_get(context, snapshot_id)
                model_update = self.driver.create_volume_from_snapshot(
                    volume_ref,
                    snapshot_ref)
            elif source_volid is not None:
                src_vref = self.db.volume_get(context, source_volid)
                model_update = self.driver.create_cloned_volume(volume_ref,
                                                                src_vref)
            else:
                # create the volume from an image
                image_service, image_id = \
                    glance.get_remote_image_service(context,
                                                    image_id)
                image_location = image_service.get_location(context, image_id)
                image_meta = image_service.show(context, image_id)
                cloned = self.driver.clone_image(volume_ref, image_location)
                if not cloned:
                    model_update = self.driver.create_volume(volume_ref)
                    status = 'downloading'

            if model_update:
                self.db.volume_update(context, volume_ref['id'], model_update)

            LOG.debug(_("volume %s: creating export"), volume_ref['name'])
            model_update = self.driver.create_export(context, volume_ref)
            if model_update:
                self.db.volume_update(context, volume_ref['id'], model_update)

        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.volume_update(context,
                                      volume_ref['id'], {'status': 'error'})

        if snapshot_id:
            # Copy any Glance metadata from the original volume
            self.db.volume_glance_metadata_copy_to_volume(context,
                                                          volume_ref['id'],
                                                          snapshot_id)

        now = timeutils.utcnow()
        self.db.volume_update(context,
                              volume_ref['id'], {'status': status,
                                                 'launched_at': now})
        LOG.debug(_("volume %s: created successfully"), volume_ref['name'])
        self._reset_stats()

        if image_id and not cloned:
            if image_meta:
                # Copy all of the Glance image properties to the
                # volume_glance_metadata table for future reference.
                self.db.volume_glance_metadata_create(context,
                                                      volume_ref['id'],
                                                      'image_id', image_id)
                name = image_meta.get('name', None)
                if name:
                    self.db.volume_glance_metadata_create(context,
                                                          volume_ref['id'],
                                                          'image_name', name)
                image_properties = image_meta.get('properties', {})
                for key, value in image_properties.items():
                    self.db.volume_glance_metadata_create(context,
                                                          volume_ref['id'],
                                                          key, value)

            #copy the image onto the volume.
            self._copy_image_to_volume(context, volume_ref, image_id)
        self._notify_about_volume_usage(context, volume_ref, "create.end")
        return volume_ref['id']

    def delete_volume(self, context, volume_id):
        """Deletes and unexports volume."""
        context = context.elevated()
        volume_ref = self.db.volume_get(context, volume_id)
        if volume_ref['attach_status'] == "attached":
            # Volume is still attached, need to detach first
            raise exception.VolumeAttached(volume_id=volume_id)
        if volume_ref['host'] != self.host:
            raise exception.InvalidVolume(
                reason=_("Volume is not local to this node"))

        self._notify_about_volume_usage(context, volume_ref, "delete.start")
        self._reset_stats()
        try:
            LOG.debug(_("volume %s: removing export"), volume_ref['name'])
            self.driver.remove_export(context, volume_ref)
            LOG.debug(_("volume %s: deleting"), volume_ref['name'])
            self.driver.delete_volume(volume_ref)
        except exception.VolumeIsBusy:
            LOG.debug(_("volume %s: volume is busy"), volume_ref['name'])
            self.driver.ensure_export(context, volume_ref)
            self.db.volume_update(context, volume_ref['id'],
                                  {'status': 'available'})
            return True
        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.volume_update(context,
                                      volume_ref['id'],
                                      {'status': 'error_deleting'})

        # Get reservations
        try:
            reservations = QUOTAS.reserve(context, volumes=-1,
                                          gigabytes=-volume_ref['size'])
        except Exception:
            reservations = None
            LOG.exception(_("Failed to update usages deleting volume"))

        self.db.volume_glance_metadata_delete_by_volume(context, volume_id)
        self.db.volume_destroy(context, volume_id)
        LOG.debug(_("volume %s: deleted successfully"), volume_ref['name'])
        self._notify_about_volume_usage(context, volume_ref, "delete.end")

        # Commit the reservations
        if reservations:
            QUOTAS.commit(context, reservations)

        return True

    def create_snapshot(self, context, volume_id, snapshot_id):
        """Creates and exports the snapshot."""
        context = context.elevated()
        snapshot_ref = self.db.snapshot_get(context, snapshot_id)
        LOG.info(_("snapshot %s: creating"), snapshot_ref['name'])

        try:
            snap_name = snapshot_ref['name']
            LOG.debug(_("snapshot %(snap_name)s: creating") % locals())
            model_update = self.driver.create_snapshot(snapshot_ref)
            if model_update:
                self.db.snapshot_update(context, snapshot_ref['id'],
                                        model_update)

        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.snapshot_update(context,
                                        snapshot_ref['id'],
                                        {'status': 'error'})

        self.db.snapshot_update(context,
                                snapshot_ref['id'], {'status': 'available',
                                                     'progress': '100%'})
        self.db.volume_glance_metadata_copy_to_snapshot(context,
                                                        snapshot_ref['id'],
                                                        volume_id)
        LOG.debug(_("snapshot %s: created successfully"), snapshot_ref['name'])
        return snapshot_id

    def delete_snapshot(self, context, snapshot_id):
        """Deletes and unexports snapshot."""
        context = context.elevated()
        snapshot_ref = self.db.snapshot_get(context, snapshot_id)

        try:
            LOG.debug(_("snapshot %s: deleting"), snapshot_ref['name'])
            self.driver.delete_snapshot(snapshot_ref)
        except exception.SnapshotIsBusy:
            LOG.debug(_("snapshot %s: snapshot is busy"), snapshot_ref['name'])
            self.db.snapshot_update(context,
                                    snapshot_ref['id'],
                                    {'status': 'available'})
            return True
        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.snapshot_update(context,
                                        snapshot_ref['id'],
                                        {'status': 'error_deleting'})

        self.db.volume_glance_metadata_delete_by_snapshot(context, snapshot_id)
        self.db.snapshot_destroy(context, snapshot_id)
        LOG.debug(_("snapshot %s: deleted successfully"), snapshot_ref['name'])
        return True

    def attach_volume(self, context, volume_id, instance_uuid, mountpoint):
        """Updates db to show volume is attached"""

        @lockutils.synchronized(volume_id, 'cinder-', external=True)
        def do_attach():
            # check the volume status before attaching
            volume = self.db.volume_get(context, volume_id)
            if volume['status'] == 'attaching':
                if (volume['instance_uuid'] and volume['instance_uuid'] !=
                        instance_uuid):
                    msg = _("being attached by another instance")
                    raise exception.InvalidVolume(reason=msg)
            elif volume['status'] != "available":
                msg = _("status must be available")
                raise exception.InvalidVolume(reason=msg)
            self.db.volume_update(context, volume_id,
                                  {"instance_uuid": instance_uuid,
                                   "status": "attaching"})

            # TODO(vish): refactor this into a more general "reserve"
            # TODO(sleepsonthefloor): Is this 'elevated' appropriate?
            if not uuidutils.is_uuid_like(instance_uuid):
                raise exception.InvalidUUID(uuid=instance_uuid)

            try:
                self.driver.attach_volume(context,
                                          volume_id,
                                          instance_uuid,
                                          mountpoint)
            except Exception:
                with excutils.save_and_reraise_exception():
                    self.db.volume_update(context,
                                          volume_id,
                                          {'status': 'error_attaching'})

            self.db.volume_attached(context.elevated(),
                                    volume_id,
                                    instance_uuid,
                                    mountpoint)
        return do_attach()

    def detach_volume(self, context, volume_id):
        """Updates db to show volume is detached"""
        # TODO(vish): refactor this into a more general "unreserve"
        # TODO(sleepsonthefloor): Is this 'elevated' appropriate?
        try:
            self.driver.detach_volume(context, volume_id)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.volume_update(context,
                                      volume_id,
                                      {'status': 'error_detaching'})

        self.db.volume_detached(context.elevated(), volume_id)

        # Check for https://bugs.launchpad.net/cinder/+bug/1065702
        volume_ref = self.db.volume_get(context, volume_id)
        if (volume_ref['provider_location'] and
                volume_ref['name'] not in volume_ref['provider_location']):
            self.driver.ensure_export(context, volume_ref)

    def _copy_image_to_volume(self, context, volume, image_id):
        """Downloads Glance image to the specified volume. """
        volume_id = volume['id']
        payload = {'volume_id': volume_id, 'image_id': image_id}
        try:
            image_service, image_id = glance.get_remote_image_service(context,
                                                                      image_id)
            self.driver.copy_image_to_volume(context, volume, image_service,
                                             image_id)
            LOG.debug(_("Downloaded image %(image_id)s to %(volume_id)s "
                        "successfully") % locals())
            self.db.volume_update(context, volume_id,
                                  {'status': 'available'})
        except Exception, error:
            with excutils.save_and_reraise_exception():
                payload['message'] = unicode(error)
                self.db.volume_update(context, volume_id, {'status': 'error'})

    def copy_volume_to_image(self, context, volume_id, image_id):
        """Uploads the specified volume to Glance."""
        payload = {'volume_id': volume_id, 'image_id': image_id}
        try:
            volume = self.db.volume_get(context, volume_id)
            self.driver.ensure_export(context.elevated(), volume)
            image_service, image_id = glance.get_remote_image_service(context,
                                                                      image_id)
            self.driver.copy_volume_to_image(context, volume, image_service,
                                             image_id)
            LOG.debug(_("Uploaded volume %(volume_id)s to "
                        "image (%(image_id)s) successfully") % locals())
        except Exception, error:
            with excutils.save_and_reraise_exception():
                payload['message'] = unicode(error)
        finally:
            if volume['instance_uuid'] is None:
                self.db.volume_update(context, volume_id,
                                      {'status': 'available'})
            else:
                self.db.volume_update(context, volume_id,
                                      {'status': 'in-use'})

    def initialize_connection(self, context, volume_id, connector):
        """Prepare volume for connection from host represented by connector.

        This method calls the driver initialize_connection and returns
        it to the caller.  The connector parameter is a dictionary with
        information about the host that will connect to the volume in the
        following format::

            {
                'ip': ip,
                'initiator': initiator,
            }

        ip: the ip address of the connecting machine

        initiator: the iscsi initiator name of the connecting machine.
        This can be None if the connecting machine does not support iscsi
        connections.

        driver is responsible for doing any necessary security setup and
        returning a connection_info dictionary in the following format::

            {
                'driver_volume_type': driver_volume_type,
                'data': data,
            }

        driver_volume_type: a string to identify the type of volume.  This
                           can be used by the calling code to determine the
                           strategy for connecting to the volume. This could
                           be 'iscsi', 'rbd', 'sheepdog', etc.

        data: this is the data that the calling code will use to connect
              to the volume. Keep in mind that this will be serialized to
              json in various places, so it should not contain any non-json
              data types.
        """
        volume_ref = self.db.volume_get(context, volume_id)
        return self.driver.initialize_connection(volume_ref, connector)

    def terminate_connection(self, context, volume_id, connector, force=False):
        """Cleanup connection from host represented by connector.

        The format of connector is the same as for initialize_connection.
        """
        volume_ref = self.db.volume_get(context, volume_id)
        self.driver.terminate_connection(volume_ref, connector, force=force)

    @manager.periodic_task
    def _report_driver_status(self, context):
        LOG.info(_("Updating volume status"))
        volume_stats = self.driver.get_volume_stats(refresh=True)
        if volume_stats:
            # This will grab info about the host and queue it
            # to be sent to the Schedulers.
            self.update_service_capabilities(volume_stats)

    def publish_service_capabilities(self, context):
        """ Collect driver status and then publish """
        self._report_driver_status(context)
        self._publish_service_capabilities(context)

    def _reset_stats(self):
        LOG.info(_("Clear capabilities"))
        self._last_volume_stats = []

    def notification(self, context, event):
        LOG.info(_("Notification {%s} received"), event)
        self._reset_stats()

    def _notify_about_volume_usage(self,
                                   context,
                                   volume,
                                   event_suffix,
                                   extra_usage_info=None):
        volume_utils.notify_about_volume_usage(
            context, volume, event_suffix,
            extra_usage_info=extra_usage_info, host=self.host)
