# Copyright (c) 2019 MacroSAN Technologies Co., Ltd.
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
"""Base device operation on MacroSAN SAN."""


import logging
from random import shuffle

import requests

from cinder import exception
from cinder.i18n import _


LOG = logging.getLogger(__name__)

context_request_id = None


class Client(object):
    """Device Client to do operation."""

    def __init__(self, sp1_ip, sp2_ip, secret_key):
        """Initialize the client."""
        self.sp1_ip = sp1_ip
        self.sp2_ip = sp2_ip
        self.port = 12138
        self.choosed_ip = None
        self.last_request_id = None
        self.last_ip = None
        self.timeout = 30
        self.SECRET_KEY = secret_key
        self.url_prefix = '/api/v1'

    def conn_test(self):
        iplist = [('sp1', self.sp1_ip), ('sp2', self.sp2_ip)]
        shuffle(iplist)
        ha = {}
        for sp, ip in iplist:
            try:
                url = ('http://%s:%s%s/ha_status' %
                       (ip, str(self.port), self.url_prefix))
                header = {'Authorization': 'Bearer %s' % self.SECRET_KEY}
                response = requests.get(url=url,
                                        timeout=self.timeout, headers=header)
                ha = self.response_processing(response)
                if ha[sp] in ['single', 'double']:
                    LOG.debug('Heart Beating......%(ha)s ', {'ha': ha})
                    return ip
            except Exception:
                pass
        raise exception.VolumeBackendAPIException(
            data=_('Connect to MacroSAN IPSAN Error, HA Status:%s') % str(ha))

    def send_request(self, method='get', url='/', data=None):
        header = {'Authorization': 'Bearer %s' % self.SECRET_KEY}
        try:
            ip = self.conn_test()
            url = ('http://%s:%s%s%s' %
                   (ip, str(self.port), self.url_prefix, url))
            response = None
            if method == 'get':
                response = requests.get(url=url, params=data,
                                        timeout=self.timeout, headers=header)
            elif method == 'post':
                response = requests.post(url=url, json=data,
                                         timeout=self.timeout, headers=header)
            elif method == 'put':
                response = requests.put(url=url, json=data,
                                        timeout=self.timeout, headers=header)
            elif method == 'delete':
                response = requests.delete(url=url, json=data,
                                           timeout=self.timeout,
                                           headers=header)
            return self.response_processing(response)
        except requests.exceptions.ConnectionError:
            LOG.error('========== Unable to establish connection '
                      'with VolumeBackend %(url)s', {'url': url})

    def response_processing(self, response):
        if response.status_code != 200:
            LOG.error('========== Command %(url)s execution error,'
                      'response_conde: %(status)s',
                      {'url': response.url, 'status': response.status_code})
            raise exception.VolumeBackendAPIException(data=response.json())
        LOG.debug('The response is: %(response)s, %(text)s',
                  {'response': response, 'text': response.json()})
        return response.json()

    def get_ha_state(self):
        """Get HA state."""
        return self.send_request(method='get', url='/ha_status')

    def lun_exists(self, name):
        """Whether the lun exists."""
        data = {
            'attr': 'existence',
            'name': name
        }
        return self.send_request(method='get', url='/lun', data=data)

    def snapshot_point_exists(self, lun_name, pointid):
        """Whether the snapshot point exists."""
        data = {
            'attr': 'existence',
            'lun_name': lun_name,
            'pointid': pointid
        }
        return self.send_request(method='get',
                                 url='/snapshot_point', data=data)

    def it_exists(self, initr_wwn, tgt_port_name):
        """Whether the it exists."""
        data = {
            'attr': 'it',
            'initr_wwn': initr_wwn,
            'tgt_port_name': tgt_port_name
        }
        return self.send_request(method='get', url='/itl', data=data)

    def is_initiator_mapped_to_client(self, initr_wwn, client_name):
        """Whether initiator is mapped to client."""
        data = {
            'initr_wwn': initr_wwn,
            'client_name': client_name,
            'attr': 'list'
        }
        return self.send_request(method='get', url='/initiator', data=data)

    def snapshot_resource_exists(self, lun_name):
        """Whether the snapshot resource exists."""
        data = {
            'lun_name': lun_name
        }
        return self.send_request(method='get',
                                 url='/snapshot_resource', data=data)

    def initiator_exists(self, initr_wwn):
        """Whether the initiator exists."""
        data = {
            'attr': 'existence',
            'initr_wwn': initr_wwn,
        }
        return self.send_request(method='get', url='/initiator', data=data)

    def get_client(self, name):
        """Get client info."""
        return self.send_request(method='get',
                                 url='/client', data={'name': name})

    def delete_lun(self, name):
        """Delete a lun."""
        return self.send_request(method='delete',
                                 url='/lun', data={'name': name})

    def get_lun_sp(self, name):
        """Get lun sp."""
        data = {
            'attr': 'lun_sp',
            'name': name
        }
        return self.send_request(method='get', url='/lun', data=data)

    def get_snapshot_resource_name(self, lun_name):
        """Whether the snapshot resource exists."""
        return self.send_request(method='get', url='/snapshot_resource',
                                 data={'lun_name': lun_name})

    def rename_lun(self, old_name, new_name):
        """Rename a lun."""
        return self.send_request(method='put', url='/lun',
                                 data={'attr': 'name', 'old_name': old_name,
                                       'new_name': new_name})

    def create_lun(self, name, owner, pool, raids, lun_mode, size, lun_params):
        """Create a lun."""
        data = {'name': name,
                'owner': owner,
                'pool': pool,
                'raids': raids,
                'lun_mode': lun_mode,
                'size': size,
                'lun_params': lun_params}
        return self.send_request(method='post', url='/lun', data=data)

    def get_raid_list(self, pool):
        """Get a raid list."""
        return self.send_request(method='get',
                                 url='/raid_list', data={'pool': pool})

    def get_pool_cap(self, pool):
        """Get pool capacity."""
        return self.send_request(method='get',
                                 url='/pool', data={'pool': pool})

    def get_lun_base_info(self, name):
        data = {'attr': 'base_info',
                'name': name}
        return self.send_request(method='get', url='/lun', data=data)

    def extend_lun(self, name, raids, size):
        """Extend a lun."""
        data = {
            'attr': 'capicity',
            'name': name,
            'raids': raids,
            'size': size
        }
        return self.send_request(method='put', url='/lun', data=data)

    def enable_lun_qos(self, name, strategy):
        """Enable lun qos."""
        data = {
            'attr': 'qos',
            'name': name,
            'strategy': strategy
        }
        return self.send_request(method='put', url='/lun', data=data)

    def localclone_exists(self, lun):
        """Whether localclone lun exists."""
        return self.send_request(method='get', url='/local_clone',
                                 data={'attr': 'existence', 'lun': lun})

    def localclone_completed(self, lun):
        """Whether localclone lun completed."""
        return self.send_request(method='get', url='/local_clone',
                                 data={'attr': 'completed', 'lun': lun})

    def start_localclone_lun(self, master, slave):
        """start localclone lun."""
        return self.send_request(method='post', url='/local_clone',
                                 data={'master': master, 'slave': slave})

    def stop_localclone_lun(self, lun):
        """stop localclone lun."""
        return self.send_request(method='delete', url='/local_clone',
                                 data={'lun': lun})

    def create_snapshot_resource(self, lun_name, raids, size):
        """Create a snapshot resource."""
        data = {
            'lun_name': lun_name,
            'raids': raids,
            'size': size
        }
        return self.send_request(method='post', url='/snapshot_resource',
                                 data=data)

    def enable_snapshot_resource_autoexpand(self, lun_name):
        """Enable snapshot resource autoexpand."""
        data = {
            'attr': 'autoexpand',
            'lun_name': lun_name
        }
        return self.send_request(method='put', url='/snapshot_resource',
                                 data=data)

    def enable_snapshot(self, lun_name):
        """Enable snapshot."""
        data = {
            'attr': 'enable',
            'lun_name': lun_name
        }
        return self.send_request(method='put', url='/snapshot', data=data)

    def snapshot_enabled(self, lun_name):
        """Weather enable snapshot"""
        params = {
            'attr': 'enable',
            'lun_name': lun_name
        }
        return self.send_request(method='get', url='/snapshot', data=params)

    def delete_snapshot_resource(self, lun_name):
        """Delete a snapshot resource."""
        data = {'lun_name': lun_name}
        return self.send_request(method='delete', url='/snapshot_resource',
                                 data=data)

    def create_snapshot_point(self, lun_name, snapshot_name):
        """Create a snapshot point."""
        data = {
            'lun_name': lun_name,
            'snapshot_name': snapshot_name
        }
        return self.send_request(method='post', url='/snapshot_point',
                                 data=data)

    def get_snapshot_pointid(self, lun_name, snapshot_name):
        """Get a snapshot pointid."""
        params = {
            'attr': 'point_id',
            'lun_name': lun_name,
            'snapshot_name': snapshot_name
        }
        return self.send_request(method='get', url='/snapshot_point',
                                 data=params)

    def rename_snapshot_point(self, lun_name, pointid, name):
        data = {
            'attr': 'name',
            'lun_name': lun_name,
            'pointid': pointid,
            'name': name
        }
        return self.send_request(method='put', url='/snapshot_point',
                                 data=data)

    def disable_snapshot(self, lun_name):
        """Disable snapshot."""
        data = {
            'attr': 'disable',
            'lun_name': lun_name
        }
        return self.send_request(method='put', url='/snapshot', data=data)

    def delete_snapshot_point(self, lun_name, pointid):
        """Delete a snapshot point."""
        data = {
            'lun_name': lun_name,
            'pointid': pointid
        }
        return self.send_request(method='delete', url='/snapshot_point',
                                 data=data)

    def get_snapshot_point_num(self, lun_name):
        """Get snapshot point number."""
        data = {
            'attr': 'number',
            'lun_name': lun_name
        }
        return self.send_request(method='get', url='/snapshot_point',
                                 data=data)

    def create_client(self, name):
        """Create a client."""
        return self.send_request(method='post', url='/client',
                                 data={'name': name})

    def create_target(self, port_name, type='fc'):
        """Create a target."""
        data = {
            'port_name': port_name,
            'type': type
        }
        return self.send_request(method='post', url='/target', data=data)

    def delete_target(self, tgt_name):
        """Delete a target."""
        return self.send_request(method='delete', url='/target',
                                 data={'tgt_name': tgt_name})

    def create_initiator(self, initr_wwn, alias, type='fc'):
        """Create an initiator."""
        data = {
            'initr_wwn': initr_wwn,
            'alias': alias,
            'type': type
        }
        return self.send_request(method='post', url='/initiator', data=data)

    def delete_initiator(self, initr_wwn):
        """Delete an initiator."""
        return self.send_request(method='delete', url='/initiator',
                                 data={'initr_wwn': initr_wwn})

    def map_initiator_to_client(self, initr_wwn, client_name):
        """Map initiator to client."""
        data = {
            'attr': 'mapinitiator',
            'initr_wwn': initr_wwn,
            'client_name': client_name
        }
        return self.send_request(method='put', url='/client', data=data)

    def unmap_initiator_from_client(self, initr_wwn, client_name):
        """Unmap target from initiator."""
        data = {
            'attr': 'unmapinitiator',
            'initr_wwn': initr_wwn,
            'client_name': client_name
        }
        return self.send_request(method='put', url='/client', data=data)

    def map_target_to_initiator(self, tgt_port_name, initr_wwn):
        """Map target to initiator."""
        data = {
            'attr': 'maptarget',
            'initr_wwn': initr_wwn,
            'tgt_port_name': tgt_port_name
        }
        return self.send_request(method='post', url='/itl', data=data)

    def unmap_target_from_initiator(self, tgt_port_name, initr_wwn):
        """Unmap target from initiator."""
        data = {
            'attr': 'unmaptarget',
            'initr_wwn': initr_wwn,
            'tgt_port_name': tgt_port_name
        }
        return self.send_request(method='delete', url='/itl', data=data)

    def map_lun_to_it(self, lun_name, initr_wwn, tgt_port_name, lun_id=-1):
        """Map lun to it."""
        data = {
            'attr': 'maplun',
            'lun_name': lun_name,
            'initr_wwn': initr_wwn,
            'tgt_port_name': tgt_port_name,
            'lun_id': lun_id
        }
        return self.send_request(method='post', url='/itl', data=data)

    def unmap_lun_to_it(self, lun_name, initr_wwn, tgt_port_name):
        """Unmap lun to it."""
        data = {
            'attr': 'unmaplun',
            'lun_name': lun_name,
            'initr_wwn': initr_wwn,
            'tgt_port_name': tgt_port_name,
        }
        return self.send_request(method='delete', url='/itl', data=data)

    def has_initiators_mapped_any_lun(self, initr_wwns, type='fc'):
        """Whether has initiators mapped any lun."""
        data = {
            'attr': 'itl',
            'initr_wwns': initr_wwns,
            'type': type
        }
        return self.send_request(method='get', url='/itl', data=data)

    def create_snapshot_view(self, view_name, lun_name, pointid):
        """Create a snapshot view."""
        data = {
            'view_name': view_name,
            'lun_name': lun_name,
            'pointid': pointid
        }
        return self.send_request(method='post', url='/snapshot_view',
                                 data=data)

    def delete_snapshot_view(self, view_name):
        """Delete a snapshot view."""
        return self.send_request(method='delete', url='/snapshot_view',
                                 data={'view_name': view_name})

    def get_fc_initr_mapped_ports(self, initr_wwns):
        """Get initiator mapped port."""
        data = {
            'attr': 'fc_initr_mapped_ports',
            'initr_wwns': initr_wwns
        }
        return self.send_request(method='get', url='/initiator', data=data)

    def get_fc_ports(self):
        """Get FC ports."""
        data = {
            'attr': 'fc_ports',
        }
        return self.send_request(method='get', url='/initiator', data=data)

    def get_iscsi_ports(self):
        """Get iSCSI ports."""
        data = {
            'attr': 'iscsi_ports',
        }
        return self.send_request(method='get', url='/initiator', data=data)

    def get_lun_id(self, initr_wwn, tgt_port_name, lun_name):
        """Get lun id."""
        data = {
            'attr': 'lun_id',
            'initr_wwn': initr_wwn,
            'tgt_port_name': tgt_port_name,
            'lun_name': lun_name
        }
        return self.send_request(method='get', url='/lun', data=data)

    def get_lun_uuid(self, lun_name):
        """Get lun uuid."""
        data = {
            'attr': 'lun_uuid',
            'lun_name': lun_name
        }
        return self.send_request(method='get', url='/lun', data=data)

    def get_lun_name(self, lun_uuid):
        """Get lun name."""
        data = {
            'attr': 'lun_name',
            'lun_uuid': lun_uuid
        }
        return self.send_request(method='get', url='/lun', data=data)

    def copy_volume_from_view(self, lun_name, view_name):
        """Copy volume from view."""
        data = {
            'attr': 'from_view',
            'lun_name': lun_name,
            'view_name': view_name
        }
        return self.send_request(method='post', url='/copy_volume', data=data)

    def snapshot_copy_task_completed(self, lun_name):
        data = {
            'attr': 'snapshot_copy_task_completed',
            'lun_name': lun_name
        }
        return self.send_request(method='get', url='/copy_volume', data=data)

    def copy_volume_from_volume(self, lun_name, src_lun_name):
        """Copy volume from volume."""
        data = {
            'attr': 'from_volume',
            'lun_name': lun_name,
            'src_lun_name': src_lun_name
        }
        return self.send_request(method='post', url='/copy_volume', data=data)

    def query_bcopy_task(self, task_id):
        """Query bcopy task."""
        data = {
            'attr': 'bcopy_task',
            'task_id': task_id
        }
        return self.send_request(method='get', url='/copy_volume', data=data)

    def get_it_unused_id_list(self, it_type, initr_wwn, tgt_port_name):
        data = {
            'attr': 'it_unused_id_list',
            'it_type': it_type,
            'initr_wwn': initr_wwn,
            'tgt_port_name': tgt_port_name
        }
        return self.send_request(method='get', url='/initiator', data=data)

    def backup_lun_name_to_rename_file(self, cur_name, original_name):
        """Backup lun name to rename file."""
        data = {
            'cur_name': cur_name,
            'original_name': original_name
        }
        return self.send_request(method='post', url='/rename_file', data=data)

    def get_lun_name_from_rename_file(self, name):
        """Get lun name from rename file."""
        data = {'name': name}
        return self.send_request(method='get', url='/rename_file', data=data)

    def create_dalun(self, lun_name):
        data = {'lun_name': lun_name}
        return self.send_request(method='post', url='/dalun', data=data)

    def delete_dalun(self, lun_name):
        data = {'lun_name': lun_name}
        return self.send_request(method='delete', url='/dalun', data=data)

    def dalun_exists(self, lun_name):
        data = {
            'attr': 'existence',
            'lun_name': lun_name
        }
        return self.send_request(method='get', url='/dalun', data=data)

    def suspend_dalun(self, lun_name):
        data = {
            'attr': 'suspend',
            'lun_name': lun_name
        }
        return self.send_request(method='put', url='/dalun', data=data)

    def resume_dalun(self, lun_name):
        data = {
            'attr': 'resume',
            'lun_name': lun_name
        }
        return self.send_request(method='put', url='/dalun', data=data)

    def setup_snapshot_resource(self, volume_name, size, raids):
        if not self.snapshot_resource_exists(volume_name):
            self.create_snapshot_resource(volume_name, raids, size)
            if self.enable_snapshot_resource_autoexpand(
                    volume_name).status_code != 200:
                LOG.warning('========== Enable snapshot resource auto '
                            'expand for volume: %s error', volume_name)

    def get_raid_list_to_create_lun(self, pool, size):
        raids = self.get_raid_list(pool)
        free = sum(raid['free_cap'] for raid in raids)
        if size > free:
            raise exception.VolumeBackendAPIException(
                data=_('Pool has not enough free capacity'))

        raids = sorted(raids, key=lambda x: x['free_cap'], reverse=True)

        selected = []
        cap = 0
        for raid in raids:
            if raid['free_cap']:
                cap += raid['free_cap']
                selected.append(raid['name'])
                if cap >= size:
                    break
        return selected

    def get_port_ipaddr(self, port):
        data = {
            'attr': 'port_ipaddr',
            'port': port,
        }
        return self.send_request(method='get', url='/itl', data=data)

    def enable_replication(self, lun_name, sp1, sp2):
        data = {
            'attr': 'enable',
            'lun_name': lun_name,
            'sp1': sp1,
            'sp2': sp2,
        }
        return self.send_request(method='put', url='/replication', data=data)

    def disable_replication(self, lun_name):
        data = {
            'attr': 'disable',
            'lun_name': lun_name,
        }
        return self.send_request(method='put', url='/replication', data=data)

    def replication_enabled(self, lun_name):
        data = {
            'attr': 'enabled',
            'lun_name': lun_name
        }
        return self.send_request(method='get', url='/replication', data=data)

    def startscan_replication(self, lun_name):
        data = {
            'attr': 'startscan',
            'lun_name': lun_name
        }
        return self.send_request(method='put', url='/replication', data=data)

    def stopscan_replication(self, lun_name):
        data = {
            'attr': 'stopscan',
            'lun_name': lun_name
        }
        return self.send_request(method='put', url='/replication', data=data)

    def pausereplicate(self, lun_name):
        data = {
            'attr': 'pause',
            'lun_name': lun_name
        }
        return self.send_request(method='put', url='/replication', data=data)

    def get_device_uuid(self):
        return self.send_request(method='get', url='/device')

    def get_lun_it(self, name):
        data = {
            'attr': 'getitl',
            'name': name
        }
        return self.send_request(method='get', url='/itl', data=data)
