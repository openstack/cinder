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

import errno

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder import interface
import cinder.volume.driver
from cinder.volume.drivers.prophetstor import dplcommon

LOG = logging.getLogger(__name__)


@interface.volumedriver
class DPLISCSIDriver(dplcommon.DPLCOMMONDriver,
                     cinder.volume.driver.ISCSIDriver):
    def __init__(self, *args, **kwargs):
        super(DPLISCSIDriver, self).__init__(*args, **kwargs)

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        properties = {}
        properties['target_lun'] = None
        properties['target_discovered'] = True
        properties['target_portal'] = ''
        properties['target_iqn'] = None
        properties['volume_id'] = volume['id']

        dpl_server = self.configuration.san_ip
        dpl_iscsi_port = self.configuration.iscsi_port
        ret, output = self.dpl.assign_vdev(self._conver_uuid2hex(
            volume['id']), connector['initiator'].lower(), volume['id'],
            '%s:%d' % (dpl_server, dpl_iscsi_port), 0)

        if ret == errno.EAGAIN:
            ret, event_uuid = self._get_event_uuid(output)
            if len(event_uuid):
                ret = 0
                status = self._wait_event(
                    self.dpl.get_vdev_status, self._conver_uuid2hex(
                        volume['id']), event_uuid)
                if status['state'] == 'error':
                    ret = errno.EFAULT
                    msg = _('Flexvisor failed to assign volume %(id)s: '
                            '%(status)s.') % {'id': volume['id'],
                                              'status': status}
                    raise exception.VolumeBackendAPIException(data=msg)
            else:
                ret = errno.EFAULT
                msg = _('Flexvisor failed to assign volume %(id)s due to '
                        'unable to query status by event '
                        'id.') % {'id': volume['id']}
                raise exception.VolumeBackendAPIException(data=msg)
        elif ret != 0:
            msg = _('Flexvisor assign volume failed.:%(id)s:'
                    '%(status)s.') % {'id': volume['id'], 'status': ret}
            raise exception.VolumeBackendAPIException(data=msg)

        if ret == 0:
            ret, output = self.dpl.get_vdev(
                self._conver_uuid2hex(volume['id']))
        if ret == 0:
            for tgInfo in output['exports']['Network/iSCSI']:
                if tgInfo['permissions'] and \
                        isinstance(tgInfo['permissions'][0], dict):
                    for assign in tgInfo['permissions']:
                        if connector['initiator'].lower() in assign.keys():
                            for tgportal in tgInfo.get('portals', {}):
                                properties['target_portal'] = tgportal
                                break
                            properties['target_lun'] = \
                                int(assign[connector['initiator'].lower()])
                            break

                    if properties['target_portal'] != '':
                        properties['target_iqn'] = tgInfo['target_identifier']
                        break
                else:
                    if connector['initiator'].lower() in tgInfo['permissions']:
                        for tgportal in tgInfo.get('portals', {}):
                            properties['target_portal'] = tgportal
                            break

                    if properties['target_portal'] != '':
                        properties['target_lun'] = \
                            int(tgInfo['logical_unit_number'])
                        properties['target_iqn'] = \
                            tgInfo['target_identifier']
                        break

        if not (ret == 0 or properties['target_portal']):
            msg = _('Flexvisor failed to assign volume %(volume)s '
                    'iqn %(iqn)s.') % {'volume': volume['id'],
                                       'iqn': connector['initiator']}
            raise exception.VolumeBackendAPIException(data=msg)

        return {'driver_volume_type': 'iscsi', 'data': properties}

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        ret, output = self.dpl.unassign_vdev(
            self._conver_uuid2hex(volume['id']),
            connector['initiator'])

        if ret == errno.EAGAIN:
            ret, event_uuid = self._get_event_uuid(output)
            if ret == 0:
                status = self._wait_event(
                    self.dpl.get_vdev_status, volume['id'], event_uuid)
                if status['state'] == 'error':
                    ret = errno.EFAULT
                    msg = _('Flexvisor failed to unassign volume %(id)s:'
                            ' %(status)s.') % {'id': volume['id'],
                                               'status': status}
                    raise exception.VolumeBackendAPIException(data=msg)
            else:
                msg = _('Flexvisor failed to unassign volume (get event) '
                        '%(id)s.') % {'id': volume['id']}
                raise exception.VolumeBackendAPIException(data=msg)
        elif ret == errno.ENODATA:
            LOG.info('Flexvisor already unassigned volume %(id)s.',
                     {'id': volume['id']})
        elif ret != 0:
            msg = _('Flexvisor failed to unassign volume:%(id)s:'
                    '%(status)s.') % {'id': volume['id'], 'status': ret}
            raise exception.VolumeBackendAPIException(data=msg)

    def get_volume_stats(self, refresh=False):
        if refresh:
            try:
                data = super(DPLISCSIDriver, self).get_volume_stats(refresh)
                if data:
                    data['storage_protocol'] = 'iSCSI'
                    backend_name = \
                        self.configuration.safe_get('volume_backend_name')
                    data['volume_backend_name'] = \
                        (backend_name or 'DPLISCSIDriver')
                    self._stats = data
            except Exception as exc:
                LOG.warning('Cannot get volume status %(exc)s.', {'exc': exc})
        return self._stats
