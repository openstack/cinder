# Copyright (c) 2017 Veritas Technologies LLC.  All rights reserved.
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
Cinder Driver for HyperScale
"""

import os

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.veritas import hs_constants as constants
from cinder.volume.drivers.veritas import utils as util

CONF = cfg.CONF
LOG = logging.getLogger(__name__)
TYPE_EPISODIC_SNAP = '0'
TYPE_USER_SNAP = '1'
TYPE_WORKFLOW_SNAP = '2'

BLOCK_SIZE = 8
MAX_REPLICAS = 2
DEFAULT_REPLICAS = 1
POOL_NAME = '{30c39970-ad80-4950-5490-8431abfaaaf0}'
HYPERSCALE_VERSION = '1.0.0'
PROVIDER_LOCATION_MNT = "/hyperscale"
PROVIDER_LOCATION = 'hyperscale-sv:' + PROVIDER_LOCATION_MNT


@interface.volumedriver
class HyperScaleDriver(driver.VolumeDriver):

    VERSION = '1.0'
    # ThirdPartySytems wiki page
    CI_WIKI_NAME = "Veritas_HyperScale_CI"

    def __init__(self, *args, **kwargs):
        """Initialization"""

        super(HyperScaleDriver, self).__init__(*args, **kwargs)

        self.compute_map = {}
        self.vsa_map = {}
        self.compute_meta_map = {}
        self.vsa_compute_map = {}
        self.old_total = 0
        self.old_free = 0
        self.my_dnid = None

    @staticmethod
    def _fetch_config_for_controller():
        return HyperScaleDriver._fetch_config_information(
            persona='controller')

    @staticmethod
    def _fetch_config_for_compute():
        return HyperScaleDriver._fetch_config_information(
            persona='compute')

    @staticmethod
    def _fetch_config_for_datanode():
        return HyperScaleDriver._fetch_config_information(
            persona='datanode')

    @staticmethod
    def _fetch_config_information(persona):
        # Get hyperscale config information for persona
        configuration = util.get_configuration(persona)
        return configuration

    @utils.trace_method
    def check_for_setup_error(self):
        # check if HyperScale has been installed correctly
        try:
            version = util.get_hyperscale_version()

            if version != HYPERSCALE_VERSION:
                raise exception.VolumeBackendAPIException(
                    data=(_("Unsupported version: %s") % version))
        except (exception.ErrorInHyperScaleVersion,
                exception.UnableToExecuteHyperScaleCmd):
            err_msg = _('Exception in getting HyperScale version')
            LOG.exception(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _get_replicas(self, volume, metadata):
        """Get the replicas."""
        try:
            ref_targets = self._get_volume_metadata_value(metadata,
                                                          'reflection_targets')
            if ref_targets is not None:
                replicas = MAX_REPLICAS
            else:
                replicas = DEFAULT_REPLICAS

        except Exception:
            LOG.exception("Exception in getting reflection targets")
            replicas = DEFAULT_REPLICAS

        LOG.debug("Number of replicas: %s", replicas)
        return replicas

    @utils.trace_method
    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(HyperScaleDriver, self).do_setup(context)

        try:
            # Get computes info
            computes = HyperScaleDriver._fetch_config_for_compute()
            if computes is None:
                computes = {}

            for compute in computes.keys():
                if 'disabled' in computes[compute].keys():
                    disabled = computes[compute]['disabled']
                    if disabled == "1":
                        continue
                vsa_ip = computes[compute]['vsa_ip']
                vsa_isolated_ip = computes[compute]['vsa_isolated_ip']
                vsa_section_header = computes[compute]['vsa_section_header']
                compute_name = computes[compute]['compute_name']
                self.compute_map[vsa_ip] = vsa_isolated_ip
                self.vsa_map[vsa_ip] = vsa_section_header
                self.compute_meta_map[compute_name] = vsa_ip
                self.vsa_compute_map[vsa_ip] = compute_name

            # Get controller info
            cntr_info = HyperScaleDriver._fetch_config_for_controller()
            if cntr_info is None:
                cntr_info = {}

            # Get data node info
            self.my_dnid = util.get_datanode_id()
            datanodes = HyperScaleDriver._fetch_config_for_datanode()
            if datanodes is None:
                datanodes = {}

            for key, value in datanodes.items():
                if self.my_dnid == value['hypervisor_id']:
                    self.datanode_hostname = value['datanode_name']
                    self.datanode_ip = value['data_ip']
                    self.dn_routing_key = value['hypervisor_id']

            LOG.debug("In init compute_map %s", self.compute_map)
            LOG.debug("In init vsa_map %s", self.vsa_map)
            LOG.debug("In init compute_meta_map %s", self.compute_meta_map)

        except (exception.UnableToProcessHyperScaleCmdOutput,
                exception.ErrorInFetchingConfiguration):
            err_msg = _("Unable to initialise the Veritas cinder driver")
            LOG.exception(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        except Exception:
            err_msg = _("Internal error occurred")
            LOG.exception(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    @utils.trace_method
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""

        LOG.debug("Clone volume")
        model_update = {}
        try:
            LOG.debug("Clone new volume %(t_id)s from source volume %(s_id)s",
                      {"t_id": volume['id'], "s_id": src_vref['id']})
            # 1. Make a call to DN
            # Check if current_dn_owner is set.

            rt_key = None
            # Get metadata for volume
            metadata = self._get_volume_metadata(src_vref)
            rt_key = self._get_volume_metadata_value(metadata,
                                                     'current_dn_owner')
            if rt_key is None:
                rt_key = self.dn_routing_key

            util.message_data_plane(
                rt_key,
                'hyperscale.storage.dm.volume.clone',
                pool_name=POOL_NAME,
                display_name=util.get_guid_with_curly_brackets(
                    volume['id']),
                version_name=util.get_guid_with_curly_brackets(
                    src_vref['id']),
                volume_raw_size=volume['size'],
                volume_qos=1,
                parent_volume_guid=util.get_guid_with_curly_brackets(
                    src_vref['id']),
                user_id=util.get_guid_with_curly_brackets(
                    volume['user_id']),
                project_id=util.get_guid_with_curly_brackets(
                    volume['project_id']),
                volume_guid=util.get_guid_with_curly_brackets(
                    volume['id']))

            LOG.debug("Volume cloned successfully on data node")

            # Get metadata for volume
            volume_metadata = self._get_volume_metadata(volume)
            parent_cur_dn = self._get_volume_metadata_value(metadata,
                                                            'current_dn_ip')

            metadata_update = {}
            metadata_update['Primary_datanode_ip'] = parent_cur_dn
            metadata_update['current_dn_owner'] = rt_key
            metadata_update['current_dn_ip'] = parent_cur_dn
            metadata_update['source_volid'] = src_vref['id']
            metadata_update['size'] = src_vref['size']

            # 2. Choose a potential replica here.
            # The actual decision to have potential replica is made in NOVA.
            rt_key, rt_dn_ip = self._select_rt(volume,
                                               volume_metadata,
                                               only_select=True)

            if rt_key and rt_dn_ip:
                metadata_update['Potential_secondary_key'] = rt_key
                metadata_update['Potential_secondary_ip'] = rt_dn_ip

        except (exception.UnableToExecuteHyperScaleCmd,
                exception.UnableToProcessHyperScaleCmdOutput):
            with excutils.save_and_reraise_exception():
                LOG.exception('Exception in clone volume', exc_info=True)
        except exception.InvalidMetadataType:
            with excutils.save_and_reraise_exception():
                LOG.exception('Exception updating metadata in clone'
                              ' volume', exc_info=True)

        volume_metadata.update(metadata_update)
        volume['provider_location'] = PROVIDER_LOCATION
        model_update = {'provider_location': volume['provider_location'],
                        'metadata': volume_metadata}

        return model_update

    def _get_datanodes_info(self):
        # Get hyperscale datanode config information from controller

        msg_body = {}
        data = None

        try:
            cmd_out, cmd_error = util.message_controller(
                constants.HS_CONTROLLER_EXCH,
                'hyperscale.controller.get.membership',
                **msg_body)
            LOG.debug("Response Message from Controller: %s",
                      cmd_out)
            payload = cmd_out.get('payload')
            data = payload.get('of_membership')

        except (exception.UnableToExecuteHyperScaleCmd,
                exception.UnableToProcessHyperScaleCmdOutput):
            with excutils.save_and_reraise_exception():
                LOG.exception("Failed to get datanode config "
                              "information from controller")

        return data

    def _select_rt(self, volume, metadata, only_select=False):

        # For the boot vdisk(first vdisk) of the instance, choose any
        # reflection target other than this. For the data disks,
        # retain the reflection target.
        # It will be passed by the caller after reading it from instance
        # metadata.

        LOG.debug("_select_rt ")
        rt_key = self._get_volume_metadata_value(metadata,
                                                 'Secondary_datanode_key')
        rt_dn_ip = self._get_volume_metadata_value(metadata,
                                                   'Secondary_datanode_ip')
        current_dn_ip = self._get_volume_metadata_value(metadata,
                                                        'current_dn_ip')

        if current_dn_ip is not None and rt_dn_ip == current_dn_ip:
            return None, None

        if rt_key is not None and rt_dn_ip is not None:
            return rt_key, rt_dn_ip

        rt_key = 'NA'
        rt_dn_ip = 'NA'
        datanodes = self._get_datanodes_info()
        LOG.debug("Data nodes: %s", datanodes)

        for key, value in datanodes.items():
            if value['personality'] == 'datanode':
                if self.my_dnid != value['hypervisor_id']:
                    LOG.debug("reflection target hypervisor_id: %s",
                              value['hypervisor_id'])
                    LOG.debug("my hypervisor_id: %s", self.my_dnid)
                    rt_dn_ip = value['data_ip']
                    rt_key = value['hypervisor_id']

        if only_select:
            return rt_key, rt_dn_ip

        return rt_key, rt_dn_ip

    def _create_replica(self, volume, metadata):
        """Create vdisk on peer data node."""

        try:
            reflection_target_ip = None
            rt_routing_key, reflection_target_ip = (
                self._select_rt(volume, metadata))
            LOG.debug("_create_replica %(rt_key)s %(rt_ip)s",
                      {"rt_key": rt_routing_key,
                       "rt_ip": reflection_target_ip})

            metadata_update = {}
            metadata_update['Secondary_datanode_key'] = rt_routing_key
            metadata_update['Secondary_datanode_ip'] = reflection_target_ip

            if rt_routing_key is None or rt_routing_key == 'NA':
                return False, None, metadata_update

            instance_id = self._get_volume_metadata_value(metadata,
                                                          'InstanceId')

            util.message_data_plane(
                rt_routing_key,
                'hyperscale.storage.dm.volume.create',
                pool_name=POOL_NAME,
                volume_guid=util.get_guid_with_curly_brackets(
                    volume['id']),
                display_name=util.get_guid_with_curly_brackets(
                    volume['id']),
                volume_raw_size=volume['size'],
                vm_id=util.get_guid_with_curly_brackets(
                    six.text_type(instance_id)),
                is_reflection_source=0,
                dn_reflection_factor=1,
                reflection_src_ip=self.datanode_ip,
                user_id=util.get_guid_with_curly_brackets(
                    volume['user_id']),
                project_id=util.get_guid_with_curly_brackets(
                    volume['project_id']),
                volume_qos=1)
            # Failure handling TBD.
            ret = True
            LOG.debug("Create volume sent to reflection target data node")

        except (exception.VolumeNotFound,
                exception.UnableToProcessHyperScaleCmdOutput,
                exception.ErrorInSendingMsg):
            LOG.error("Exception in creating replica", exc_info = True)
            metadata_update['Secondary_datanode_key'] = 'NA'
            metadata_update['Secondary_datanode_ip'] = 'NA'
            metadata_update['DN_Resiliency'] = 'degraded'
            ret = False
        return ret, reflection_target_ip, metadata_update

    def _get_volume_details_for_create_volume(self,
                                              reflection_target_ip,
                                              volume,
                                              metadata):

        instance_id = self._get_volume_metadata_value(metadata,
                                                      'InstanceId')
        volume_details = {}
        volume_details['pool_name'] = POOL_NAME
        volume_details['volume_guid'] = (
            util.get_guid_with_curly_brackets(volume['id']))
        volume_details['display_name'] = (
            util.get_guid_with_curly_brackets(volume['id']))
        volume_details['volume_raw_size'] = volume['size']
        volume_details['vm_id'] = util.get_guid_with_curly_brackets(
            six.text_type(instance_id))
        volume_details['user_id'] = util.get_guid_with_curly_brackets(
            volume['user_id'])
        volume_details['project_id'] = (
            util.get_guid_with_curly_brackets(volume['project_id']))
        volume_details['volume_qos'] = 1
        volume_details['dn_reflection_factor'] = 0

        if reflection_target_ip is not None:
            volume_details['is_reflection_source'] = 1
            volume_details['dn_reflection_factor'] = 1
            volume_details['reflection_target_ip'] = reflection_target_ip

        return volume_details

    def _get_volume_metadata(self, volume):
        volume_metadata = {}
        if 'volume_metadata' in volume:
            for metadata in volume['volume_metadata']:
                volume_metadata[metadata['key']] = metadata['value']
        return volume_metadata

    def _get_volume_metadata_value(self, metadata, metadata_key):
        metadata_value = None
        if metadata:
            metadata_value = metadata.get(metadata_key)

        LOG.debug("Volume metadata key %(m_key)s, value %(m_val)s",
                  {"m_key": metadata_key, "m_val": metadata_value})
        return metadata_value

    @utils.trace_method
    def create_volume(self, volume):
        """Creates a hyperscale volume."""

        model_update = {}
        metadata_update = {}
        reflection_target_ip = None
        LOG.debug("Create volume")
        try:
            volume_metadata = self._get_volume_metadata(volume)

            # 1. Check how many replicas needs to be created.
            replicas = self._get_replicas(volume, volume_metadata)
            if replicas > 1:
                # 2. Create replica on peer datanode.
                LOG.debug("Create volume message sent to peer data node")
                ret, reflection_target_ip, metadata_update = (
                    self._create_replica(volume, volume_metadata))
                if ret is False:
                    metadata_update['DN_Resiliency'] = 'degraded'
                    # Do not fail volume creation, just create one replica.
                    reflection_target_ip = None

            # 3. Get volume details based on reflection factor
            #    for volume
            volume_details = self._get_volume_details_for_create_volume(
                reflection_target_ip, volume, volume_metadata)

            # 4. Send create volume to data node with volume details
            util.message_data_plane(
                self.dn_routing_key,
                'hyperscale.storage.dm.volume.create',
                **volume_details)
            LOG.debug("Create volume message sent to data node")

            volume_metadata['Primary_datanode_ip'] = self.datanode_ip
            volume_metadata['current_dn_owner'] = self.dn_routing_key
            volume_metadata['current_dn_ip'] = self.datanode_ip
            volume_metadata['hs_image_id'] = util.get_hyperscale_image_id()
            volume_metadata.update(metadata_update)

            volume['provider_location'] = PROVIDER_LOCATION
            model_update = {'provider_location': volume['provider_location'],
                            'metadata': volume_metadata}

        except (exception.UnableToProcessHyperScaleCmdOutput,
                exception.ErrorInSendingMsg):
            with excutils.save_and_reraise_exception():
                LOG.exception('Unable to create hyperscale volume')

        return model_update

    @utils.trace_method
    def delete_volume(self, volume):
        """Deletes a volume."""

        LOG.debug("Delete volume with id %s", volume['id'])
        # 1. Check for provider location
        if not volume['provider_location']:
            LOG.warning('Volume %s does not have provider_location specified',
                        volume['name'])
            raise exception.VolumeMetadataNotFound(
                volume_id=volume['id'],
                metadata_key='provider_location')

        # 2. Message data plane for volume deletion
        message_body = {'display_name': volume['name']}

        # if Secondary_datanode_key is present,
        # delete the replica from secondary datanode.
        rt_key = None

        # Get metadata for volume
        metadata = self._get_volume_metadata(volume)

        rt_key = self._get_volume_metadata_value(metadata,
                                                 'Secondary_datanode_key')
        rt_dn_ip = self._get_volume_metadata_value(metadata,
                                                   'Secondary_datanode_ip')
        current_dn_ip = self._get_volume_metadata_value(metadata,
                                                        'current_dn_ip')
        if current_dn_ip is not None and rt_dn_ip == current_dn_ip:
            rt_key = None

        # Send Delete Volume to Data Node
        try:
            if rt_key is not None:
                util.message_data_plane(
                    rt_key,
                    'hyperscale.storage.dm.volume.delete',
                    **message_body)

            util.message_data_plane(
                self.dn_routing_key,
                'hyperscale.storage.dm.volume.delete',
                **message_body)

        except (exception.UnableToProcessHyperScaleCmdOutput,
                exception.ErrorInSendingMsg):
            LOG.error('Exception while deleting volume', exc_info=True)
            raise exception.VolumeIsBusy(volume_name=volume['name'])

    @utils.trace_method
    def create_snapshot(self, snapshot):
        """Create a snapshot."""

        LOG.debug("Create Snapshot %s", snapshot['volume_id'])
        workflow_id = None
        last_in_eds_seq = None
        model_update = {}
        rt_key = None

        # Get metadata for volume
        snapshot_volume = snapshot.get('volume')
        metadata = snapshot_volume['metadata']
        rt_key = self._get_volume_metadata_value(metadata,
                                                 'current_dn_owner')
        if rt_key is None:
            rt_key = self.dn_routing_key

        # Check for episodic based on metadata key
        workflow_snap = 0

        meta = snapshot.get('metadata')
        LOG.debug('Snapshot metatadata %s', meta)
        if 'SNAPSHOT-COOKIE' in meta.keys():
            snapsize = meta['SIZE']

            # Call DataNode for episodic snapshots
            LOG.debug('Calling Data Node for episodic snapshots')
            message_body = {}
            message_body['snapshot_id'] = (
                util.get_guid_with_curly_brackets(snapshot['id']))
            message_body['volume_guid'] = (
                util.get_guid_with_curly_brackets(
                    snapshot['volume_id']))
            message_body['snapshot_cookie'] = meta['SNAPSHOT-COOKIE']

            try:
                # send message to data node
                util.message_data_plane(
                    rt_key,
                    'hyperscale.storage.dm.volume.snapshot.update',
                    **message_body)

                # Update size via cinder api
                if snapsize is not None:
                    model_update['volume_size'] = snapsize.value

                # Set the episodic type metatdata for filtering purpose
                meta['TYPE'] = TYPE_EPISODIC_SNAP
                meta['status'] = 'available'
                meta['datanode_ip'] = self.datanode_ip

            except (exception.VolumeNotFound,
                    exception.UnableToExecuteHyperScaleCmd,
                    exception.UnableToProcessHyperScaleCmdOutput):
                with excutils.save_and_reraise_exception():
                    LOG.exception('Exception in create snapshot')

            model_update['metadata'] = meta
            return model_update

        else:
            out_meta = util.episodic_snap(meta)
            if out_meta.get('update'):
                meta['TYPE'] = out_meta.get('TYPE')
                meta['status'] = out_meta.get('status')
                meta['datanode_ip'] = self.datanode_ip
                model_update['metadata'] = meta
                return model_update

        if 'workflow_id' in meta.keys():
            workflow_snap = 1
            workflow_id = meta['workflow_id']

        if 'monitor_snap' in meta.keys():
            if int(meta['monitor_snap']) == constants.SNAP_RESTORE_RF:
                last_in_eds_seq = 0
            else:
                last_in_eds_seq = 1

        # If code falls through here then it mean its user initiated snapshots
        try:
            # Get metadata for volume
            vsa_routing_key = None
            snapshot_volume = snapshot.get('volume')
            metadata = snapshot_volume['metadata']
            LOG.debug('Calling Compute Node for user initiated snapshots')
            vsa_ip = self._get_volume_metadata_value(metadata,
                                                     'acting_vdisk_owner')
            if vsa_ip is None:
                vsa_ip = self._get_volume_metadata_value(metadata, 'vsa_ip')

            LOG.debug("Create snap on compute vsa %s", vsa_ip)
            if vsa_ip:
                vsa_routing_key = vsa_ip.replace('.', '')

            message_body = {}
            # Set the parent volume id
            message_body['vdisk_id_str'] = (
                util.get_guid_with_curly_brackets(
                    snapshot['volume_id']))
            # Set the snapshot details
            message_body['snapshot_id_str'] = (
                util.get_guid_with_curly_brackets(snapshot['id']))
            message_body['snapshot_name'] = snapshot['name']

            if workflow_snap == 1:
                message_body['workflow_snapshot'] = 1
            else:
                message_body['user_initiated'] = 1

            if last_in_eds_seq is not None:
                message_body['last_in_eds_seq'] = last_in_eds_seq

            # send message to compute node
            util.message_compute_plane(
                vsa_routing_key,
                'hyperscale.storage.nfs.volume.snapshot.create',
                **message_body)

            # Set the snapshot type to either workflow or user initiated
            # snapshot in metatdata for filtering purpose
            if workflow_snap:
                LOG.debug('__help request for WORKFLOW snapshot')
                meta['TYPE'] = TYPE_WORKFLOW_SNAP
                meta['status'] = 'creating'
                meta['datanode_ip'] = self.datanode_ip
            else:
                LOG.debug('__help request for MANUAL snapshot')
                meta['TYPE'] = TYPE_USER_SNAP
                meta['status'] = 'creating'
                meta['datanode_ip'] = self.datanode_ip

            if workflow_id is not None:
                message_body = {}
                message_body['workflow_id'] = workflow_id
                message_body['skip_upto_sentinel'] = (
                    'hyperscale.vdisk.failback.snapmark_sentinel')

                # send message to controller node
                util.message_controller(
                    constants.HS_CONTROLLER_EXCH,
                    'hyperscale.controller.execute.workflow',
                    **message_body)

        except (exception.VolumeNotFound,
                exception.UnableToExecuteHyperScaleCmd,
                exception.UnableToProcessHyperScaleCmdOutput):
            with excutils.save_and_reraise_exception():
                LOG.exception('Exception in create snapshot')

        model_update['metadata'] = meta
        return model_update

    @utils.trace_method
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""

        meta = snapshot.get('metadata')
        if 'force' in meta.keys():
            LOG.debug("Found force flag for snapshot metadata."
                      " Not sending call to datanode ")
            LOG.debug('snapshot metadata %s', meta)
            return

        if 'is_busy' in meta.keys():
            LOG.warning("Snapshot %s is being used, skipping delete",
                        snapshot['id'])
            raise exception.SnapshotIsBusy(snapshot_name=snapshot['id'])
        else:
            LOG.warning("Snapshot %s is being deleted,"
                        " is_busy key not present", snapshot['id'])

        message_body = {}
        message_body['volume_guid'] = (
            util.get_guid_with_curly_brackets(snapshot['volume_id']))
        message_body['snapshot_id'] = (
            util.get_guid_with_curly_brackets(snapshot['id']))

        # HyperScale snapshots whether Episodic or User initiated, all resides
        # in the data plane.
        # Hence delete snapshot operation will go to datanode
        rt_key = None

        # Get metadata for volume
        snapshot_volume = snapshot.get('volume')
        metadata = snapshot_volume['metadata']
        rt_key = self._get_volume_metadata_value(metadata,
                                                 'current_dn_owner')
        if rt_key is None:
            rt_key = self.dn_routing_key

        try:
            # send message to data node
            util.message_data_plane(
                rt_key,
                'hyperscale.storage.dm.version.delete',
                **message_body)

        except (exception.UnableToExecuteHyperScaleCmd,
                exception.UnableToProcessHyperScaleCmdOutput):
            with excutils.save_and_reraise_exception():
                LOG.exception('Exception in delete snapshot')

    @utils.trace_method
    def create_volume_from_snapshot(self, volume, snapshot):
        """Create volume from snapshot."""

        LOG.debug("Create volume from snapshot")
        model_update = {}
        try:
            LOG.debug("Clone new volume %(t_id)s from snapshot with id"
                      " %(s_id)s", {"t_id": volume['id'],
                                    "s_id": volume['snapshot_id']})
            # 1. Make a call to DN
            # Check if current_dn_owner is set.
            # Route the snapshot creation request to current_dn_owner

            rt_key = None

            # Get metadata for volume
            snap_vol = snapshot['volume']
            metadata = snap_vol['metadata']
            rt_key = self._get_volume_metadata_value(metadata,
                                                     'current_dn_owner')
            if rt_key is None:
                rt_key = self.dn_routing_key

            util.message_data_plane(
                rt_key,
                'hyperscale.storage.dm.volume.clone.create',
                pool_name=POOL_NAME,
                display_name=util.get_guid_with_curly_brackets(
                    volume['id']),
                version_name=util.get_guid_with_curly_brackets(
                    volume['snapshot_id']),
                volume_raw_size=volume['size'],
                volume_qos=1,
                parent_volume_guid=util.get_guid_with_curly_brackets(
                    snapshot['volume_id']),
                user_id=util.get_guid_with_curly_brackets(
                    volume['user_id']),
                project_id=util.get_guid_with_curly_brackets(
                    volume['project_id']),
                volume_guid=util.get_guid_with_curly_brackets(
                    volume['id']))

            LOG.debug("Volume created successfully on data node")

            # Get metadata for volume
            volume_metadata = self._get_volume_metadata(volume)
            parent_cur_dn = self._get_volume_metadata_value(metadata,
                                                            'current_dn_ip')

            metadata_update = {}
            metadata_update['snapshot_id'] = snapshot['id']
            metadata_update['parent_volume_guid'] = (
                util.get_guid_with_curly_brackets(
                    snapshot['volume_id']))
            metadata_update['Primary_datanode_ip'] = parent_cur_dn
            metadata_update['current_dn_owner'] = rt_key
            metadata_update['current_dn_ip'] = parent_cur_dn

            # 2. Choose a potential replica here.
            # The actual decision to have potential replica is made in NOVA.
            rt_key, rt_dn_ip = self._select_rt(volume,
                                               volume_metadata,
                                               only_select=True)

            if rt_key and rt_dn_ip:
                metadata_update['Potential_secondary_key'] = rt_key
                metadata_update['Potential_secondary_ip'] = rt_dn_ip

        except (exception.UnableToExecuteHyperScaleCmd,
                exception.UnableToProcessHyperScaleCmdOutput):
            with excutils.save_and_reraise_exception():
                LOG.exception('Exception in creating volume from snapshot')
        except exception.InvalidMetadataType:
            with excutils.save_and_reraise_exception():
                LOG.exception('Exception updating metadata in create'
                              ' volume from snapshot')

        volume_metadata.update(metadata_update)

        volume['provider_location'] = PROVIDER_LOCATION
        model_update = {'provider_location': volume['provider_location'],
                        'metadata': volume_metadata}

        return model_update

    @utils.trace_method
    def get_volume_stats(self, refresh=False):
        """Get volume status."""

        # If 'refresh' is True, run update the stats first.

        LOG.debug("Get volume status")

        self._stats = self._fetch_volume_status()
        new_total = self._stats['total_capacity_gb']
        new_free = self._stats['free_capacity_gb']

        if self.old_total != new_total or self.old_free != new_free:
            self.old_total = new_total
            self.old_free = new_free

            message_body = {'hostname': self.datanode_hostname,
                            'is_admin': 1,
                            'total': new_total,
                            'free': new_free}
            try:
                cmd_out, cmd_error = util.message_controller(
                    constants.HS_CONTROLLER_EXCH,
                    'hyperscale.controller.set.datanode.storage.stats',
                    **message_body)
                LOG.debug("Response Message from Controller: %s",
                          cmd_out)

            except (exception.UnableToExecuteHyperScaleCmd,
                    exception.UnableToProcessHyperScaleCmdOutput):
                with excutils.save_and_reraise_exception():
                    LOG.exception('Exception during fetch stats')

        return self._stats

    @utils.trace_method
    def extend_volume(self, volume, size_gb):
        """Extend volume."""

        LOG.debug("Extend volume")
        try:
            message_body = {}
            message_body['volume_guid'] = (
                util.get_guid_with_curly_brackets(volume['id']))
            message_body['new_size'] = size_gb

            # Send Extend Volume message to Data Node
            util.message_data_plane(
                self.dn_routing_key,
                'hyperscale.storage.dm.volume.extend',
                **message_body)

        except (exception.UnableToProcessHyperScaleCmdOutput,
                exception.ErrorInSendingMsg):
            msg = _('Exception in extend volume %s') % volume['name']
            LOG.exception(msg)
            raise exception.VolumeDriverException(message=msg)

    def _fetch_volume_status(self):
        """Retrieve Volume Stats from Datanode."""

        LOG.debug("Request Volume Stats from Datanode")

        data = {}
        data["volume_backend_name"] = 'Veritas_HyperScale'
        data["vendor_name"] = 'Veritas Technologies LLC'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = 'nfs'
        data['total_capacity_gb'] = 0.0
        data['free_capacity_gb'] = 0.0
        data['reserved_percentage'] = self.configuration.reserved_percentage
        data['QoS_support'] = False

        try:
            message_body = {}
            # send message to data node
            cmd_out, cmd_error = util.message_data_plane(
                self.dn_routing_key,
                'hyperscale.storage.dm.discover.stats',
                **message_body)

            LOG.debug("Response Message from Datanode: %s", cmd_out)
            payload = cmd_out.get('payload')
            if 'stats' in payload.keys():
                if 'total_capacity' in payload.get(
                        'stats')[0].keys():
                    total_capacity = payload.get(
                        'stats')[0]['total_capacity']

                if 'free_capacity' in payload.get(
                        'stats')[0].keys():
                    free_capacity = payload.get(
                        'stats')[0]['free_capacity']

                if total_capacity is not None:
                    data['total_capacity_gb'] = float(total_capacity)
                    data['free_capacity_gb'] = float(free_capacity)

        except (exception.UnableToExecuteHyperScaleCmd,
                exception.UnableToProcessHyperScaleCmdOutput):
            with excutils.save_and_reraise_exception():
                LOG.exception('Exception during fetch stats')

        return data

    @utils.trace_method
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        data = {'export': volume['provider_location'],
                'name': volume['name']}
        return {
            'driver_volume_type': 'veritas_hyperscale',
            'data': data
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        pass

    def ensure_export(self, ctx, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    def create_export(self, ctx, volume, connector):

        # Exports the volume. Can optionally return a Dictionary of changes
        # to the volume object to be persisted."""
        pass

    def remove_export(self, ctx, volume):
        """Removes an export for a logical volume."""
        pass

    @utils.trace_method
    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""

        LOG.debug("copy_image_to_volume volume: %(vol)s "
                  "image service: %(service)s image id: %(id)s.",
                  {'vol': volume,
                   'service': six.text_type(image_service),
                   'id': six.text_type(image_id)})

        path = util.get_image_path(image_id)
        try:
            # Skip image creation if file already exists
            if not os.path.isfile(path):
                image_utils.fetch_to_raw(context,
                                         image_service,
                                         image_id,
                                         path,
                                         BLOCK_SIZE,
                                         size=volume['size'])
            metadata = self._get_volume_metadata(volume)
            hs_img_id = self._get_volume_metadata_value(metadata,
                                                        'hs_image_id')
            util.update_image(path, volume['id'], hs_img_id)

        except (exception.UnableToExecuteHyperScaleCmd,
                exception.UnableToProcessHyperScaleCmdOutput):
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to copy_image_to_volume')

    @utils.trace_method
    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""

        LOG.debug("copy_volume_to_image volume: %(vol)s"
                  " image service:%(service)s image meta: %(meta)s.",
                  {'vol': volume,
                   'service': six.text_type(image_service),
                   'meta': six.text_type(image_meta)})

        try:
            metadata = self._get_volume_metadata(volume)
            hs_img_id = self._get_volume_metadata_value(metadata,
                                                        'hs_image_id')
            path = util.get_image_path(hs_img_id, 'volume')
            image_utils.upload_volume(context,
                                      image_service,
                                      image_meta,
                                      path)

        except (exception.UnableToExecuteHyperScaleCmd,
                exception.UnableToProcessHyperScaleCmdOutput):
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to copy_volume_to_image')
