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
from cinder.i18n import _, _LE, _LI
from cinder.volume import driver
from cinder.volume.drivers.prophetstor import dplcommon
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


class DPLFCDriver(dplcommon.DPLCOMMONDriver,
                  driver.FibreChannelDriver):
    def __init__(self, *args, **kwargs):
        super(DPLFCDriver, self).__init__(*args, **kwargs)

    def _get_fc_channel(self):
        """Get FibreChannel info.

        :returns: fcInfos[uuid]
                  fcInfo[uuid]['display_name']
                  fcInfo[uuid]['display_description']
                  fcInfo[uuid]['hardware_address']
                  fcInfo[uuid]['type']
                  fcInfo[uuid]['speed']
                  fcInfo[uuid]['state']
        """
        output = None
        fcInfos = {}
        try:
            retCode, output = self.dpl.get_server_info()
            if retCode == 0 and output:
                fcUuids = output.get('metadata',
                                     {}).get('storage_adapter', {}).keys()
                for fcUuid in fcUuids:
                    fcInfo = output.get('metadata',
                                        {}).get('storage_adapter',
                                                {}).get(fcUuid)
                    if fcInfo['type'] == 'fc':
                        fcInfos[fcUuid] = fcInfo
        except Exception as e:
            LOG.error(_LE("Failed to get fiber channel info from storage "
                          "due to %(stat)s"), {'stat': e})
        return fcInfos

    def _get_targets(self):
        """Get targets.

        :returns: targetInfos[uuid] = targetInfo
                  targetInfo['targetUuid']
                  targetInfo['targetName']
                  targetInfo['targetAddr']
        """
        output = None
        targetInfos = {}
        try:
            retCode, output = self.dpl.get_target_list('target')
            if retCode == 0 and output:
                for targetInfo in output.get('children', []):
                    targetI = {}
                    targetI['targetUuid'] = targetInfo[0]
                    targetI['targetName'] = targetInfo[1]
                    targetI['targetAddr'] = targetInfo[2]
                    targetInfos[str(targetInfo[0])] = targetI
        except Exception as e:
            targetInfos = {}
            LOG.error(_LE("Failed to get fiber channel target from "
                          "storage server due to %(stat)s"),
                      {'stat': e})
        return targetInfos

    def _get_targetwpns(self, volumeid, initiatorWwpns):
        lstargetWwpns = []
        try:
            ret, output = self.dpl.get_vdev(volumeid)
            if ret == 0 and output:
                exports = output.get('exports', {})
                fc_infos = exports.get('Network/FC', {})
                for fc_info in fc_infos:
                    for p in fc_info.get('permissions', []):
                        if p.get(initiatorWwpns, None):
                            targetWwpns = fc_info.get('target_identifier', '')
                            lstargetWwpns.append(targetWwpns)
        except Exception as e:
            LOG.error(_LE("Failed to get target wwpns from storage due "
                          "to %(stat)s"), {'stat': e})
            lstargetWwpns = []
        return lstargetWwpns

    def _is_initiator_wwpn_active(self, targetWwpn, initiatorWwpn):
        fActive = False
        output = None
        try:
            retCode, output = self.dpl.get_sns_table(targetWwpn)
            if retCode == 0 and output:
                for fdwwpn, fcport in output.get('metadata',
                                                 {}).get('sns_table',
                                                         []):
                    if fdwwpn == initiatorWwpn:
                        fActive = True
                        break
        except Exception:
            LOG.error(_LE('Failed to get sns table'))
        return fActive

    def _convertHex2String(self, wwpns):
        szwwpns = ''
        if len(str(wwpns)) == 16:
            szwwpns = '%2s:%2s:%2s:%2s:%2s:%2s:%2s:%2s' % (
                str(wwpns)[0:2],
                str(wwpns)[2:4],
                str(wwpns)[4:6],
                str(wwpns)[6:8],
                str(wwpns)[8:10],
                str(wwpns)[10:12],
                str(wwpns)[12:14],
                str(wwpns)[14:16])
        return szwwpns

    def _export_fc(self, volumeid, targetwwpns, initiatorwwpns, volumename):
        ret = 0
        output = ''
        LOG.debug('Export fc: %(volume)s, %(wwpns)s, %(iqn)s, %(volumename)s',
                  {'volume': volumeid, 'wwpns': targetwwpns,
                   'iqn': initiatorwwpns, 'volumename': volumename})
        try:
            ret, output = self.dpl.assign_vdev_fc(
                self._conver_uuid2hex(volumeid), targetwwpns,
                initiatorwwpns, volumename)
        except Exception:
            LOG.error(_LE('Volume %(volumeid)s failed to send assign command, '
                          'ret: %(status)s output: %(output)s'),
                      {'volumeid': volumeid, 'status': ret, 'output': output})
            ret = errno.EFAULT

        if ret == errno.EAGAIN:
            ret, event_uuid = self._get_event_uuid(output)
            if len(event_uuid):
                ret = 0
                status = self._wait_event(
                    self.dpl.get_vdev_status,
                    self._conver_uuid2hex(volumeid), event_uuid)
                if status['state'] == 'error':
                    ret = errno.EFAULT
                    msg = _('Flexvisor failed to assign volume %(id)s: '
                            '%(status)s.') % {'id': volumeid,
                                              'status': status}
                    raise exception.VolumeBackendAPIException(data=msg)
            else:
                ret = errno.EFAULT
                msg = _('Flexvisor failed to assign volume %(id)s due to '
                        'unable to query status by event '
                        'id.') % {'id': volumeid}
                raise exception.VolumeBackendAPIException(data=msg)
        elif ret != 0:
            msg = _('Flexvisor assign volume failed:%(id)s:'
                    '%(status)s.') % {'id': volumeid, 'status': ret}
            raise exception.VolumeBackendAPIException(data=msg)

        return ret

    def _delete_export_fc(self, volumeid, targetwwpns, initiatorwwpns):
        ret = 0
        output = ''
        ret, output = self.dpl.unassign_vdev_fc(
            self._conver_uuid2hex(volumeid),
            targetwwpns, initiatorwwpns)
        if ret == errno.EAGAIN:
            ret, event_uuid = self._get_event_uuid(output)
            if ret == 0 and len(event_uuid):
                status = self._wait_event(
                    self.dpl.get_vdev_status, volumeid, event_uuid)
                if status['state'] == 'error':
                    ret = errno.EFAULT
                    msg = _('Flexvisor failed to unassign volume %(id)s:'
                            ' %(status)s.') % {'id': volumeid,
                                               'status': status}
                    raise exception.VolumeBackendAPIException(data=msg)
            else:
                msg = _('Flexvisor failed to unassign volume (get event) '
                        '%(id)s.') % {'id': volumeid}
                raise exception.VolumeBackendAPIException(data=msg)
        elif ret != 0:
            msg = _('Flexvisor unassign volume failed:%(id)s:'
                    '%(status)s.') % {'id': volumeid, 'status': ret}
            raise exception.VolumeBackendAPIException(data=msg)
        else:
            LOG.info(_LI('Flexvisor succeeded to unassign volume %(id)s.'),
                     {'id': volumeid})

        return ret

    def _build_initiator_target_map(self, connector, tgtwwns):
        """Build the target_wwns and the initiator target map."""
        init_targ_map = {}
        initiator_wwns = connector['wwpns']
        for initiator in initiator_wwns:
            init_targ_map[initiator] = tgtwwns

        return init_targ_map

    @fczm_utils.AddFCZone
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        """
            connector = {'ip': CONF.my_ip,
                         'host': CONF.host,
                         'initiator': self._initiator,
                         'wwnns': self._fc_wwnns,
                         'wwpns': self._fc_wwpns}

        """
        dc_fc = {}
        dc_target = {}
        lsTargetWwpn = []
        output = None
        properties = {}
        preferTargets = {}
        ret = 0
        targetIdentifier = []
        szwwpns = []
        LOG.info(_LI('initialize_connection volume: %(volume)s, connector:'
                     ' %(connector)s'),
                 {"volume": volume, "connector": connector})
        # Get Storage Fiber channel controller
        dc_fc = self._get_fc_channel()

        # Get existed FC target list to decide target wwpn
        dc_target = self._get_targets()
        if len(dc_target) == 0:
            msg = _('Backend storage did not configure fiber channel '
                    'target.')
            raise exception.VolumeBackendAPIException(data=msg)

        for keyFc in dc_fc.keys():
            for targetuuid in dc_target.keys():
                if dc_fc[keyFc]['hardware_address'] == \
                        dc_target[targetuuid]['targetAddr']:
                    preferTargets[targetuuid] = dc_target[targetuuid]
                    break
        # Confirm client wwpn is existed in sns table
        # Covert wwwpns to 'xx:xx:xx:xx:xx:xx:xx:xx' format
        for dwwpn in connector['wwpns']:
            szwwpn = self._convertHex2String(dwwpn)
            if len(szwwpn) == 0:
                msg = _('Invalid wwpns format %(wwpns)s') % \
                    {'wwpns': connector['wwpns']}
                raise exception.VolumeBackendAPIException(data=msg)
            szwwpns.append(szwwpn)

        if len(szwwpns):
            for targetUuid in preferTargets.keys():
                targetWwpn = ''
                targetWwpn = preferTargets.get(targetUuid,
                                               {}).get('targetAddr', '')
                lsTargetWwpn.append(targetWwpn)
        # Use wwpns to assign volume.
        LOG.info(_LI('Prefer use target wwpn %(wwpn)s'),
                 {'wwpn': lsTargetWwpn})
        # Start to create export in all FC target node.
        assignedTarget = []
        for pTarget in lsTargetWwpn:
            try:
                ret = self._export_fc(volume['id'], str(pTarget), szwwpns,
                                      volume['name'])
                if ret:
                    break
                else:
                    assignedTarget.append(pTarget)
            except Exception as e:
                LOG.error(_LE('Failed to export fiber channel target '
                              'due to %s'), e)
                ret = errno.EFAULT
                break
        if ret == 0:
            ret, output = self.dpl.get_vdev(self._conver_uuid2hex(
                volume['id']))
        nLun = -1
        if ret == 0:
            try:
                for p in output['exports']['Network/FC']:
                    # check initiator wwpn existed in target initiator list
                    for initI in p.get('permissions', []):
                        for szwpn in szwwpns:
                            if initI.get(szwpn, None):
                                nLun = initI[szwpn]
                                break
                        if nLun != -1:
                            break

                    if nLun != -1:
                        targetIdentifier.append(
                            str(p['target_identifier']).replace(':', ''))

            except Exception:
                msg = _('Invalid connection initialization response of '
                        'volume %(name)s: '
                        '%(output)s') % {'name': volume['name'],
                                         'output': output}
                raise exception.VolumeBackendAPIException(data=msg)

        if nLun != -1:
            init_targ_map = self._build_initiator_target_map(connector,
                                                             targetIdentifier)
            properties['target_discovered'] = True
            properties['target_wwn'] = targetIdentifier
            properties['target_lun'] = int(nLun)
            properties['volume_id'] = volume['id']
            properties['initiator_target_map'] = init_targ_map
            LOG.info(_LI('%(volume)s assign type fibre_channel, properties '
                         '%(properties)s'),
                     {'volume': volume['id'], 'properties': properties})
        else:
            msg = _('Invalid connection initialization response of '
                    'volume %(name)s') % {'name': volume['name']}
            raise exception.VolumeBackendAPIException(data=msg)
        LOG.info(_LI('Connect initialization info: '
                     '{driver_volume_type: fibre_channel, '
                     'data: %(properties)s'), {'properties': properties})
        return {'driver_volume_type': 'fibre_channel',
                'data': properties}

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        """
            connector = {'ip': CONF.my_ip,
                         'host': CONF.host,
                         'initiator': self._initiator,
                         'wwnns': self._fc_wwnns,
                         'wwpns': self._fc_wwpns}
        """
        lstargetWwpns = []
        lsTargets = []
        szwwpns = []
        ret = 0
        info = {'driver_volume_type': 'fibre_channel', 'data': {}}
        LOG.info(_LI('terminate_connection volume: %(volume)s, '
                     'connector: %(con)s'),
                 {'volume': volume, 'con': connector})
        # Query targetwwpns.
        # Get all target list of volume.
        for dwwpn in connector['wwpns']:
            szwwpn = self._convertHex2String(dwwpn)
            if len(szwwpn) == 0:
                msg = _('Invalid wwpns format %(wwpns)s') % \
                    {'wwpns': connector['wwpns']}
                raise exception.VolumeBackendAPIException(data=msg)
            szwwpns.append(szwwpn)

        if len(szwwpns) == 0:
            ret = errno.EFAULT
            msg = _('Invalid wwpns format %(wwpns)s') % \
                {'wwpns': connector['wwpns']}
            raise exception.VolumeBackendAPIException(data=msg)
        else:
            for szwwpn in szwwpns:
                lstargetWwpns = self._get_targetwpns(
                    self._conver_uuid2hex(volume['id']), szwwpn)
                lsTargets = list(set(lsTargets + lstargetWwpns))

        # Remove all export target
        try:
            for ptarget in lsTargets:
                ret = self._delete_export_fc(volume['id'], ptarget, szwwpns)
                if ret:
                    break
        except Exception:
            ret = errno.EFAULT
        finally:
            if ret:
                msg = _('Faield to unassign %(volume)s') % (volume['id'])
                raise exception.VolumeBackendAPIException(data=msg)

        # Failed to delete export with fibre channel
        if ret:
            init_targ_map = self._build_initiator_target_map(connector,
                                                             lsTargets)
            info['data'] = {'target_wwn': lsTargets,
                            'initiator_target_map': init_targ_map}

        return info

    def get_volume_stats(self, refresh=False):
        if refresh:
            data = super(DPLFCDriver, self).get_volume_stats(refresh)
            if data:
                data['storage_protocol'] = 'FC'
                backend_name = \
                    self.configuration.safe_get('volume_backend_name')
                data['volume_backend_name'] = (backend_name or 'DPLFCDriver')
                self._stats = data
        return self._stats
