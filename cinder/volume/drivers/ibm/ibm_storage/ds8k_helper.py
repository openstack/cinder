#  Copyright (c) 2016 IBM Corporation
#  All Rights Reserved.
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
#
import collections
import distutils.version as dist_version  # pylint: disable=E0611
import eventlet
import math
import os
import six
import string

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _, _LI, _LW, _LE
from cinder.objects import fields
import cinder.volume.drivers.ibm.ibm_storage as storage
from cinder.volume.drivers.ibm.ibm_storage import cryptish
from cinder.volume.drivers.ibm.ibm_storage import ds8k_restclient as restclient
from cinder.volume.drivers.ibm.ibm_storage import proxy
from cinder.volume.drivers.ibm.ibm_storage import strings

LOG = logging.getLogger(__name__)

LSS_VOL_SLOTS = 0x100
LSS_SLOTS = 0xFF

VALID_HOST_TYPES = (
    'auto', 'AMDLinuxRHEL', 'AMDLinuxSuse',
    'AppleOSX', 'Fujitsu', 'Hp', 'HpTru64',
    'HpVms', 'LinuxDT', 'LinuxRF', 'LinuxRHEL',
    'LinuxSuse', 'Novell', 'SGI', 'SVC',
    'SanFsAIX', 'SanFsLinux', 'Sun', 'VMWare',
    'Win2000', 'Win2003', 'Win2008', 'Win2012',
    'iLinux', 'nSeries', 'pLinux', 'pSeries',
    'pSeriesPowerswap', 'zLinux', 'iSeries'
)


def filter_alnum(s):
    return ''.join(x if x in string.ascii_letters +
                   string.digits else '_' for x in s) if s else ''


class DS8KCommonHelper(object):
    """Manage the primary backend, it is common class too."""

    # if use new REST API, please update the version below
    VALID_REST_VERSION_5_7_MIN = '5.7.51.1047'
    VALID_REST_VERSION_5_8_MIN = ''
    INVALID_STORAGE_VERSION = '8.0.1'

    def __init__(self, conf, HTTPConnectorObject=None):
        self.conf = conf
        self._connector_obj = HTTPConnectorObject
        self._storage_pools = None
        self._disable_thin_provision = False
        self._connection_type = self._get_value('connection_type')
        self.backend = {}
        self.setup()

    @staticmethod
    def _gb2b(gb):
        return gb * (2 ** 30)

    def _get_value(self, key):
        if getattr(self.conf, 'safe_get', 'get') == 'get':
            return self.conf.get(key)
        else:
            return self.conf.safe_get(key)

    def get_thin_provision(self):
        return self._disable_thin_provision

    def get_storage_pools(self):
        return self._storage_pools

    def get_connection_type(self):
        return self._connection_type

    def get_pool(self, lss):
        node = int(lss, 16) % 2
        pids = [
            pid for pid, p in self._storage_pools.items() if p['node'] == node]
        return pids[0] if pids else None

    def setup(self):
        self._create_client()
        self._get_storage_information()
        self._check_host_type()
        self.backend['pools_str'] = self._get_value('san_clustername')
        self._verify_version()
        self._verify_pools()

    def update_client(self):
        self._client.close()
        self._create_client()

    def _get_certificate(self, host):
        cert_file = strings.CERTIFICATES_PATH + host + '.pem'
        msg = "certificate file for DS8K %(host)s: %(cert)s"
        LOG.debug(msg, {'host': host, 'cert': cert_file})
        # Use the certificate if it exists, otherwise use the System CA Bundle
        if os.path.exists(cert_file):
            return cert_file
        else:
            LOG.debug("certificate file not found.")
            return True

    def _create_client(self):
        try:
            clear_pass = cryptish.decrypt(self._get_value('san_password'))
        except TypeError:
            err = _('Param [san_password] is invalid.')
            raise exception.InvalidParameterValue(err=err)
        verify = self._get_certificate(self._get_value('san_ip'))
        try:
            self._client = restclient.RESTScheduler(
                self._get_value('san_ip'),
                self._get_value('san_login'),
                clear_pass,
                self._connector_obj,
                verify)
        except restclient.TimeoutException:
            msg = (_("Can't connect to %(host)s") %
                   {'host': self._get_value('san_ip')})
            raise restclient.APIException(data=msg)
        self.backend['rest_version'] = self._get_version()['bundle_version']
        msg = _LI("Connection to DS8K storage system %(host)s has been "
                  "established successfully, the version of REST is %(rest)s.")
        LOG.info(msg, {
            'host': self._get_value('san_ip'),
            'rest': self.backend['rest_version']
        })

    def _get_storage_information(self):
        storage_info = self.get_systems()
        self.backend['storage_unit'] = storage_info['id']
        self.backend['storage_wwnn'] = storage_info['wwnn']
        self.backend['storage_version'] = storage_info['release']

    def _check_host_type(self):
        ds8k_host_type = self._get_value('ds8k_host_type')
        if ((ds8k_host_type is not None) and
           (ds8k_host_type not in VALID_HOST_TYPES)):
            msg = (_("Param [ds8k_host_type] must be one of: %(values)s.") %
                   {'values': VALID_HOST_TYPES[1:-1]})
            LOG.error(msg)
            raise exception.InvalidParameterValue(err=msg)
        self.backend['host_type_override'] = (
            None if ds8k_host_type == 'auto' else ds8k_host_type)

    def _verify_version(self):
        if self.backend['storage_version'] == self.INVALID_STORAGE_VERSION:
            raise exception.VolumeDriverException(
                message=(_("%s does not support bulk deletion of volumes, "
                           "if you want to use this version of driver, "
                           "please upgrade the CCL.")
                         % self.INVALID_STORAGE_VERSION))
        if ('5.7' in self.backend['rest_version'] and
           dist_version.LooseVersion(self.backend['rest_version']) <
           dist_version.LooseVersion(self.VALID_REST_VERSION_5_7_MIN)):
            raise exception.VolumeDriverException(
                message=(_("REST version %(invalid)s is lower than "
                           "%(valid)s, please upgrade it in DS8K.")
                         % {'invalid': self.backend['rest_version'],
                            'valid': self.VALID_REST_VERSION_5_7_MIN}))

    def _verify_pools(self):
        if self._connection_type == storage.XIV_CONNECTION_TYPE_FC:
            ptype = 'fb'
        elif self._connection_type == storage.XIV_CONNECTION_TYPE_FC_ECKD:
            ptype = 'ckd'
        else:
            err = _('Param [connection_type] is invalid.')
            raise exception.InvalidParameterValue(err=err)
        self._storage_pools = self.get_pools()
        for pid, p in self._storage_pools.items():
            if p['stgtype'] != ptype:
                msg = _LE('The stgtype of pool %(pool)s is %(ptype)s.')
                LOG.error(msg, {'pool': pid, 'ptype': p['stgtype']})
                err = _('Param [san_clustername] is invalid.')
                raise exception.InvalidParameterValue(err=err)

    @proxy.logger
    def get_pools(self, new_pools=None):
        if new_pools is None:
            pools_str = self.backend['pools_str']
        else:
            pools_str = new_pools
        pools_str = pools_str.replace(' ', '').upper().split(',')

        pools = self._get_pools(pools_str)
        unsorted_pools = self._format_pools(pools)
        storage_pools = collections.OrderedDict(sorted(
            unsorted_pools, key=lambda i: i[1]['capavail'], reverse=True))
        if new_pools is None:
            self._storage_pools = storage_pools
        return storage_pools

    def _format_pools(self, pools):
        return ((p['id'], {
            'name': p['name'],
            'node': int(p['node']),
            'stgtype': p['stgtype'],
            'cap': int(p['cap']),
            'capavail': int(p['capavail'])
        }) for p in pools)

    @proxy.logger
    def find_available_lss(self, pool, find_new_pid, excluded_lss):
        if pool:
            node = int(pool[1:], 16) % 2
            lss = self._find_lss(node, excluded_lss)
            if lss:
                return (pool, lss)
            else:
                if not find_new_pid:
                    msg = _('All LSS/LCU IDs for configured pools on '
                            'storage are exhausted.')
                    raise restclient.LssIDExhaustError(message=msg)
        # find new pool id and lss for lun
        return self.find_biggest_pool_and_lss(excluded_lss)

    @proxy.logger
    def find_biggest_pool_and_lss(self, excluded_lss):
        # pools are ordered by capacity
        for pool_id, pool in self._storage_pools.items():
            lss = self._find_lss(pool['node'], excluded_lss)
            if lss:
                return pool_id, lss
        msg = _("All LSS/LCU IDs for configured pools are exhausted.")
        raise restclient.LssIDExhaustError(message=msg)

    @proxy.logger
    def _find_lss(self, node, excluded_lss):
        fileds = ['id', 'type', 'addrgrp', 'group', 'configvols']
        existing_lss = self.get_all_lss(fileds)
        msg = _LI("existing LSS IDs are: %s.")
        LOG.info(msg, ','.join([lss['id'] for lss in existing_lss]))

        if excluded_lss:
            existing_lss = [lss for lss in existing_lss
                            if lss['id'] not in excluded_lss]
        lss = self._find_from_existing_lss(node, existing_lss)
        lss = lss if lss else self._find_from_unexisting_lss(node,
                                                             existing_lss)
        return lss

    def _find_from_existing_lss(self, node, existing_lss):
        lss_in_pprc = self.get_lss_in_pprc_paths()
        if lss_in_pprc:
            existing_lss = [lss for lss in existing_lss
                            if lss['id'] not in lss_in_pprc]
        existing_lss = [lss for lss in existing_lss if lss['type'] == 'fb'
                        and int(lss['group']) == node]
        lss_id = None
        if existing_lss:
            # look for the emptiest lss from existing lss
            lss = sorted(existing_lss, key=lambda k: int(k['configvols']))[0]
            if int(lss['configvols']) < LSS_VOL_SLOTS:
                lss_id = lss['id']
                msg = _LI('_find_from_existing_lss: choose %(lss)s. '
                          'now it has %(num)s volumes.')
                LOG.info(msg, {'lss': lss_id, 'num': lss['configvols']})
        return lss_id

    def _find_from_unexisting_lss(self, node, existing_lss):
        addrgrps = set(int(lss['addrgrp'], 16) for lss in existing_lss if
                       lss['type'] == 'ckd' and int(lss['group']) == node)

        fulllss = set(int(lss['id'], 16) for lss in existing_lss if
                      lss['type'] == 'fb' and int(lss['group']) == node)

        # look for an available lss from unexisting lss
        lss_id = None
        for lss in range(node, LSS_SLOTS, 2):
            addrgrp = lss // 16
            if addrgrp not in addrgrps and lss not in fulllss:
                lss_id = ("%02x" % lss).upper()
                break
        msg = _LI('_find_from_unexisting_lss: choose %s.')
        LOG.info(msg, lss_id)
        return lss_id

    def create_lun(self, lun):
        volData = {
            'cap': self._gb2b(lun.size),
            'captype': 'bytes',
            'stgtype': 'fb',
            'tp': 'ese' if lun.type_thin else 'none'
        }
        lun.data_type = lun.data_type if lun.data_type else 'FB 512'
        if lun.type_os400:
            volData['os400'] = lun.type_os400
        volData['name'] = lun.ds_name
        volData['pool'], volData['lss'] = lun.lss_pair['source']
        lun.ds_id = self._create_lun(volData)
        return lun

    def delete_lun(self, luns):
        lun_ids = []
        luns = [luns] if not isinstance(luns, list) else luns
        for lun in luns:
            if lun.ds_id is None:
                # create_lun must have failed and not returned the id
                LOG.error(_LE("delete_lun: volume id is None."))
                continue
            if not self.lun_exists(lun.ds_id):
                msg = _LE("delete_lun: volume %s not found.")
                LOG.error(msg, lun.ds_id)
                continue
            lun_ids.append(lun.ds_id)

        # Max 32 volumes could be deleted by specifying ids parameter
        while lun_ids:
            if len(lun_ids) > 32:
                lun_ids_str = ','.join(lun_ids[0:32])
                del lun_ids[0:32]
            else:
                lun_ids_str = ','.join(lun_ids)
                lun_ids = []
            msg = _LI("Deleting volumes: %s.")
            LOG.info(msg, lun_ids_str)
            self._delete_lun(lun_ids_str)

    def get_lss_in_pprc_paths(self):
        # TODO(Jiamin): when the REST API that get the licenses installed
        # in DS8K is ready, this function should be improved.
        try:
            paths = self.get_pprc_paths()
        except restclient.APIException:
            paths = []
            LOG.exception(_LE("Can not get the LSS"))
        lss_ids = set(p['source_lss_id'] for p in paths)
        msg = _LI('LSS in PPRC paths are: %s.')
        LOG.info(msg, ','.join(lss_ids))
        return lss_ids

    def _find_host(self, vol_id):
        host_ids = []
        hosts = self._get_hosts()
        for host in hosts:
            vol_ids = [vol['volume_id'] for vol in host['mappings_briefs']]
            if vol_id in vol_ids:
                host_ids.append(host['id'])
        msg = _LI('_find_host: host IDs are: %s.')
        LOG.info(msg, host_ids)
        return host_ids

    def wait_flashcopy_finished(self, src_luns, tgt_luns):
        finished = False
        try:
            fc_state = [False] * len(tgt_luns)
            while True:
                eventlet.sleep(5)
                for i in range(len(tgt_luns)):
                    if not fc_state[i]:
                        fcs = self.get_flashcopy(tgt_luns[i].ds_id)
                        if not fcs:
                            fc_state[i] = True
                            continue
                        if fcs[0]['state'] not in ('valid',
                                                   'validation_required'):
                            msg = (_('Flashcopy ended up in bad state %s. '
                                     'Rolling back.') % fcs[0]['state'])
                            raise restclient.APIException(data=msg)
                if fc_state.count(False) == 0:
                    break
            finished = True
        finally:
            if not finished:
                for src_lun, tgt_lun in zip(src_luns, tgt_luns):
                    self.delete_flashcopy(src_lun.ds_id, tgt_lun.ds_id)
        return finished

    def wait_pprc_copy_finished(self, vol_ids, state, delete=True):
        msg = _LI("Wait for PPRC pair to enter into state %s")
        LOG.info(msg, state)
        vol_ids = sorted(vol_ids)
        min_vol_id = min(vol_ids)
        max_vol_id = max(vol_ids)
        try:
            finished = False
            while True:
                eventlet.sleep(2)
                pairs = self.get_pprc_pairs(min_vol_id, max_vol_id)
                pairs = [
                    p for p in pairs if p['source_volume']['name'] in vol_ids]
                finished_pairs = [p for p in pairs if p['state'] == state]
                if len(finished_pairs) == len(pairs):
                    finished = True
                    break

                invalid_states = [
                    'target_suspended',
                    'invalid',
                    'volume_inaccessible'
                ]
                if state == 'full_duplex':
                    invalid_states.append('suspended')
                elif state == 'suspended':
                    invalid_states.append('valid')

                unfinished_pairs = [p for p in pairs if p['state'] != state]
                for p in unfinished_pairs:
                    if p['state'] in invalid_states:
                        msg = (_('Metro Mirror pair %(id)s enters into '
                                 'state %(state)s. ') %
                               {'id': p['id'], 'state': p['state']})
                        raise restclient.APIException(data=msg)
        finally:
            if not finished and delete:
                pair_ids = {'ids': ','.join([p['id'] for p in pairs])}
                self.delete_pprc_pair_by_pair_id(pair_ids)

    def _get_host(self, connector):
        # DS8K doesn't support hostname which is longer than 32 chars.
        hname = ('OShost:%s' % filter_alnum(connector['host']))[:32]
        os_type = connector.get('os_type')
        platform = connector.get('platform')

        if self.backend['host_type_override']:
            htype = self.backend['host_type_override']
        elif os_type == 'OS400':
            htype = 'iSeries'
        elif os_type == 'AIX':
            htype = 'pSeries'
        elif platform in ('s390', 's390x') and os_type == 'linux2':
            htype = 'zLinux'
        else:
            htype = 'LinuxRHEL'
        return collections.namedtuple('Host', ('name', 'type'))(hname, htype)

    def initialize_connection(self, vol_id, connector, **kwargs):
        host = self._get_host(connector)
        # Find defined host and undefined host ports
        host_wwpn_set = set(wwpn.upper() for wwpn in connector['wwpns'])
        host_ports = self._get_host_ports(host_wwpn_set)
        LOG.debug("host_ports: %s", host_ports)
        defined_hosts = set(
            hp['host_id'] for hp in host_ports if hp['host_id'])
        unknown_ports = host_wwpn_set - set(
            hp['wwpn'] for hp in host_ports)
        unconfigured_ports = set(
            hp['wwpn'] for hp in host_ports if not hp['host_id'])
        msg = ("initialize_connection: defined_hosts: %(defined)s, "
               "unknown_ports: %(unknown)s, unconfigured_ports: "
               "%(unconfigured)s.")
        LOG.debug(msg, {
            "defined": defined_hosts,
            "unknown": unknown_ports,
            "unconfigured": unconfigured_ports
        })
        # Create host if it is not defined
        if not defined_hosts:
            host_id = self._create_host(host)['id']
        elif len(defined_hosts) == 1:
            host_id = defined_hosts.pop()
        else:
            msg = _('More than one host defined for requested ports.')
            raise restclient.APIException(message=msg)
        LOG.info(_LI('Volume will be attached to host %s.'), host_id)

        # Create missing host ports
        if unknown_ports or unconfigured_ports:
            self._assign_host_port(host_id,
                                   list(unknown_ports | unconfigured_ports))

        # Map the volume to host
        lun_id = self._map_volume_to_host(host_id, vol_id)
        target_ports = [p['wwpn'] for p in self._get_ioports()]
        return {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'target_discovered': False,
                'target_lun': int(lun_id, 16),
                'target_wwn': target_ports,
                'initiator_target_map': {initiator: target_ports for
                                         initiator in host_wwpn_set}
            }
        }

    def terminate_connection(self, vol_id, connector, force, **kwargs):
        # If a fake connector is generated by nova when the host
        # is down, then the connector will not have a wwpns property.
        if 'wwpns' in connector:
            host = self._get_host(connector)
            host_wwpn_set = set(wwpn.upper() for wwpn in connector['wwpns'])
            host_ports = self._get_host_ports(host_wwpn_set)
            defined_hosts = set(
                hp['host_id'] for hp in host_ports if hp['host_id'])
            delete_ports = set(
                hp['wwpn'] for hp in host_ports if not hp['host_id'])
        else:
            host_ports = None
            delete_ports = None
            defined_hosts = self._find_host(vol_id)
        msg = ("terminate_connection: host_ports: %(host)s, defined_hosts: "
               "%(defined)s, delete_ports: %(delete)s.")
        LOG.debug(msg, {
            "host": host_ports,
            "defined": defined_hosts,
            "delete": delete_ports
        })

        if not defined_hosts:
            LOG.info(_LI('Could not find host.'))
            return None
        elif len(defined_hosts) > 1:
            raise restclient.APIException(_('More than one host found.'))
        else:
            host_id = defined_hosts.pop()
            mappings = self._get_mappings(host_id)
            lun_ids = [
                m['lunid'] for m in mappings if m['volume']['id'] == vol_id]
            msg = _LI('Volumes attached to host %(host)s are %(vols)s.')
            LOG.info(msg, {'host': host_id, 'vols': ','.join(lun_ids)})
            for lun_id in lun_ids:
                self._delete_mappings(host_id, lun_id)
            if not lun_ids:
                msg = _LW("Volume %(vol)s is already not mapped to "
                          "host %(host)s.")
                LOG.warning(msg, {'vol': vol_id, 'host': host.name})
            # if this host only has volumes that have been detached,
            # remove the host and its ports
            ret_info = {
                'driver_volume_type': 'fibre_channel',
                'data': {}
            }
            if len(mappings) == len(lun_ids):
                if delete_ports:
                    self._delete_host_ports(",".join(delete_ports))
                self._delete_host(host_id)
                if 'wwpns' in connector:
                    target_ports = [p['wwpn'] for p in self._get_ioports()]
                    target_map = {initiator.upper(): target_ports
                                  for initiator in connector['wwpns']}
                    ret_info['data']['initiator_target_map'] = target_map
                    return ret_info
            return ret_info

    def create_group(self, ctxt, group):
        return {'status': fields.GroupStatus.AVAILABLE}

    def delete_group(self, ctxt, group, luns):
        volumes_model_update = []
        model_update = {'status': fields.GroupStatus.DELETED}
        if luns:
            try:
                self.delete_lun(luns)
            except restclient.APIException:
                model_update['status'] = fields.GroupStatus.ERROR_DELETING
                msg = _LE("Failed to delete the volumes in group %(group)s")
                LOG.exception(msg, {'group': group.id})

            for lun in luns:
                volumes_model_update.append({
                    'id': lun.os_id,
                    'status': model_update['status']
                })
        return model_update, volumes_model_update

    def update_group(self, ctxt, group, add_volumes, remove_volumes):
        return None, None, None

    def _delete_lun(self, lun_ids_str):
        self._client.send('DELETE', '/volumes',
                          params={'ids': lun_ids_str})

    def delete_lun_by_id(self, lun_id):
        self._client.send('DELETE', '/volumes/%s' % lun_id)

    def _get_version(self):
        return self._client.fetchone('GET', '')

    @proxy.logger
    def _create_lun(self, volData):
        return self._client.fetchid('POST', '/volumes', volData)

    def _get_pools(self, pools_str):
        return [self._client.fetchone('GET', '/pools/%s' % pid,
                fields=['id', 'name', 'node', 'stgtype', 'cap', 'capavail'])
                for pid in pools_str]

    def start_flashcopy(self, vol_pairs, freeze=False):
        options = [
            "permit_space_efficient_target",
            "fail_space_efficient_target_out_of_space"
        ]
        if freeze:
            options.append("freeze_consistency")
        self._client.send('POST', '/cs/flashcopies', {
            "volume_pairs": vol_pairs,
            "options": options
        })

    def get_pprc_paths(self, specific_lss=None):
        if specific_lss:
            lss_range = {
                'source_lss_id_from': specific_lss,
                'source_lss_id_to': specific_lss
            }
        else:
            # get all of PPRC paths between source DS8K and target DS8K.
            lss_range = {
                'source_lss_id_from': '00',
                'source_lss_id_to': 'FF'
            }

        return self._client.fetchall('GET', '/cs/pprcs/paths',
                                     params=lss_range)

    def get_flashcopy(self, vol_id):
        return self._client.fetchall('GET', '/volumes/%s/flashcopy' % vol_id)

    def delete_flashcopy(self, src_lun_id, tgt_lun_id):
        # no exception if failed
        self._client.statusok(
            'DELETE', '/cs/flashcopies/%s:%s' % (src_lun_id, tgt_lun_id))

    def _get_host_ports(self, host_wwpn_set):
        return self._client.fetchall(
            'GET', '/host_ports',
            params={
                'wwpns': ",".join(host_wwpn_set),
                'state': 'logged in,logged out'
            },
            fields=['host_id', 'wwpn'])

    def _create_host(self, host):
        return self._client.fetchone(
            'POST', '/hosts', {'name': host.name, 'hosttype': host.type})

    def _assign_host_port(self, host_id, ports):
        self._client.send('POST', '/host_ports/assign', {
            'host_id': host_id, 'host_port_wwpns': ports})

    def _map_volume_to_host(self, host_id, vol_id):
        return self._client.fetchid(
            'POST', '/hosts%5Bid=' + host_id + '%5D/mappings',
            {'volumes': [vol_id]})

    def _get_mappings(self, host_id):
        return self._client.fetchall(
            'GET', '/hosts%5Bid=' + host_id + '%5D/mappings')

    def _delete_mappings(self, host_id, lun_id):
        self._client.send(
            'DELETE', '/hosts%5Bid=' + host_id + '%5D/mappings/' + lun_id)

    def _delete_host_ports(self, ports):
        self._client.send(
            'DELETE', '/host_ports', params={'wwpns': ports})

    def _get_hosts(self):
        return self._client.fetchall(
            'GET', '/hosts', fields=['id', 'mappings_briefs'])

    def _delete_host(self, host_id):
        # delete the host will delete all of the ports belong to it
        self._client.send('DELETE', '/hosts%5Bid=' + host_id + '%5D')

    def _get_ioports(self):
        return self._client.fetchall('GET', '/ioports', fields=['wwpn'])

    def unfreeze_lss(self, lss_ids):
        self._client.send(
            'POST', '/cs/flashcopies/unfreeze', {"lss_ids": lss_ids})

    def get_all_lss(self, fields):
        return self._client.fetchall('GET', '/lss', fields=fields)

    def lun_exists(self, lun_id):
        return self._client.statusok('GET', '/volumes/%s' % lun_id)

    def get_lun(self, lun_id):
        return self._client.fetchone('GET', '/volumes/%s' % lun_id)

    def change_lun(self, lun_id, param):
        self._client.send('PUT', '/volumes/%s' % lun_id, param)

    def get_physical_links(self, target_id):
        return self._client.fetchall(
            'GET', '/cs/pprcs/physical_links',
            params={
                'target_system_wwnn': target_id,
                'source_lss_id': 00,
                'target_lss_id': 00
            })

    def get_systems(self):
        return self._client.fetchone(
            'GET', '/systems', fields=['id', 'wwnn', 'release'])

    def get_lun_number_in_lss(self, lss_id):
        return int(self._client.fetchone(
            'GET', '/lss/%s' % lss_id,
            fields=['configvols'])['configvols'])

    def create_pprc_path(self, pathData):
        self._client.send('POST', '/cs/pprcs/paths', pathData)

    def get_pprc_path(self, path_id):
        return self._client.fetchone(
            'GET', '/cs/pprcs/paths/%s' % path_id,
            fields=['port_pairs'])

    def delete_pprc_path(self, path_id):
        self._client.send('DELETE', '/cs/pprcs/paths/%s' % path_id)

    def create_pprc_pair(self, pairData):
        self._client.send('POST', '/cs/pprcs', pairData)

    def delete_pprc_pair_by_pair_id(self, pids):
        self._client.statusok('DELETE', '/cs/pprcs', params=pids)

    def do_failback(self, pairData):
        self._client.send('POST', '/cs/pprcs/resume', pairData)

    def get_pprc_pairs(self, min_vol_id, max_vol_id):
        return self._client.fetchall(
            'GET', '/cs/pprcs',
            params={
                'volume_id_from': min_vol_id,
                'volume_id_to': max_vol_id
            })

    def delete_pprc_pair(self, vol_id):
        # check pprc pairs exist or not.
        if not self.get_pprc_pairs(vol_id, vol_id):
            return None
        # don't use pprc pair ID to delete it, because it may have
        # communication issues.
        pairData = {
            'volume_full_ids': [{
                'volume_id': vol_id,
                'system_id': self.backend['storage_unit']
            }],
            'options': ['unconditional', 'issue_source']
        }
        self._client.send('POST', '/cs/pprcs/delete', pairData)


class DS8KReplicationSourceHelper(DS8KCommonHelper):
    """Manage source storage for replication."""

    @proxy.logger
    def find_pool_and_lss(self, excluded_lss=None):
        for pool_id, pool in self._storage_pools.items():
            lss = self._find_lss_for_type_replication(pool['node'],
                                                      excluded_lss)
            if lss:
                return pool_id, lss
        msg = _("All LSS/LCU IDs for configured pools are exhausted.")
        raise restclient.LssIDExhaustError(message=msg)

    @proxy.logger
    def _find_lss_for_type_replication(self, node, excluded_lss):
        # prefer to choose the non-existing one firstly
        fileds = ['id', 'type', 'addrgrp', 'group', 'configvols']
        existing_lss = self.get_all_lss(fileds)
        LOG.info(_LI("existing LSS IDs are %s"),
                 ','.join([lss['id'] for lss in existing_lss]))
        lss_id = self._find_from_unexisting_lss(node, existing_lss)
        if not lss_id:
            if excluded_lss:
                existing_lss = [lss for lss in existing_lss
                                if lss['id'] not in excluded_lss]
            lss_id = self._find_from_existing_lss(node, existing_lss)
        return lss_id


class DS8KReplicationTargetHelper(DS8KReplicationSourceHelper):
    """Manage target storage for replication."""

    def setup(self):
        self._create_client()
        self._get_storage_information()
        self._get_replication_information()
        self._check_host_type()
        self.backend['pools_str'] = self._get_value(
            'san_clustername').replace('_', ',')
        self._verify_version()
        self._verify_pools()

    def _get_replication_information(self):
        port_pairs = []
        pairs = self._get_value('port_pairs')
        if pairs:
            for pair in pairs.replace(' ', '').upper().split(';'):
                pair = pair.split('-')
                port_pair = {
                    'source_port_id': pair[0],
                    'target_port_id': pair[1]
                }
                port_pairs.append(port_pair)
        self.backend['port_pairs'] = port_pairs
        self.backend['id'] = self._get_value('backend_id')

    def create_lun(self, lun):
        volData = {
            'cap': self._gb2b(lun.size),
            'captype': 'bytes',
            'stgtype': 'fb',
            'tp': 'ese' if lun.type_thin else 'none'
        }
        lun.data_type = lun.data_type if lun.data_type else 'FB 512'
        if lun.type_os400:
            volData['os400'] = lun.type_os400

        volData['name'] = lun.replica_ds_name
        volData['pool'], volData['lss'] = lun.lss_pair['target']
        volID = self._create_lun(volData)
        lun.replication_driver_data.update(
            {self.backend['id']: {'vol_hex_id': volID}})
        return lun

    def delete_pprc_pair(self, vol_id):
        if not self.get_pprc_pairs(vol_id, vol_id):
            return None
        pairData = {
            'volume_full_ids': [{
                'volume_id': vol_id,
                'system_id': self.backend['storage_unit']
            }],
            'options': ['unconditional', 'issue_target']
        }
        self._client.send('POST', '/cs/pprcs/delete', pairData)


class DS8KECKDHelper(DS8KCommonHelper):
    """Manage ECKD volume."""

    # if use new REST API, please update the version below
    VALID_REST_VERSION_5_7_MIN = '5.7.51.1068'
    VALID_REST_VERSION_5_8_MIN = '5.8.20.1059'
    MIN_VALID_STORAGE_VERSION = '8.1'
    INVALID_STORAGE_VERSION = '8.0.1'

    @staticmethod
    def _gb2cyl(gb):
        # now only support 3390, no 3380 or 3390-A
        cyl = int(math.ceil(gb * 1263.28))
        if cyl > 65520:
            msg = (_("For 3390 volume, capacity can be in the range "
                     "1-65520(849KiB to 55.68GiB) cylinders, now it "
                     "is %(gb)d GiB, equals to %(cyl)d cylinders.") %
                   {'gb': gb, 'cyl': cyl})
            raise exception.VolumeDriverException(data=msg)
        return cyl

    @staticmethod
    def _cyl2b(cyl):
        return cyl * 849960

    def _get_cula(self, lcu):
        return self.backend['device_mapping'][lcu]

    def disable_thin_provision(self):
        self._disable_thin_provision = True

    def setup(self):
        self._create_client()
        self._get_storage_information()
        self._check_host_type()
        self.backend['pools_str'] = self._get_value('san_clustername')
        ssid_prefix = self._get_value('ds8k_ssid_prefix')
        self.backend['ssid_prefix'] = ssid_prefix if ssid_prefix else 'FF'
        self.backend['device_mapping'] = self._check_and_verify_lcus()
        self._verify_version()
        self._verify_pools()

    def _verify_version(self):
        if self.backend['storage_version'] == self.INVALID_STORAGE_VERSION:
            raise exception.VolumeDriverException(
                message=(_("%s does not support bulk deletion of volumes, "
                           "if you want to use this version of driver, "
                           "please upgrade the CCL.")
                         % self.INVALID_STORAGE_VERSION))
        # DS8K supports ECKD ESE volume from 8.1
        if (dist_version.LooseVersion(self.backend['storage_version']) <
           dist_version.LooseVersion(self.MIN_VALID_STORAGE_VERSION)):
            self._disable_thin_provision = True

        if (('5.7' in self.backend['rest_version'] and
           dist_version.LooseVersion(self.backend['rest_version']) <
           dist_version.LooseVersion(self.VALID_REST_VERSION_5_7_MIN)) or
           ('5.8' in self.backend['rest_version'] and
           dist_version.LooseVersion(self.backend['rest_version']) <
           dist_version.LooseVersion(self.VALID_REST_VERSION_5_8_MIN))):
            raise exception.VolumeDriverException(
                message=(_("REST version %(invalid)s is lower than "
                           "%(valid)s, please upgrade it in DS8K.")
                         % {'invalid': self.backend['rest_version'],
                            'valid': (self.VALID_REST_VERSION_5_7_MIN if '5.7'
                                      in self.backend['rest_version'] else
                                      self.VALID_REST_VERSION_5_8_MIN)}))

    @proxy.logger
    def _check_and_verify_lcus(self):
        map_str = self._get_value('ds8k_devadd_unitadd_mapping')
        if not map_str:
            err = _('Param [ds8k_devadd_unitadd_mapping] is not '
                    'provided, please provide the mapping between '
                    'IODevice address and unit address.')
            raise exception.InvalidParameterValue(err=err)

        # verify the LCU
        mappings = map_str.replace(' ', '').upper().split(';')
        pairs = [m.split('-') for m in mappings]
        dev_mapping = {p[1]: int(p[0], 16) for p in pairs}
        for lcu in dev_mapping.keys():
            if int(lcu, 16) > 255:
                err = (_('LCU %s in param [ds8k_devadd_unitadd_mapping]'
                         'is invalid, it should be within 00-FF.') % lcu)
                raise exception.InvalidParameterValue(err=err)

        # verify address group
        all_lss = self.get_all_lss(['id', 'type'])
        fb_lss = set(lss['id'] for lss in all_lss if lss['type'] == 'fb')
        fb_addrgrp = set((int(lss, 16) // 16) for lss in fb_lss)
        ckd_addrgrp = set((int(lcu, 16) // 16) for lcu in dev_mapping.keys())
        intersection = ckd_addrgrp & fb_addrgrp
        if intersection:
            msg = (_('Invaild LCUs which first digit is %s, they are'
                     'for fb volume.') % ', '.join(intersection))
            raise exception.VolumeDriverException(data=msg)

        # create LCU that doesn't exist
        ckd_lss = set(lss['id'] for lss in all_lss if lss['type'] == 'ckd')
        unexisting_lcu = set(dev_mapping.keys()) - ckd_lss
        if unexisting_lcu:
            msg = _LI('LCUs %s do not exist in DS8K, they will be created.')
            LOG.info(msg, ','.join(unexisting_lcu))
            for lcu in unexisting_lcu:
                try:
                    self._create_lcu(self.backend['ssid_prefix'], lcu)
                except restclient.APIException as e:
                    msg = (_('can not create lcu %(lcu)s, Exception= '
                             '%(e)s') % {'lcu': lcu, 'e': six.text_type(e)})
                    raise exception.VolumeDriverException(data=msg)
        return dev_mapping

    def _format_pools(self, pools):
        return ((p['id'], {
            'name': p['name'],
            'node': int(p['node']),
            'stgtype': p['stgtype'],
            'cap': self._cyl2b(int(p['cap'])),
            'capavail': self._cyl2b(int(p['capavail']))
        }) for p in pools)

    @proxy.logger
    def find_pool_and_lss(self, excluded_lss=None):
        return self.find_biggest_pool_and_lss(excluded_lss)

    @proxy.logger
    def _find_lss(self, node, excluded_lcu):
        # all LCUs have existed, not like LSS
        all_lss = self.get_all_lss(['id', 'type', 'group', 'configvols'])
        existing_lcu = [lss for lss in all_lss if lss['type'] == 'ckd']
        candidate_lcu = [lcu for lcu in existing_lcu if (
                         lcu['id'] in self.backend['device_mapping'].keys() and
                         lcu['id'] not in excluded_lcu and
                         lcu['group'] == str(node))]
        if not candidate_lcu:
            return None

        # perfer to use LCU that is not in PPRC path first.
        lcu_pprc = self.get_lss_in_pprc_paths() & set(
            self.backend['device_mapping'].keys())
        if lcu_pprc:
            lcu_non_pprc = [
                lcu for lcu in candidate_lcu if lcu['id'] not in lcu_pprc]
            if lcu_non_pprc:
                candidate_lcu = lcu_non_pprc

        # get the lcu which has max number of empty slots
        emptiest_lcu = sorted(
            candidate_lcu, key=lambda i: int(i['configvols']))[0]
        if int(emptiest_lcu['configvols']) == LSS_VOL_SLOTS:
            return None

        return emptiest_lcu['id']

    def _create_lcu(self, ssid_prefix, lcu):
        self._client.send('POST', '/lss', {
            'id': lcu,
            'type': 'ckd',
            'sub_system_identifier': ssid_prefix + lcu
        })

    def create_lun(self, lun):
        volData = {
            'cap': self._gb2cyl(lun.size),
            'captype': 'cyl',
            'stgtype': 'ckd',
            'tp': 'ese' if lun.type_thin else 'none'
        }
        lun.data_type = '3390'
        volData['name'] = lun.ds_name
        volData['pool'], volData['lss'] = lun.lss_pair['source']
        lun.ds_id = self._create_lun(volData)
        return lun

    def initialize_connection(self, vol_id, connector, **kwargs):
        return {
            'driver_volume_type': 'fibre_channel_eckd',
            'data': {
                'target_discovered': True,
                'cula': self._get_cula(vol_id[0:2]),
                'unit_address': int(vol_id[2:4], 16),
                'discard': False
            }
        }

    def terminate_connection(self, vol_id, connector, force, **kwargs):
        return None


class DS8KReplicationTargetECKDHelper(DS8KECKDHelper,
                                      DS8KReplicationTargetHelper):
    """Manage ECKD volume in replication target."""

    def setup(self):
        self._create_client()
        self._get_storage_information()
        self._get_replication_information()
        self._check_host_type()
        self.backend['pools_str'] = self._get_value(
            'san_clustername').replace('_', ',')
        ssid_prefix = self._get_value('ds8k_ssid_prefix')
        self.backend['ssid_prefix'] = ssid_prefix if ssid_prefix else 'FF'
        self.backend['device_mapping'] = self._check_and_verify_lcus()
        self._verify_version()
        self._verify_pools()

    def create_lun(self, lun):
        volData = {
            'cap': self._gb2cyl(lun.size),
            'captype': 'cyl',
            'stgtype': 'ckd',
            'tp': 'ese' if lun.type_thin else 'none'
        }
        lun.data_type = '3390'

        volData['name'] = lun.replica_ds_name
        volData['pool'], volData['lss'] = lun.lss_pair['target']
        volID = self._create_lun(volData)
        lun.replication_driver_data.update(
            {self.backend['id']: {'vol_hex_id': volID}})
        return lun
