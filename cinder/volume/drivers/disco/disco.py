#    Copyright (c) 2015 Industrial Technology Research Institute.
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

"""DISCO Block device Driver."""

import os
import time

from os_brick.initiator import connector
from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import units
import six
from suds import client

from cinder import context
from cinder.db.sqlalchemy import api
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder import utils
from cinder.volume import driver


LOG = logging.getLogger(__name__)

disco_opts = [
    cfg.IPOpt('disco_client',
              default='127.0.0.1',
              help='The IP of DMS client socket server'),
    cfg.PortOpt('disco_client_port',
                default='9898',
                help='The port to connect DMS client socket server'),
    cfg.StrOpt('disco_wsdl_path',
               default='/etc/cinder/DISCOService.wsdl',
               help='Path to the wsdl file '
                    'to communicate with DISCO request manager'),
    cfg.StrOpt('volume_name_prefix',
               default='openstack-',
               help='Prefix before volume name to differentiate '
                    'DISCO volume created through openstack '
                    'and the other ones'),
    cfg.IntOpt('snapshot_check_timeout',
               default=3600,
               help='How long we check whether a snapshot '
                    'is finished before we give up'),
    cfg.IntOpt('restore_check_timeout',
               default=3600,
               help='How long we check whether a restore '
                    'is finished before we give up'),
    cfg.IntOpt('clone_check_timeout',
               default=3600,
               help='How long we check whether a clone '
                    'is finished before we give up'),
    cfg.IntOpt('retry_interval',
               default=1,
               help='How long we wait before retrying to '
                    'get an item detail')
]

DISCO_CODE_MAPPING = {
    'request.success': 1,
    'request.ongoing': 2,
    'request.failure': 3,
}

CONF = cfg.CONF
CONF.register_opts(disco_opts)


# Driver to communicate with DISCO storage solution
@interface.volumedriver
class DiscoDriver(driver.VolumeDriver):
    """Execute commands related to DISCO Volumes."""

    VERSION = "1.0"
    CI_WIKI_NAME = "ITRI_DISCO_CI"

    def __init__(self, *args, **kwargs):
        """Init Disco driver : get configuration, create client."""
        super(DiscoDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(disco_opts)
        self.ctxt = context.get_admin_context()

        self.connector = connector.InitiatorConnector.factory(
            self._get_connector_identifier(), utils.get_root_helper(),
            device_scan_attempts=(
                self.configuration.num_volume_device_scan_tries)
        )

        self.connection_conf = {}
        self.connection_conf['server_ip'] = self.configuration.disco_client
        self.connection_conf['server_port'] = (
            self.configuration.disco_client_port)

        self.connection_properties = {}
        self.connection_properties['name'] = None
        self.connection_properties['disco_id'] = None
        self.connection_properties['conf'] = self.connection_conf

    def do_setup(self, context):
        """Create client for DISCO request manager."""
        LOG.debug("Enter in DiscoDriver do_setup.")
        path = ''.join(['file:', self.configuration.disco_wsdl_path])
        self.client = client.Client(path, cache=None)

    def check_for_setup_error(self):
        """Make sure we have the pre-requisites."""
        LOG.debug("Enter in DiscoDriver check_for_setup_error.")
        path = self.configuration.disco_wsdl_path
        if not os.path.exists(path):
            msg = _("Could not find DISCO wsdl file.")
            raise exception.VolumeBackendAPIException(data=msg)

    def _get_connector_identifier(self):
        """Return connector identifier, put here to mock it in unit tests."""
        return connector.DISCO

    def create_volume(self, volume):
        """Create a disco volume."""
        name = self.configuration.volume_name_prefix, volume["id"]
        vol_name = ''.join(name)
        vol_size = volume['size'] * units.Ki
        LOG.debug("Create volume : [name] %(vname)s - [size] %(vsize)s.",
                  {'vname': vol_name, 'vsize': six.text_type(vol_size)})
        reply = self.client.service.volumeCreate(vol_name, vol_size)
        status = reply['status']
        result = reply['result']
        LOG.debug("Create volume : [status] %(stat)s - [result] %(res)s.",
                  {'stat': six.text_type(status), 'res': result})

        if status != 0:
            msg = (_("Error while creating volume "
                     "[status] %(stat)s - [result] %(res)s.") %
                   {'stat': six.text_type(status), 'res': result})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        LOG.debug("Volume %s created.", volume["name"])
        return {'provider_location': result}

    def delete_volume(self, volume):
        """Delete a logical volume."""
        disco_vol_id = volume['provider_location']
        LOG.debug("Delete disco volume : %s.", disco_vol_id)
        reply = self.client.service.volumeDelete(disco_vol_id)
        status = reply['status']
        result = reply['result']

        LOG.debug("Delete volume [status] %(stat)s - [result] %(res)s.",
                  {'stat': six.text_type(status), 'res': result})

        if status != 0:
            msg = (_("Error while deleting volume "
                     "[status] %(stat)s - [result] %(res)s.") %
                   {'stat': six.text_type(status), 'res': result})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug("Volume %s deleted.", volume['name'])

    def create_snapshot(self, snapshot):
        """Create a disco snapshot."""
        volume = api.volume_get(self.ctxt, snapshot['volume_id'])
        description = snapshot['display_description']
        vol_id = volume['provider_location']
        LOG.debug("Create snapshot of volume : %(id)s, "
                  "description : %(desc)s.",
                  {'id': vol_id, 'desc': description})

        # Trigger an asynchronous local snapshot
        reply = self.client.service.snapshotCreate(vol_id,
                                                   -1, -1,
                                                   description)
        status = reply['status']
        result = reply['result']
        LOG.debug("Create snapshot : [status] %(stat)s - [result] %(res)s.",
                  {'stat': six.text_type(status), 'res': result})

        if status != 0:
            msg = (_("Error while creating snapshot "
                     "[status] %(stat)s - [result] %(res)s.") %
                   {'stat': six.text_type(status), 'res': result})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Monitor the status until it becomes either success or fail
        params = {'snapshot_id': int(result)}
        start_time = int(time.time())

        timer = loopingcall.FixedIntervalLoopingCall(
            self._retry_get_detail,
            start_time,
            self.configuration.snapshot_check_timeout,
            'snapshot_detail',
            params)
        reply = timer.start(interval=self.configuration.retry_interval).wait()

        snapshot['provider_location'] = result
        LOG.debug("snapshot taken successfully on volume : %(volume)s.",
                  {'volume': volume['name']})
        return {'provider_location': result}

    def delete_snapshot(self, snapshot):
        """Delete a disco snapshot."""
        LOG.debug("Enter in delete a disco snapshot.")

        snap_id = snapshot['provider_location']
        LOG.debug("[start] Delete snapshot : %s.", snap_id)
        reply = self.client.service.snapshotDelete(snap_id)
        status = reply['status']
        result = reply['result']
        LOG.debug("[End] Delete snapshot : "
                  "[status] %(stat)s - [result] %(res)s.",
                  {'stat': six.text_type(status), 'res': result})

        if status != 0:
            msg = (_("Error while deleting snapshot "
                     "[status] %(stat)s - [result] %(res)s") %
                   {'stat': six.text_type(status), 'res': result})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot."""
        name = self.configuration.volume_name_prefix, volume['id']
        snap_id = snapshot['provider_location']
        vol_name = ''.join(name)
        # Trigger an asynchronous restore operation
        LOG.debug("[start] Create volume from snapshot : "
                  "%(snap_id)s - name : %(vol_name)s.",
                  {'snap_id': snap_id, 'vol_name': vol_name})
        reply = self.client.service.restoreFromSnapshot(snap_id, vol_name)
        status = reply['status']
        result = reply['result']
        LOG.debug("Restore  volume from snapshot "
                  "[status] %(stat)s - [result] %(res)s.",
                  {'stat': six.text_type(status), 'res': result})

        if status != 0:
            msg = (_("Error[%(stat)s - %(res)s] while restoring snapshot "
                     "[%(snap_id)s] into volume [%(vol)s].") %
                   {'stat': six.text_type(status), 'res': result,
                    'snap_id': snap_id, 'vol': vol_name})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Monitor the status until it becomes
        # either success, fail or timeout
        params = {'restore_id': int(result)}
        start_time = int(time.time())

        timer = loopingcall.FixedIntervalLoopingCall(
            self._retry_get_detail,
            start_time,
            self.configuration.restore_check_timeout,
            'restore_detail',
            params)
        reply = timer.start(interval=self.configuration.retry_interval).wait()

        reply = self.client.service.volumeDetailByName(vol_name)
        status = reply['status']
        new_vol_id = reply['volumeInfoResult']['volumeId']

        if status != 0:
            msg = (_("Error[status] %(stat)s - [result] %(res)s] "
                     "while getting volume id.") %
                   {'stat': six.text_type(status), 'res': result})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        LOG.debug("Restore done [status] %(stat)s - "
                  "[volume id] %(vol_id)s.",
                  {'stat': status, 'vol_id': six.text_type(new_vol_id)})
        return {'provider_location': new_vol_id}

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume."""
        LOG.debug("Creating clone of volume: %s.", src_vref['id'])
        name = self.configuration.volume_name_prefix, volume['id']
        vol_name = ''.join(name)
        vol_size = volume['size'] * units.Ki
        src_vol_id = src_vref['provider_location']
        LOG.debug("Clone volume : "
                  "[name] %(name)s - [source] %(source)s - [size] %(size)s.",
                  {'name': vol_name,
                   'source': src_vol_id,
                   'size': six.text_type(vol_size)})
        reply = self.client.service.volumeClone(src_vol_id, vol_name)
        status = reply['status']
        result = reply['result']
        LOG.debug("Clone volume : [status] %(stat)s - [result] %(res)s.",
                  {'stat': six.text_type(status), 'res': result})

        if status != 0:
            msg = (_("Error while creating volume "
                     "[status] %(stat)s - [result] %(res)s.") %
                   {'stat': six.text_type(status), 'res': result})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Monitor the status until it becomes
        # either success, fail or timeout
        params = {'clone_id': int(result),
                  'vol_name': vol_name}
        start_time = int(time.time())

        timer = loopingcall.FixedIntervalLoopingCall(
            self._retry_get_detail,
            start_time,
            self.configuration.clone_check_timeout,
            'clone_detail',
            params)
        reply = timer.start(interval=self.configuration.retry_interval).wait()

        reply = self.client.service.volumeDetailByName(vol_name)
        status = reply['status']
        new_vol_id = reply['volumeInfoResult']['volumeId']

        if status != 0:
            msg = (_("Error[%(stat)s - %(res)s] "
                     "while getting volume id."),
                   {'stat': six.text_type(status), 'res': result})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug("clone done : "
                  "[status] %(stat)s - [volume id] %(vol_id)s.",
                  {'stat': status, 'vol_id': six.text_type(new_vol_id)})
        return {'provider_location': new_vol_id}

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        LOG.debug("Enter in copy image to volume for disco.")

        try:
            device_info = self._attach_volume(volume)
            image_utils.fetch_to_raw(context,
                                     image_service,
                                     image_id,
                                     device_info['path'],
                                     self.configuration.volume_dd_blocksize,
                                     size=volume['size'])
        finally:
            self._detach_volume(volume)

    def _attach_volume(self, volume):
        """Call the connector.connect_volume()."""
        connection_properties = self._get_connection_properties(volume)
        device_info = self.connector.connect_volume(connection_properties)
        return device_info

    def _detach_volume(self, volume):
        """Call the connector.disconnect_volume()."""
        connection_properties = self._get_connection_properties(volume)
        self.connector.disconnect_volume(connection_properties, volume)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy a  volume to a new image."""
        LOG.debug("Enter in copy image to volume for disco.")
        try:
            device_info = self._attach_volume(volume)
            image_utils.upload_volume(context,
                                      image_service,
                                      image_meta,
                                      device_info['path'])
        finally:
            self._detach_volume(volume)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume's size."""
        vol_id = volume['provider_location']
        LOG.debug("Extends volume : %(id)s, new size : %(size)s.",
                  {'id': vol_id, 'size': new_size})
        new_size_mb = new_size * units.Ki
        reply = self.client.service.volumeExtend(vol_id, new_size_mb)
        status = reply['status']
        result = reply['result']

        if status != 0:
            msg = (_("Error while extending volume "
                     "[status] %(stat)s - [result] %(res)s."),
                   {'stat': six.text_type(status), 'res': result})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        LOG.debug("Volume extended : [id] %(vid)s - "
                  "[status] %(stat)s - [result] %(res)s.",
                  {'vid': vol_id,
                   'stat': six.text_type(status),
                   'res': result})

    def initialize_connection(self, volume, connector):
        """Function called before attaching a volume."""
        LOG.debug("Enter in initialize connection with disco, "
                  "connector is %s.", connector)
        data = {
            'driver_volume_type': 'disco',
            'data': self._get_connection_properties(volume)
        }
        LOG.debug("Initialize connection [data]: %s.", data)
        return data

    def _get_connection_properties(self, volume):
        """Return a dictionnary with the connection properties."""
        connection_properties = dict(self.connection_properties)
        connection_properties['name'] = volume['name']
        connection_properties['disco_id'] = volume['provider_location']
        return connection_properties

    def terminate_connection(self, volume, connector, **kwargs):
        """Function called after attaching a volume."""
        LOG.debug("Enter in terminate connection with disco.")

    def _update_volume_stats(self):
        LOG.debug("Enter in update volume stats.")
        stats = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        stats['volume_backend_name'] = backend_name or 'disco'
        stats['storage_protocol'] = 'disco'
        stats['driver_version'] = self.VERSION
        stats['reserved_percentage'] = 0
        stats['vendor_name'] = 'ITRI'
        stats['QoS_support'] = False

        try:
            reply = self.client.service.systemInformationList()
            status = reply['status']

            if status != 0:
                msg = (_("Error while getting "
                         "disco information [%s].") %
                       six.text_type(status))
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            info_list = reply['propertyListResult']['PropertyInfoList']
            for info in info_list:
                if info['name'] == 'freeCapacityGB':
                    stats['free_capacity_gb'] = float(info['value'])
                elif info['name'] == 'totalCapacityGB':
                    stats['total_capacity_gb'] = float(info['value'])
        except Exception:
            stats['total_capacity_gb'] = 'unknown'
            stats['free_capacity_gb'] = 'unknown'

        self._stats = stats

    def get_volume_stats(self, refresh=False):
        """Get backend information."""
        if refresh:
            self._update_volume_stats()
        return self._stats

    def local_path(self, volume):
        """Return the path to the DISCO volume."""
        return "/dev/dms%s" % volume['name']

    def ensure_export(self, context, volume):
        """Ensure an export."""
        pass

    def create_export(self, context, volume, connector):
        """Export the volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a logical volume."""
        pass

    def is_timeout(self, start_time, timeout):
        """Check whether we reach the timeout."""
        current_time = int(time.time())
        if current_time - start_time > timeout:
            return True
        else:
            return False

    def _retry_get_detail(self, start_time, timeout, operation, params):
        """Keep trying to query an item detail unless we reach the timeout."""
        reply = self._call_api(operation, params)
        status = reply['status']

        msg = (_("Error while getting %(op)s details, "
                 "returned code: %(status)s.") %
               {'op': operation, 'status': six.text_type(status)})

        if status != 0:
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        item_status = self._get_item_status(operation, reply)
        if item_status == DISCO_CODE_MAPPING['request.failure']:
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        elif item_status == DISCO_CODE_MAPPING['request.success']:
            raise loopingcall.LoopingCallDone(retvalue=reply)
        elif self.is_timeout(start_time, timeout):
            msg = (_("Timeout while calling %s ") % operation)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _call_api(self, operation, params):
        """Make the call to the SOAP api."""
        if operation == 'snapshot_detail':
            return self.client.service.snapshotDetail(params['snapshot_id'])
        if operation == 'restore_detail':
            return self.client.service.restoreDetail(params['restore_id'])
        if operation == 'clone_detail':
            return self.client.service.cloneDetail(params['clone_id'],
                                                   params['vol_name'])
        else:
            msg = (_("Unknown operation %s."), operation)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _get_item_status(self, operation, reply):
        """Make the call to the SOAP api."""
        if reply is None:
            msg = (_("Call returned a None object"))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        elif operation == 'snapshot_detail':
            return reply['snapshotInfoResult']['status']
        elif operation == 'restore_detail':
            return reply['restoreInfoResult']['status']
        elif operation == 'clone_detail':
            return int(reply['result'])
        else:
            msg = (_("Unknown operation "
                     "%s."), operation)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
