# Copyright (c) 2014 ProphetStor, Inc.
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
Implementation of the class of ProphetStor DPL storage adapter of Federator.
"""

import base64
import errno
import httplib
import json
import random
import time

import six

from cinder import exception
from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import loopingcall
from cinder.openstack.common import units
from cinder.volume import driver
from cinder.volume.drivers.prophetstor import options
from cinder.volume.drivers.san import san

LOG = logging.getLogger(__name__)

CONNECTION_RETRY = 10
DISCOVER_SERVER_TYPE = 'dpl'
DPL_BLOCKSTOR = '/dpl_blockstor'
DPL_SYSTEM = '/dpl_system'

DPL_VER_V1 = 'v1'
DPL_OBJ_POOL = 'dpl_pool'
DPL_OBJ_DISK = 'dpl_disk'
DPL_OBJ_VOLUME = 'dpl_volume'
DPL_OBJ_VOLUMEGROUP = 'dpl_volgroup'
DPL_OBJ_SNAPSHOT = 'cdmi_snapshots'
DPL_OBJ_EXPORT = 'dpl_export'

DPL_OBJ_REPLICATION = 'cdmi_replication'
DPL_OBJ_TARGET = 'dpl_target'
DPL_OBJ_SYSTEM = 'dpl_system'
DPL_OBJ_SNS = 'sns_table'


class DPLCommand(object):
    """DPL command interface."""

    def __init__(self, ip, port, username, password):
        self.ip = ip
        self.port = port
        self.username = username
        self.password = password

    def send_cmd(self, method, url, params, expected_status):
        """Send command to DPL."""
        connection = None
        retcode = 0
        response = {}
        data = {}
        header = {'Content-Type': 'application/cdmi-container',
                  'Accept': 'application/cdmi-container',
                  'x-cdmi-specification-version': '1.0.2'}
        # base64 encode the username and password
        auth = base64.encodestring('%s:%s'
                                   % (self.username,
                                      self.password)).replace('\n', '')
        header['Authorization'] = 'Basic %s' % auth

        if not params:
            payload = None
        else:
            try:
                payload = json.dumps(params, ensure_ascii=False)
                payload.encode('utf-8')
            except Exception:
                LOG.error(_('JSON encode params error: %s.'),
                          six.text_type(params))
                retcode = errno.EINVAL
        for i in range(CONNECTION_RETRY):
            try:
                connection = httplib.HTTPSConnection(self.ip,
                                                     self.port,
                                                     timeout=60)
                if connection:
                    retcode = 0
                    break
            except IOError as ioerr:
                LOG.error(_('Connect to Flexvisor error: %s.'),
                          six.text_type(ioerr))
                retcode = errno.ENOTCONN
            except Exception as e:
                LOG.error(_('Connect to Flexvisor failed: %s.'),
                          six.text_type(e))
                retcode = errno.EFAULT

        retry = CONNECTION_RETRY
        while (connection and retry):
            try:
                connection.request(method, url, payload, header)
            except httplib.CannotSendRequest as e:
                connection.close()
                time.sleep(1)
                connection = httplib.HTTPSConnection(self.ip,
                                                     self.port,
                                                     timeout=60)
                retry -= 1
                if connection:
                    if retry == 0:
                        retcode = errno.ENOTCONN
                    else:
                        retcode = 0
                else:
                    retcode = errno.ENOTCONN
                continue
            except Exception as e:
                LOG.error(_('Failed to send request: %s.'),
                          six.text_type(e))
                retcode = errno.EFAULT
                break

            if retcode == 0:
                try:
                    response = connection.getresponse()
                    if response.status == httplib.SERVICE_UNAVAILABLE:
                        LOG.error(_('The Flexvisor service is unavailable.'))
                        time.sleep(1)
                        retry -= 1
                        retcode = errno.ENOPROTOOPT
                        continue
                    else:
                        retcode = 0
                        break
                except httplib.ResponseNotReady as e:
                    time.sleep(1)
                    retry -= 1
                    retcode = errno.EFAULT
                    continue
                except Exception as e:
                    LOG.error(_('Failed to get response: %s.'),
                              six.text_type(e.message))
                    retcode = errno.EFAULT
                    break

        if retcode == 0 and response.status in expected_status and\
                response.status == httplib.NOT_FOUND:
            retcode = errno.ENODATA
        elif retcode == 0 and response.status not in expected_status:
            LOG.error(_('%(method)s %(url)s unexpected response status: '
                        '%(response)s (expects: %(expects)s).')
                      % {'method': method,
                         'url': url,
                         'response': httplib.responses[response.status],
                         'expects': expected_status})
            if response.status == httplib.UNAUTHORIZED:
                raise exception.NotAuthorized
                retcode = errno.EACCES
            else:
                retcode = errno.EIO
        elif retcode == 0 and response.status is httplib.NOT_FOUND:
            retcode = errno.ENODATA
        elif retcode == 0 and response.status is httplib.ACCEPTED:
            retcode = errno.EAGAIN
            try:
                data = response.read()
                data = json.loads(data)
            except (TypeError, ValueError) as e:
                LOG.error(_('Call to json.loads() raised an exception: %s.'),
                          six.text_type(e))
                retcode = errno.ENOEXEC
            except Exception as e:
                LOG.error(_('Read response raised an exception: %s.'),
                          six.text_type(e))
                retcode = errno.ENOEXEC
        elif retcode == 0 and \
                response.status in [httplib.OK, httplib.CREATED] and \
                httplib.NO_CONTENT not in expected_status:
            try:
                data = response.read()
                data = json.loads(data)
            except (TypeError, ValueError) as e:
                LOG.error(_('Call to json.loads() raised an exception: %s.'),
                          six.text_type(e))
                retcode = errno.ENOEXEC
            except Exception as e:
                LOG.error(_('Read response raised an exception: %s.'),
                          six.text_type(e))
                retcode = errno.ENOEXEC

        if connection:
            connection.close()
        return retcode, data


class DPLVolume(object):

    def __init__(self, dplServer, dplPort, dplUser, dplPassword):
        self.objCmd = DPLCommand(dplServer, dplPort, dplUser, dplPassword)

    def _execute(self, method, url, params, expected_status):
        if self.objCmd:
            return self.objCmd.send_cmd(method, url, params, expected_status)
        else:
            return -1, None

    def _gen_snapshot_url(self, vdevid, snapshotid):
        snapshot_url = '/%s/%s/%s' % (vdevid, DPL_OBJ_SNAPSHOT, snapshotid)
        return snapshot_url

    def get_server_info(self):
        method = 'GET'
        url = '/%s/%s/' % (DPL_VER_V1, DPL_OBJ_SYSTEM)
        return self._execute(method, url, None, [httplib.OK, httplib.ACCEPTED])

    def create_vdev(self, volumeID, volumeName, volumeDesc, poolID, volumeSize,
                    fthinprovision=True, maximum_snapshot=1024,
                    snapshot_quota=None):
        method = 'PUT'
        metadata = {}
        params = {}
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_VOLUME, volumeID)

        if volumeName is None or volumeName == '':
            metadata['display_name'] = volumeID
        else:
            metadata['display_name'] = volumeName
        metadata['display_description'] = volumeDesc
        metadata['pool_uuid'] = poolID
        metadata['total_capacity'] = volumeSize
        metadata['maximum_snapshot'] = 1024
        if snapshot_quota is not None:
            metadata['snapshot_quota'] = int(snapshot_quota)
        metadata['properties'] = dict(thin_provision=fthinprovision)
        params['metadata'] = metadata
        return self._execute(method,
                             url, params,
                             [httplib.OK, httplib.ACCEPTED, httplib.CREATED])

    def extend_vdev(self, volumeID, volumeName, volumeDesc, volumeSize,
                    maximum_snapshot=1024, snapshot_quota=None):
        method = 'PUT'
        metadata = {}
        params = {}
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_VOLUME, volumeID)

        if volumeName is None or volumeName == '':
            metadata['display_name'] = volumeID
        else:
            metadata['display_name'] = volumeName
        metadata['display_description'] = volumeDesc
        metadata['total_capacity'] = int(volumeSize)
        metadata['maximum_snapshot'] = maximum_snapshot
        if snapshot_quota is not None:
            metadata['snapshot_quota'] = snapshot_quota
        params['metadata'] = metadata
        return self._execute(method,
                             url, params,
                             [httplib.OK, httplib.ACCEPTED, httplib.CREATED])

    def delete_vdev(self, volumeID, force=True):
        method = 'DELETE'
        metadata = {}
        params = {}
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_VOLUME, volumeID)

        metadata['force'] = force
        params['metadata'] = metadata
        return self._execute(method,
                             url, params,
                             [httplib.OK, httplib.ACCEPTED, httplib.NOT_FOUND,
                              httplib.NO_CONTENT])

    def create_vdev_from_snapshot(self, vdevID, vdevDisplayName, vdevDesc,
                                  snapshotID, poolID, fthinprovision=True,
                                  maximum_snapshot=1024, snapshot_quota=None):
        method = 'PUT'
        metadata = {}
        params = {}
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_VOLUME, vdevID)
        metadata['snapshot_operation'] = 'copy'
        if vdevDisplayName is None or vdevDisplayName == "":
            metadata['display_name'] = vdevID
        else:
            metadata['display_name'] = vdevDisplayName
        metadata['display_description'] = vdevDesc
        metadata['pool_uuid'] = poolID
        metadata['properties'] = {}
        metadata['maximum_snapshot'] = maximum_snapshot
        if snapshot_quota:
            metadata['snapshot_quota'] = snapshot_quota
        metadata['properties'] = dict(thin_provision=fthinprovision)

        params['metadata'] = metadata
        params['copy'] = self._gen_snapshot_url(vdevID, snapshotID)
        return self._execute(method,
                             url, params,
                             [httplib.OK, httplib.ACCEPTED, httplib.CREATED])

    def spawn_vdev_from_snapshot(self, new_vol_id, src_vol_id,
                                 vol_display_name, description, snap_id):
        method = 'PUT'
        params = {}
        metadata = {}
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_VOLUME, new_vol_id)

        metadata['snapshot_operation'] = 'spawn'
        if vol_display_name is None or vol_display_name == '':
            metadata['display_name'] = new_vol_id
        else:
            metadata['display_name'] = vol_display_name
        metadata['display_description'] = description
        params['metadata'] = metadata
        params['copy'] = self._gen_snapshot_url(src_vol_id, snap_id)

        return self._execute(method, url, params,
                             [httplib.OK, httplib.ACCEPTED, httplib.CREATED])

    def get_pool(self, poolid):
        method = 'GET'
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_POOL, poolid)

        return self._execute(method, url, None, [httplib.OK, httplib.ACCEPTED])

    def clone_vdev(self, SourceVolumeID, NewVolumeID, poolID, volumeName,
                   volumeDesc, volumeSize, fthinprovision=True,
                   maximum_snapshot=1024, snapshot_quota=None):
        method = 'PUT'
        params = {}
        metadata = {}
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_VOLUME, NewVolumeID)
        metadata["snapshot_operation"] = "clone"
        if volumeName is None or volumeName == '':
            metadata["display_name"] = NewVolumeID
        else:
            metadata["display_name"] = volumeName
        metadata["display_description"] = volumeDesc
        metadata["pool_uuid"] = poolID
        metadata["total_capacity"] = volumeSize
        metadata["maximum_snapshot"] = maximum_snapshot
        if snapshot_quota:
            metadata["snapshot_quota"] = snapshot_quota
        metadata["properties"] = dict(thin_provision=fthinprovision)
        params["metadata"] = metadata
        params["copy"] = SourceVolumeID

        return self._execute(method,
                             url, params,
                             [httplib.OK, httplib.CREATED, httplib.ACCEPTED])

    def create_vdev_snapshot(self, volumeID, snapshotID, snapshotName='',
                             snapshotDes=''):
        method = 'PUT'
        metadata = {}
        params = {}
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_VOLUME, volumeID)

        if snapshotName is None or snapshotName == '':
            metadata['display_name'] = snapshotID
        else:
            metadata['display_name'] = snapshotName
        metadata['display_description'] = snapshotDes

        params['metadata'] = metadata
        params['snapshot'] = snapshotID

        return self._execute(method,
                             url, params,
                             [httplib.OK, httplib.CREATED, httplib.ACCEPTED])

    def get_vdev(self, vdevid):
        method = 'GET'
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_VOLUME, vdevid)

        return self._execute(method,
                             url, None,
                             [httplib.OK, httplib.ACCEPTED, httplib.NOT_FOUND])

    def get_vdev_status(self, vdevid, eventid):
        method = 'GET'
        url = '/%s/%s/%s/?event_uuid=%s' \
              % (DPL_VER_V1, DPL_OBJ_VOLUME, vdevid, eventid)

        return self._execute(method,
                             url, None,
                             [httplib.OK, httplib.NOT_FOUND])

    def get_pool_status(self, poolid, eventid):
        method = 'GET'
        url = '/%s/%s/%s/?event_uuid=%s' \
              % (DPL_VER_V1, DPL_OBJ_POOL, poolid, eventid)

        return self._execute(method,
                             url, None,
                             [httplib.OK, httplib.NOT_FOUND])

    def assign_vdev(self, vdevid, iqn, lunname, portal, lunid=0):
        method = 'PUT'
        metadata = {}
        exports = {}
        params = {}
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_VOLUME, vdevid)

        metadata['export_operation'] = 'assign'
        exports['Network/iSCSI'] = {}
        target_info = {}
        target_info['logical_unit_number'] = 0
        target_info['logical_unit_name'] = lunname
        permissions = []
        portals = []
        portals.append(portal)
        permissions.append(iqn)
        target_info['permissions'] = permissions
        target_info['portals'] = portals
        exports['Network/iSCSI'] = target_info

        params['metadata'] = metadata
        params['exports'] = exports

        return self._execute(method,
                             url, params,
                             [httplib.OK, httplib.ACCEPTED, httplib.CREATED])

    def assign_vdev_fc(self, vdevid, targetwwpn, initiatorwwpn, lunname,
                       lunid=-1):
        method = 'PUT'
        metadata = {}
        exports = {}
        params = {}
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_VOLUME, vdevid)
        metadata['export_operation'] = 'assign'
        exports['Network/FC'] = {}
        target_info = {}
        target_info['target_identifier'] = targetwwpn
        target_info['logical_unit_number'] = lunid
        target_info['logical_unit_name'] = lunname
        target_info['permissions'] = initiatorwwpn
        exports['Network/FC'] = target_info

        params['metadata'] = metadata
        params['exports'] = exports

        return self._execute(method,
                             url, params,
                             [httplib.OK, httplib.ACCEPTED, httplib.CREATED])

    def unassign_vdev(self, vdevid, initiatorIqn, targetIqn=''):
        method = 'PUT'
        metadata = {}
        exports = {}
        params = {}
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_VOLUME, vdevid)

        metadata['export_operation'] = 'unassign'
        params['metadata'] = metadata

        exports['Network/iSCSI'] = {}
        exports['Network/iSCSI']['target_identifier'] = targetIqn
        permissions = []
        permissions.append(initiatorIqn)
        exports['Network/iSCSI']['permissions'] = permissions

        params['exports'] = exports

        return self._execute(method,
                             url, params,
                             [httplib.OK, httplib.ACCEPTED,
                              httplib.NO_CONTENT, httplib.NOT_FOUND])

    def unassign_vdev_fc(self, vdevid, targetwwpn, initiatorwwpns):
        method = 'PUT'
        metadata = {}
        exports = {}
        params = {}
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_VOLUME, vdevid)

        metadata['export_operation'] = 'unassign'
        params['metadata'] = metadata

        exports['Network/FC'] = {}
        exports['Network/FC']['target_identifier'] = targetwwpn
        permissions = initiatorwwpns
        exports['Network/FC']['permissions'] = permissions

        params['exports'] = exports

        return self._execute(method,
                             url, params,
                             [httplib.OK, httplib.ACCEPTED,
                              httplib.NO_CONTENT, httplib.NOT_FOUND])

    def delete_vdev_snapshot(self, volumeID, snapshotID):
        method = 'DELETE'
        url = '/%s/%s/%s/%s/%s/' \
              % (DPL_VER_V1, DPL_OBJ_VOLUME, volumeID,
                 DPL_OBJ_SNAPSHOT, snapshotID)

        return self._execute(method,
                             url, None,
                             [httplib.OK, httplib.ACCEPTED, httplib.NO_CONTENT,
                              httplib.NOT_FOUND])

    def rollback_vdev(self, vdevid, snapshotid):
        method = 'PUT'
        params = {}
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_VOLUME, vdevid)

        params['copy'] = self._gen_snapshot_url(vdevid, snapshotid)

        return self._execute(method,
                             url, params,
                             [httplib.OK, httplib.ACCEPTED])

    def list_vdev_snapshots(self, vdevid):
        method = 'GET'
        url = '/%s/%s/%s/%s/' \
              % (DPL_VER_V1, DPL_OBJ_VOLUME, vdevid, DPL_OBJ_SNAPSHOT)

        return self._execute(method,
                             url, None,
                             [httplib.OK])

    def create_target(self, targetID, protocol, displayName, targetAddress,
                      description=''):
        method = 'PUT'
        params = {}
        url = '/%s/%s/%s/' \
            % (DPL_VER_V1, DPL_OBJ_EXPORT, targetID)
        params['metadata'] = {}
        metadata = params['metadata']
        metadata['type'] = 'target'
        metadata['protocol'] = protocol
        if displayName is None or displayName == '':
            metadata['display_name'] = targetID
        else:
            metadata['display_name'] = displayName
        metadata['display_description'] = description
        metadata['address'] = targetAddress
        return self._execute(method, url, params, [httplib.OK])

    def get_target(self, targetID):
        method = 'GET'
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_EXPORT, targetID)
        return self._execute(method, url, None, [httplib.OK])

    def delete_target(self, targetID):
        method = 'DELETE'
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_EXPORT, targetID)
        return self._execute(method,
                             url, None,
                             [httplib.OK, httplib.ACCEPTED, httplib.NOT_FOUND])

    def get_target_list(self, type='target'):
        # type = target/initiator
        method = 'GET'
        if type is None:
            url = '/%s/%s/' % (DPL_VER_V1, DPL_OBJ_EXPORT)
        else:
            url = '/%s/%s/?type=%s' % (DPL_VER_V1, DPL_OBJ_EXPORT, type)
        return self._execute(method, url, None, [httplib.OK])

    def get_sns_table(self, wwpn):
        method = 'PUT'
        params = {}
        url = '/%s/%s/%s/' % (DPL_VER_V1, DPL_OBJ_EXPORT, DPL_OBJ_SNS)
        params['metadata'] = {}
        params['metadata']['protocol'] = 'fc'
        params['metadata']['address'] = str(wwpn)
        return self._execute(method, url, params, [httplib.OK])


class DPLCOMMONDriver(driver.VolumeDriver):
    """class of dpl storage adapter."""
    VERSION = '2.0'

    def __init__(self, *args, **kwargs):
        super(DPLCOMMONDriver, self).__init__(*args, **kwargs)
        if self.configuration:
            self.configuration.append_config_values(options.DPL_OPTS)
            self.configuration.append_config_values(san.san_opts)

        self.dpl = DPLVolume(self.configuration.san_ip,
                             self.configuration.dpl_port,
                             self.configuration.san_login,
                             self.configuration.san_password)
        self._stats = {}

    def _convert_size_GB(self, size):
        s = round(float(size) / units.Gi, 2)
        if s > 0:
            return s
        else:
            return 0

    def _conver_uuid2hex(self, strID):
        if strID:
            return strID.replace('-', '')
        else:
            return None

    def _get_event_uuid(self, output):
        ret = 0
        event_uuid = ""

        if type(output) is dict and \
                output.get("metadata") and output["metadata"]:
            if output["metadata"].get("event_uuid") and  \
                    output["metadata"]["event_uuid"]:
                event_uuid = output["metadata"]["event_uuid"]
            else:
                ret = errno.EINVAL
        else:
            ret = errno.EINVAL
        return ret, event_uuid

    def _wait_event(self, callFun, objuuid, eventid=None):
        nRetry = 30
        fExit = False
        status = {}
        status['state'] = 'error'
        status['output'] = {}
        while nRetry:
            try:
                if eventid:
                    ret, output = callFun(
                        self._conver_uuid2hex(objuuid),
                        self._conver_uuid2hex(eventid))
                else:
                    ret, output = callFun(self._conver_uuid2hex(objuuid))

                if ret == 0:
                    if output['completionStatus'] == 'Complete':
                        fExit = True
                        status['state'] = 'available'
                        status['output'] = output
                    elif output['completionStatus'] == 'Error':
                        fExit = True
                        status['state'] = 'error'
                        raise loopingcall.LoopingCallDone(retvalue=False)
                    else:
                        nsleep = random.randint(0, 10)
                        value = round(float(nsleep) / 10, 2)
                        time.sleep(value)
                elif ret == errno.ENODATA:
                    status['state'] = 'deleted'
                    fExit = True
                else:
                    nRetry -= 1
                    time.sleep(3)
                    continue

            except Exception as e:
                msg = _('Flexvisor failed to get event %(volume)s'
                        '(%(status)s).') % {'volume': eventid,
                                            'status': six.text_type(e)}
                LOG.error(msg)
                raise loopingcall.LoopingCallDone(retvalue=False)
                status['state'] = 'error'
                fExit = True

            if fExit is True:
                break

        return status

    def create_export(self, context, volume):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def create_volume(self, volume):
        """Create a volume."""
        pool = self.configuration.dpl_pool
        ret, output = self.dpl.create_vdev(
            self._conver_uuid2hex(volume['id']),
            volume.get('display_name', ''),
            volume.get('display_description', ''),
            pool,
            int(volume['size']) * units.Gi,
            self.configuration.san_thin_provision)
        if ret == errno.EAGAIN:
            ret, event_uuid = self._get_event_uuid(output)
            if ret == 0:
                status = self._wait_event(self.dpl.get_vdev_status,
                                          volume['id'],
                                          event_uuid)
                if status['state'] != 'available':
                    msg = _('Flexvisor failed to create volume %(volume)s: '
                            '%(status)s.') % {'volume': volume['id'],
                                              'status': ret}
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
            else:
                msg = _('Flexvisor failed to create volume (get event) '
                        '%s.') % (volume['id'])
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(
                    data=msg)
        elif ret != 0:
            msg = _('Flexvisor create volume failed.:%(volumeid)s:'
                    '%(status)s.') % {'volumeid': volume['id'], 'status': ret}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(
                data=msg)
        else:
            msg = _('Flexvisor succeed to create volume '
                    '%(id)s.') % {'id': volume['id']}
            LOG.info(msg)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        pool = self.configuration.dpl_pool
        ret, output = self.dpl.create_vdev_from_snapshot(
            self._conver_uuid2hex(volume['id']),
            volume.get('display_name', ''),
            volume.get('display_description', ''),
            self._conver_uuid2hex(snapshot['id']),
            pool,
            self.configuration.san_thin_provision)
        if ret == errno.EAGAIN:
            ret, event_uuid = self._get_event_uuid(output)
            if ret == 0:
                status = self._wait_event(self.dpl.get_vdev_status,
                                          volume['id'],
                                          event_uuid)
                if status['state'] != 'available':
                    msg = _('Flexvisor failed to create volume from snapshot '
                            '%(id)s:%(status)s.') % {'id': snapshot['id'],
                                                     'status': ret}
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(
                        data=msg)
            else:
                msg = _('Flexvisor failed to create volume from snapshot '
                        '(failed to get event) '
                        '%(id)s.') % {'id': snapshot['id']}
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        elif ret != 0:
            msg = _('Flexvisor failed to create volume from snapshot '
                    '%(id)s: %(status)s.') % {'id': snapshot['id'],
                                              'status': ret}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(
                data=msg)
        else:
            msg = _('Flexvisor succeed to create volume %(id)s '
                    'from snapshot.') % {'id': volume['id']}
            LOG.info(msg)

    def spawn_volume_from_snapshot(self, volume, snapshot):
        """Spawn a REFERENCED volume from a snapshot."""
        ret, output = self.dpl.spawn_vdev_from_snapshot(
            self._conver_uuid2hex(volume['id']),
            self._conver_uuid2hex(snapshot['volume_id']),
            volume.get('display_name', ''),
            volume.get('display_description', ''),
            self._conver_uuid2hex(snapshot['id']))

        if ret == errno.EAGAIN:
            # its an async process
            ret, event_uuid = self._get_event_uuid(output)
            if ret == 0:
                status = self._wait_event(self.dpl.get_vdev_status,
                                          volume['id'], event_uuid)
                if status['state'] != 'available':
                    msg = _('Flexvisor failed to spawn volume from snapshot '
                            '%(id)s:%(status)s.') % {'id': snapshot['id'],
                                                     'status': ret}
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
            else:
                msg = _('Flexvisor failed to spawn volume from snapshot '
                        '(failed to get event) '
                        '%(id)s.') % {'id': snapshot['id']}
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        elif ret != 0:
            msg = _('Flexvisor failed to create volume from snapshot '
                    '%(id)s: %(status)s.') % {'id': snapshot['id'],
                                              'status': ret}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(
                data=msg)
        else:
            msg = _('Flexvisor succeed to create volume %(id)s '
                    'from snapshot.') % {'id': volume['id']}
            LOG.info(msg)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        pool = self.configuration.dpl_pool
        ret, output = self.dpl.clone_vdev(
            self._conver_uuid2hex(src_vref['id']),
            self._conver_uuid2hex(volume['id']),
            pool,
            volume.get('display_name', ''),
            volume.get('display_description', ''),
            int(volume['size']) * units.Gi,
            self.configuration.san_thin_provision)
        if ret == errno.EAGAIN:
            ret, event_uuid = self._get_event_uuid(output)
            if ret == 0:
                status = self._wait_event(self.dpl.get_vdev_status,
                                          volume['id'],
                                          event_uuid)
                if status['state'] != 'available':
                    msg = _('Flexvisor failed to clone volume %(id)s: '
                            '%(status)s.') % {'id': src_vref['id'],
                                              'status': ret}
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
            else:
                msg = _('Flexvisor failed to clone volume (failed to get event'
                        ') %(id)s.') % {'id': src_vref['id']}
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(
                    data=msg)
        elif ret != 0:
            msg = _('Flexvisor failed to clone volume %(id)s: '
                    '%(status)s.') % {'id': src_vref['id'], 'status': ret}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(
                data=msg)
        else:
            msg = _('Flexvisor succeed to clone '
                    'volume %(id)s.') % {'id': volume['id']}
            LOG.info(msg)

    def delete_volume(self, volume):
        """Deletes a volume."""
        ret, output = self.dpl.delete_vdev(self._conver_uuid2hex(volume['id']))
        if ret == errno.EAGAIN:
            status = self._wait_event(self.dpl.get_vdev, volume['id'])
            if status['state'] == 'error':
                msg = _('Flexvisor failed deleting volume %(id)s: '
                        '%(status)s.') % {'id': volume['id'], 'status': ret}
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        elif ret == errno.ENODATA:
            ret = 0
            msg = _('Flexvisor volume %(id)s not '
                    'existed.') % {'id': volume['id']}
            LOG.info(msg)
        elif ret != 0:
            msg = _('Flexvisor failed to delete volume %(id)s: '
                    '%(status)s.') % {'id': volume['id'], 'status': ret}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(
                data=msg)

    def extend_volume(self, volume, new_size):
        ret, output = self.dpl.extend_vdev(self._conver_uuid2hex(volume['id']),
                                           volume.get('display_name', ''),
                                           volume.get('display_description',
                                                      ''),
                                           new_size * units.Gi)
        if ret == errno.EAGAIN:
            ret, event_uuid = self._get_event_uuid(output)
            if ret == 0:
                status = self._wait_event(self.dpl.get_vdev_status,
                                          volume['id'],
                                          event_uuid)
                if status['state'] != 'available':
                    msg = _('Flexvisor failed to extend volume '
                            '%(id)s:%(status)s.') % {'id': volume,
                                                     'status': ret}
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(
                        data=msg)
            else:
                msg = _('Flexvisor failed to extend volume '
                        '(failed to get event) '
                        '%(id)s.') % {'id': volume['id']}
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        elif ret != 0:
            msg = _('Flexvisor failed to extend volume '
                    '%(id)s: %(status)s.') % {'id': volume['id'],
                                              'status': ret}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(
                data=msg)
        else:
            msg = _('Flexvisor succeed to extend volume'
                    ' %(id)s.') % {'id': volume['id']}
            LOG.info(msg)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        ret, output = self.dpl.create_vdev_snapshot(
            self._conver_uuid2hex(snapshot['volume_id']),
            self._conver_uuid2hex(snapshot['id']),
            snapshot.get('display_name', ''),
            snapshot.get('display_description', ''))

        if ret == errno.EAGAIN:
            ret, event_uuid = self._get_event_uuid(output)
            if ret == 0:
                status = self._wait_event(self.dpl.get_vdev_status,
                                          snapshot['volume_id'],
                                          event_uuid)
                if status['state'] != 'available':
                    msg = _('Flexvisor failed to create snapshot for volume '
                            '%(id)s: %(status)s.') % \
                        {'id': snapshot['volume_id'], 'status': ret}
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
            else:
                msg = _('Flexvisor failed to create snapshot for volume '
                        '(failed to get event) %(id)s.') % \
                    {'id': snapshot['volume_id']}
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        elif ret != 0:
            msg = _('Flexvisor failed to create snapshot for volume %(id)s: '
                    '%(status)s.') % {'id': snapshot['volume_id'],
                                      'status': ret}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        ret, output = self.dpl.delete_vdev_snapshot(
            self._conver_uuid2hex(snapshot['volume_id']),
            self._conver_uuid2hex(snapshot['id']))
        if ret == errno.EAGAIN:
            ret, event_uuid = self._get_event_uuid(output)
            if ret == 0:
                status = self._wait_event(self.dpl.get_vdev_status,
                                          snapshot['volume_id'],
                                          event_uuid)
                if status['state'] != 'available':
                    msg = _('Flexvisor failed to delete snapshot %(id)s: '
                            '%(status)s.') % {'id': snapshot['id'],
                                              'status': ret}
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
            else:
                msg = _('Flexvisor failed to delete snapshot (failed to '
                        'get event) %(id)s.') % {'id': snapshot['id']}
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        elif ret == errno.ENODATA:
            msg = _('Flexvisor snapshot %(id)s not existed.') % \
                {'id': snapshot['id']}
            LOG.info(msg)
        elif ret != 0:
            msg = _('Flexvisor failed to delete snapshot %(id)s: '
                    '%(status)s.') % {'id': snapshot['id'], 'status': ret}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        else:
            msg = _('Flexvisor succeed to delete '
                    'snapshot %(id)s.') % {'id': snapshot['id']}
            LOG.info(msg)

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self, refresh=False):
        """Return the current state of the volume service. If 'refresh' is
           True, run the update first.
        """
        data = {}
        totalSize = 0
        availableSize = 0

        ret, output = self._get_pool_info(self.configuration.dpl_pool)
        if ret == 0:
            totalSize = int(output['metadata']['total_capacity'])
            availableSize = int(output['metadata']['available_capacity'])
        else:
            totalSize = 0
            availableSize = 0

        data['volume_backend_name'] = \
            self.configuration.safe_get('volume_backend_name')

        location_info = '%(driver)s:%(host)s:%(volume)s' % {
            'driver': self.__class__.__name__,
            'host': self.configuration.san_ip,
            'volume': self.configuration.dpl_pool
        }

        try:
            ret, output = self.dpl.get_server_info()
            if ret == 0:
                data['vendor_name'] = output['metadata']['vendor']
                data['driver_version'] = output['metadata']['version']
                data['storage_protocol'] = 'iSCSI'
                data['total_capacity_gb'] = self._convert_size_GB(totalSize)
                data['free_capacity_gb'] = self._convert_size_GB(availableSize)
                data['reserved_percentage'] = 0
                data['QoS_support'] = False
                data['location_info'] = location_info
                self._stats = data
        except Exception as e:
            msg = _('Failed to get server info due to '
                    '%(state)s.') % {'state': six.text_type(e)}
            LOG.error(msg)
        return self._stats

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        self.context = context
        LOG.info(_('Activate Flexvisor cinder volume driver.'))

    def check_for_setup_error(self):
        """Check DPL can connect properly."""
        pass

    def _get_pool_info(self, poolid):
        """Query pool information."""
        ret, output = self.dpl.get_pool(poolid)
        if ret == errno.EAGAIN:
            ret, event_uuid = self._get_event_uuid(output)
            if ret == 0:
                status = self._wait_event(self.dpl.get_pool_status, poolid,
                                          event_uuid)
                if status['state'] != 'available':
                    msg = _('Flexvisor failed to get pool info %(id)s: '
                            '%(status)s.') % {'id': poolid, 'status': ret}
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                else:
                    ret = 0
                    output = status.get('output', {})
            else:
                LOG.error(_('Flexvisor failed to get pool info '
                          '(failed to get event)%s.') % (poolid))
                raise exception.VolumeBackendAPIException(
                    data="failed to get event")
        elif ret != 0:
            msg = _('Flexvisor failed to get pool info %(id)s: '
                    '%(status)s.') % {'id': poolid, 'status': ret}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        else:
            msg = 'Flexvisor succeed to get pool info.'
            LOG.debug(msg)
        return ret, output
