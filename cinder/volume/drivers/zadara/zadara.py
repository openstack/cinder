# Copyright (c) 2019 Zadara Storage, Inc.
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
"""Volume driver for Zadara Virtual Private Storage Array (VPSA).

This driver requires VPSA with API version 15.07 or higher.
"""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import strutils
import six

from cinder import exception as cinder_exception
from cinder.i18n import _
from cinder import interface
from cinder.objects import fields
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.zadara import common
from cinder.volume.drivers.zadara import exception as zadara_exception
from cinder.volume import volume_utils

CONF = cfg.CONF
CONF.register_opts(common.zadara_opts, group=configuration.SHARED_CONF_GROUP)

LOG = logging.getLogger(__name__)

cinder_opts = [
    cfg.BoolOpt('zadara_use_iser',
                default=True,
                help='VPSA - Use ISER instead of iSCSI'),
    cfg.StrOpt('zadara_vol_name_template',
               default='OS_%s',
               help='VPSA - Default template for VPSA volume names')]


@interface.volumedriver
class ZadaraVPSAISCSIDriver(driver.ISCSIDriver):
    """Zadara VPSA iSCSI/iSER volume driver.

    .. code-block:: none

      Version history:
        15.07 - Initial driver
        16.05 - Move from httplib to requests
        19.08 - Add API access key authentication option
        20.01 - Move to json format from xml. Provide manage/unmanage
                volume/snapshot feature
        20.12-01 - Merging with the common code for all the openstack drivers
        20.12-02 - Common code changed as part of fixing
                   Zadara github issue #18723
        20.12-03 - Adding the metadata support while creating volume to
                   configure vpsa.
        20.12-20 - IPv6 connectivity support for Cinder driver
        20.12-24 - Optimizing get manageable volumes and snapshots
    """

    VERSION = '20.12-24'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "ZadaraStorage_VPSA_CI"

    def __init__(self, *args, **kwargs):
        super(ZadaraVPSAISCSIDriver, self).__init__(*args, **kwargs)
        self.vpsa = None
        self.configuration.append_config_values(common.zadara_opts)
        self.configuration.append_config_values(cinder_opts)
        # The valid list of volume options that can be specified
        # as the metadata while creating cinder volume
        self.vol_options = ['crypt', 'compress',
                            'dedupe', 'attachpolicies']

    @staticmethod
    def get_driver_options():
        driver_opts = []
        driver_opts.extend(common.zadara_opts)
        driver_opts.extend(cinder_opts)
        return driver_opts

    def _check_access_key_validity(self):
        try:
            self.vpsa._check_access_key_validity()
        except common.exception.ZadaraInvalidAccessKey:
            raise zadara_exception.ZadaraCinderInvalidAccessKey()

    def do_setup(self, context):
        """Any initialization the volume driver does while starting.

        Establishes initial connection with VPSA and retrieves access_key.
        Need to pass driver_ssl_cert_path here (and not fetch it from the
        config opts directly in common code), because this config option is
        different for different drivers and so cannot be figured in the
        common code.
        """
        driver_ssl_cert_path = self.configuration.driver_ssl_cert_path
        self.vpsa = common.ZadaraVPSAConnection(self.configuration,
                                                driver_ssl_cert_path, True)
        self._check_access_key_validity()

    def check_for_setup_error(self):
        """Returns an error (exception) if prerequisites aren't met."""
        self._check_access_key_validity()

    def local_path(self, volume):
        """Return local path to existing local volume."""
        raise NotImplementedError()

    def _get_zadara_vol_template_name(self, vol_name):
        return self.configuration.zadara_vol_name_template % vol_name

    def _get_vpsa_volume(self, volume, raise_exception=True):
        vpsa_volume = None
        if volume.provider_location:
            vpsa_volume = (self.vpsa._get_vpsa_volume_by_id(
                           volume.provider_location))
        else:
            vol_name = self._get_zadara_vol_template_name(volume.name)
            vpsa_volume = self.vpsa._get_vpsa_volume(vol_name)

        if not vpsa_volume:
            vol_name = self._get_zadara_vol_template_name(volume.name)
            msg = (_('Backend Volume %(name)s not found') % {'name': vol_name})
            if raise_exception:
                LOG.error(msg)
                raise cinder_exception.VolumeDriverException(message=msg)
            LOG.warning(msg)
        return vpsa_volume

    def vpsa_send_cmd(self, cmd, **kwargs):
        try:
            response = self.vpsa.send_cmd(cmd, **kwargs)
        except common.exception.UnknownCmd as e:
            raise cinder_exception.UnknownCmd(cmd=e.cmd)
        except common.exception.SessionRequestException as e:
            raise zadara_exception.ZadaraSessionRequestException(msg=e.msg)
        except common.exception.BadHTTPResponseStatus as e:
            raise cinder_exception.BadHTTPResponseStatus(status=e.status)
        except common.exception.FailedCmdWithDump as e:
            raise cinder_exception.FailedCmdWithDump(status=e.status,
                                                     data=e.data)
        except common.exception.ZadaraInvalidAccessKey:
            raise zadara_exception.ZadaraCinderInvalidAccessKey()
        return response

    def _validate_existing_ref(self, existing_ref):
        """Validates existing ref"""
        if not existing_ref.get('name'):
            raise cinder_exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=_("manage_existing requires a 'name'"
                         " key to identify an existing volume."))

    def _get_volume_metadata(self, volume):
        if 'metadata' in volume:
            return volume.metadata
        if 'volume_metadata' in volume:
            metadata = volume.volume_metadata
            return {m['key']: m['value'] for m in metadata}
        return {}

    def is_valid_metadata(self, metadata):
        LOG.debug('Metadata while creating volume: %(metadata)s',
                  {'metadata': metadata})
        # Check the values allowed for provided metadata
        return all(value in ('YES', 'NO')
                   for key, value in metadata.items()
                   if key in self.vol_options)

    def create_volume(self, volume):
        """Create volume."""
        vol_name = self._get_zadara_vol_template_name(volume.name)

        # Collect the volume metadata if any provided and validate it
        metadata = self._get_volume_metadata(volume)
        if not self.is_valid_metadata(metadata):
            msg = (_('Invalid metadata for Volume %s') % vol_name)
            LOG.error(msg)
            raise cinder_exception.VolumeDriverException(message=msg)

        data = self.vpsa_send_cmd('create_volume',
                                  name=vol_name,
                                  size=volume.size,
                                  metadata=metadata)

        return {'provider_location': data.get('vol_name')}

    def delete_volume(self, volume):
        """Delete volume.

        Return ok if doesn't exist. Auto detach from all servers.
        """
        vpsa_volume = self._get_vpsa_volume(volume, False)
        if not vpsa_volume:
            return

        self.vpsa._detach_vpsa_volume(vpsa_vol=vpsa_volume)

        # Delete volume
        self.vpsa_send_cmd('delete_volume', vpsa_vol=vpsa_volume['name'])

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""

        LOG.debug('Create snapshot: %s', snapshot.name)

        vpsa_volume = self._get_vpsa_volume(snapshot.volume)
        # Retrieve the CG name for the base volume
        cg_name = vpsa_volume['cg_name']
        data = self.vpsa_send_cmd('create_snapshot',
                                  cg_name=cg_name,
                                  snap_name=snapshot.name)

        return {'provider_location': data.get('snapshot_name')}

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""

        LOG.debug('Delete snapshot: %s', snapshot.name)

        vpsa_volume = self._get_vpsa_volume(snapshot.volume, False)
        if not vpsa_volume:
            # If the volume isn't present, then don't attempt to delete
            return

        # Retrieve the CG name for the base volume
        cg_name = vpsa_volume['cg_name']
        snap_id = self.vpsa._get_snap_id(cg_name, snapshot.name)
        if not snap_id:
            # If the snapshot isn't present, then don't attempt to delete
            LOG.warning('snapshot: snapshot %s not found, '
                        'skipping delete operation', snapshot.name)
            return

        self.vpsa_send_cmd('delete_snapshot',
                           snap_id=snap_id)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""

        LOG.debug('Creating volume from snapshot: %s', snapshot.name)

        vpsa_volume = self._get_vpsa_volume(snapshot.volume, False)
        if not vpsa_volume:
            LOG.error('Snapshot %(name)s not found.',
                      {'name': snapshot.name})
            raise cinder_exception.SnapshotNotFound(snapshot_id=snapshot.id)

        # Retrieve the CG name for the base volume
        cg_name = vpsa_volume['cg_name']
        snap_id = self.vpsa._get_snap_id(cg_name, snapshot.name)
        if not snap_id:
            LOG.error('Snapshot %(name)s not found',
                      {'name': snapshot.name})
            raise cinder_exception.SnapshotNotFound(snapshot_id=snapshot.id)

        volume_name = self._get_zadara_vol_template_name(volume.name)
        self.vpsa_send_cmd('create_clone_from_snap',
                           cg_name=cg_name,
                           name=volume_name,
                           snap_id=snap_id)

        vpsa_volume = self._get_vpsa_volume(volume)
        if volume.size > snapshot.volume_size:
            self.extend_volume(volume, volume.size)
        return {'provider_location': vpsa_volume.get('name')}

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""

        LOG.debug('Creating clone of volume: %s', src_vref.name)

        vpsa_volume = self._get_vpsa_volume(src_vref)
        # Retrieve the CG name for the base volume
        cg_name = vpsa_volume['cg_name']
        volume_name = self._get_zadara_vol_template_name(volume.name)
        self.vpsa_send_cmd('create_clone',
                           cg_name=cg_name,
                           name=volume_name)

        vpsa_volume = self._get_vpsa_volume(volume)
        if volume.size > src_vref.size:
            self.extend_volume(volume, volume.size)
        return {'provider_location': vpsa_volume.get('name')}

    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        # Get volume
        vpsa_volume = self._get_vpsa_volume(volume)
        size = vpsa_volume['virtual_capacity']
        if new_size < size:
            raise cinder_exception.InvalidInput(
                reason=_('%(new_size)s < current size %(size)s') %
                {'new_size': new_size, 'size': size})

        expand_size = new_size - size
        self.vpsa_send_cmd('expand_volume',
                           vpsa_vol=vpsa_volume['name'],
                           size=expand_size)

    def create_export(self, context, volume, vg=None):
        """Irrelevant for VPSA volumes. Export created during attachment."""
        pass

    def ensure_export(self, context, volume):
        """Irrelevant for VPSA volumes. Export created during attachment."""
        pass

    def remove_export(self, context, volume):
        """Irrelevant for VPSA volumes. Export removed during detach."""
        pass

    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        """List volumes on the backend available for management by Cinder"""
        # Get all vpsa volumes
        all_vpsa_volumes = self.vpsa._get_all_vpsa_volumes()

        # Create a dictionary of existing volumes
        existing_vols = {}
        for cinder_vol in cinder_volumes:
            if cinder_vol.provider_location:
                volumes = (list(filter(lambda volume:
                           (volume['name'] == cinder_vol.provider_location),
                           all_vpsa_volumes)))
            else:
                cinder_name = (self._get_zadara_vol_template_name(
                               cinder_vol.name))
                volumes = (list(filter(lambda volume:
                                (volume['display_name'] == cinder_name),
                                all_vpsa_volumes)))
            for volume in volumes:
                existing_vols[volume['name']] = cinder_vol.id

        # Filter out all volumes already attached to any server
        volumes_in_use = {}
        volumes_not_available = {}
        for volume in all_vpsa_volumes:
            if volume['name'] in existing_vols:
                continue

            if volume['status'] == 'In-use':
                volumes_in_use[volume['name']] =\
                    self.vpsa._get_servers_attached_to_volume(volume)
                continue

            if volume['status'] != 'Available':
                volumes_not_available[volume['name']] = volume['display_name']
                continue

        manageable_vols = []
        for vpsa_volume in all_vpsa_volumes:
            vol_name = vpsa_volume['name']
            vol_display_name = vpsa_volume['display_name']
            cinder_id = existing_vols.get(vol_name)
            not_safe_msgs = []

            if vol_name in volumes_in_use:
                host_list = volumes_in_use[vol_name]
                not_safe_msgs.append(_('Volume connected to host(s) %s')
                                     % host_list)

            elif vol_name in volumes_not_available:
                not_safe_msgs.append(_('Volume not available'))

            if cinder_id:
                not_safe_msgs.append(_('Volume already managed'))

            is_safe = (len(not_safe_msgs) == 0)
            reason_not_safe = ' && '.join(not_safe_msgs)

            manageable_vols.append({
                'reference': {'name': vol_display_name},
                'size': vpsa_volume['virtual_capacity'],
                'safe_to_manage': is_safe,
                'reason_not_safe': reason_not_safe,
                'cinder_id': cinder_id,
            })

        return volume_utils.paginate_entries_list(
            manageable_vols, marker, limit, offset, sort_keys, sort_dirs)

    def manage_existing(self, volume, existing_ref):
        """Bring an existing volume into cinder management"""
        self._validate_existing_ref(existing_ref)

        # Check if the volume exists in vpsa
        name = existing_ref['name']
        vpsa_volume = self.vpsa._get_vpsa_volume(name)
        if not vpsa_volume:
            msg = (_('Volume %(name)s could not be found. '
                     'It might be already deleted') % {'name': name})
            LOG.error(msg)
            raise cinder_exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=msg)

        # Check if the volume is available
        if vpsa_volume['status'] != 'Available':
            msg = (_('Existing volume %(name)s is not available')
                   % {'name': name})
            LOG.error(msg)
            raise cinder_exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=msg)

        # Rename the volume to cinder specified name
        new_name = self._get_zadara_vol_template_name(volume.name)
        new_vpsa_volume = self.vpsa._get_vpsa_volume(new_name)
        if new_vpsa_volume:
            msg = (_('Volume %(new_name)s already exists')
                   % {'new_name': new_name})
            LOG.error(msg)
            raise cinder_exception.VolumeDriverException(message=msg)

        data = self.vpsa_send_cmd('rename_volume',
                                  vpsa_vol=vpsa_volume['name'],
                                  new_name=new_name)
        return {'provider_location': data.get('vol_name')}

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing"""
        # Check if the volume exists in vpsa
        self._validate_existing_ref(existing_ref)
        name = existing_ref['name']
        vpsa_volume = self.vpsa._get_vpsa_volume(name)
        if not vpsa_volume:
            msg = (_('Volume %(name)s could not be found. '
                     'It might be already deleted') % {'name': volume.name})
            LOG.error(msg)
            raise cinder_exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=msg)

        # Return the size of the volume
        return vpsa_volume['virtual_capacity']

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management"""
        pass

    def get_manageable_snapshots(self, cinder_snapshots, marker, limit, offset,
                                 sort_keys, sort_dirs):
        """Interface to support listing manageable snapshots and volumes"""
        # Get all snapshots
        vpsa_snapshots = self.vpsa._get_all_vpsa_snapshots()

        # Get all snapshots of all volumes
        all_vpsa_snapshots = []
        for vpsa_snap in vpsa_snapshots:
            if (vpsa_snap['pool_name'] ==
                    self.configuration.zadara_vpsa_poolname):
                vpsa_snap['volume_name'] = vpsa_snap['volume_display_name']
                vpsa_snap['size'] = float(vpsa_snap['volume_capacity_mb'] /
                                          1024)
                all_vpsa_snapshots.append(vpsa_snap)

        existing_snapshots = {}
        for cinder_snapshot in cinder_snapshots:
            if cinder_snapshot.provider_location:
                snapshots = (list(filter(lambda snapshot:
                             ((snapshot['volume_ext_name'] ==
                               cinder_snapshot.volume.provider_location) and
                              (snapshot['name'] ==
                               cinder_snapshot.provider_location)),
                             all_vpsa_snapshots)))
            else:
                volume_name = (self._get_zadara_vol_template_name(
                    cinder_snapshot.volume_name))
                snapshots = (list(filter(lambda snapshot:
                             ((snapshot['volume_display_name'] ==
                               volume_name) and
                              (snapshot['display_name'] ==
                               cinder_snapshot.name)),
                             all_vpsa_snapshots)))
            for snapshot in snapshots:
                existing_snapshots[snapshot['name']] = cinder_snapshot.id

        manageable_snapshots = []
        try:
            unique_snapshots = []
            for snapshot in all_vpsa_snapshots:
                snap_id = snapshot['name']
                if snap_id in unique_snapshots:
                    continue

                cinder_id = existing_snapshots.get(snap_id)
                is_safe = True
                reason_not_safe = None

                if cinder_id:
                    is_safe = False
                    reason_not_safe = _("Snapshot already managed.")

                manageable_snapshots.append({
                    'reference': {'name': snapshot['display_name']},
                    'size': snapshot['size'],
                    'safe_to_manage': is_safe,
                    'reason_not_safe': reason_not_safe,
                    'cinder_id': cinder_id,
                    'extra_info': None,
                    'source_reference': {'name': snapshot['volume_name']},
                })

                unique_snapshots.append(snap_id)
            return volume_utils.paginate_entries_list(
                manageable_snapshots, marker, limit, offset,
                sort_keys, sort_dirs)
        except Exception as e:
            msg = (_('Exception: %s') % six.text_type(e))
            LOG.error(msg)
            raise

    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Brings an existing backend storage object under Cinder management"""
        self._validate_existing_ref(existing_ref)

        snap_name = existing_ref['name']
        volume = self._get_vpsa_volume(snapshot.volume, False)
        if not volume:
            msg = (_('Source volume of snapshot %s could not be found.'
                     ' Invalid data') % snap_name)
            LOG.error(msg)
            raise cinder_exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=msg)

        # Check if the snapshot exists
        snap_id = self.vpsa._get_snap_id(volume['cg_name'], snap_name)
        if not snap_id:
            msg = (_('Snapshot %s could not be found. It might be'
                     ' already deleted') % snap_name)
            LOG.error(msg)
            raise cinder_exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=msg)

        new_name = snapshot.name
        new_snap_id = self.vpsa._get_snap_id(volume['cg_name'], new_name)
        if new_snap_id:
            msg = (_('Snapshot with name %s already exists') % new_name)
            LOG.debug(msg)
            return

        data = self.vpsa_send_cmd('rename_snapshot',
                                  snap_id=snap_id,
                                  new_name=new_name)
        return {'provider_location': data.get('snapshot_name')}

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return size of snapshot to be managed by manage_existing"""
        # We do not have any size field for a snapshot.
        # We only have it on volumes. So, here just figure
        # out the parent volume of this snapshot and return its size
        self._validate_existing_ref(existing_ref)
        snap_name = existing_ref['name']
        volume = self._get_vpsa_volume(snapshot.volume, False)
        if not volume:
            msg = (_('Source volume of snapshot %s could not be found.'
                     ' Invalid data') % snap_name)
            LOG.error(msg)
            raise cinder_exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=msg)

        snap_id = self.vpsa._get_snap_id(volume['cg_name'], snap_name)
        if not snap_id:
            msg = (_('Snapshot %s could not be found. It might be '
                     'already deleted') % snap_name)
            LOG.error(msg)
            raise cinder_exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=msg)

        return volume['virtual_capacity']

    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management"""
        pass

    def initialize_connection(self, volume, connector):
        """Attach volume to initiator/host.

        During this call VPSA exposes volume to particular Initiator. It also
        creates a 'server' entity for Initiator (if it was not created before)
        All necessary connection information is returned, including auth data.
        Connection data (target, LUN) is not stored in the DB.
        """
        # First: Check Active controller: if not valid, raise exception
        ctrl = self.vpsa._get_active_controller_details()
        if not ctrl:
            raise zadara_exception.ZadaraVPSANoActiveController()

        # Get/Create server name for IQN
        initiator_name = connector['initiator']
        vpsa_srv = self.vpsa._create_vpsa_server(iqn=initiator_name)
        if not vpsa_srv:
            raise zadara_exception.ZadaraServerCreateFailure(
                name=initiator_name)

        # Get volume
        vpsa_volume = self._get_vpsa_volume(volume)
        servers = self.vpsa._get_servers_attached_to_volume(vpsa_volume)
        attach = None
        for server in servers:
            if server == vpsa_srv:
                attach = server
                break
        # Attach volume to server
        if attach is None:
            self.vpsa_send_cmd('attach_volume',
                               vpsa_srv=vpsa_srv,
                               vpsa_vol=vpsa_volume['name'])

        data = self.vpsa_send_cmd('list_vol_attachments',
                                  vpsa_vol=vpsa_volume['name'])
        server = None
        servers = data.get('servers', [])
        for srv in servers:
            if srv['iqn'] == initiator_name:
                server = srv
                break

        if server is None:
            vol_name = (self._get_zadara_vol_template_name(
                        volume.name))
            raise zadara_exception.ZadaraAttachmentsNotFound(
                name=vol_name)

        target = server['target']
        lun = int(server['lun'])
        if None in [target, lun]:
            vol_name = (self._get_zadara_vol_template_name(
                        volume.name))
            raise zadara_exception.ZadaraInvalidAttachmentInfo(
                name=vol_name,
                reason=_('target=%(target)s, lun=%(lun)s') %
                {'target': target, 'lun': lun})

        ctrl_ip = self.vpsa._get_target_host(ctrl['ip'])
        properties = {'target_discovered': False,
                      'target_portal': (('%s:%s') % (ctrl_ip, '3260')),
                      'target_iqn': target,
                      'target_lun': lun,
                      'volume_id': volume.id,
                      'auth_method': 'CHAP',
                      'auth_username': ctrl['chap_user'],
                      'auth_password': ctrl['chap_passwd']}

        LOG.debug('Attach properties: %(properties)s',
                  {'properties': strutils.mask_password(properties)})
        return {'driver_volume_type':
                ('iser' if (self.configuration.safe_get('zadara_use_iser'))
                 else 'iscsi'), 'data': properties}

    def terminate_connection(self, volume, connector, **kwargs):
        """Detach volume from the initiator."""

        vpsa_volume = self._get_vpsa_volume(volume)

        if connector is None:
            # Detach volume from all servers
            # Get volume name
            self.vpsa._detach_vpsa_volume(vpsa_vol=vpsa_volume)
            return

        # Check if there are multiple attachments to the volume from the
        # same host. Terminate connection only for the last attachment from
        # the corresponding host.
        count = 0
        host = connector.get('host') if connector else None
        if host and volume.get('multiattach'):
            attach_list = volume.volume_attachment
            for attachment in attach_list:
                if (attachment['attach_status'] !=
                        fields.VolumeAttachStatus.ATTACHED):
                    continue
                if attachment.attached_host == host:
                    count += 1
        if count > 1:
            return

        # Get server name for IQN
        initiator_name = connector['initiator']

        vpsa_srv = self.vpsa._get_server_name(initiator_name, False)
        if not vpsa_srv:
            raise zadara_exception.ZadaraServerNotFound(name=initiator_name)

        if not vpsa_volume:
            raise cinder_exception.VolumeNotFound(volume_id=volume.id)

        # Detach volume from server
        self.vpsa._detach_vpsa_volume(vpsa_vol=vpsa_volume,
                                      vpsa_srv=vpsa_srv)

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""
        LOG.debug("Updating volume stats")
        backend_name = self.configuration.safe_get('volume_backend_name')
        storage_protocol = ('iSER' if
                            (self.configuration.safe_get('zadara_use_iser'))
                            else 'iSCSI')
        pool_name = self.configuration.zadara_vpsa_poolname
        (total, free, provisioned) = self.vpsa._get_pool_capacity(pool_name)
        data = dict(
            volume_backend_name=backend_name or self.__class__.__name__,
            vendor_name='Zadara Storage',
            driver_version=self.VERSION,
            storage_protocol=storage_protocol,
            reserved_percentage=self.configuration.reserved_percentage,
            QoS_support=False,
            multiattach=True,
            total_capacity_gb=total,
            free_capacity_gb=free
        )

        self._stats = data
