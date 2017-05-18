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
import copy
import distutils.version as dist_version  # pylint: disable=E0611
import eventlet
import math
import os
import six
import string

from oslo_log import log as logging

from cinder import coordination
from cinder import exception
from cinder.i18n import _
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

    OPTIONAL_PARAMS = ['ds8k_host_type', 'lss_range_for_cg']
    # if use new REST API, please update the version below
    VALID_REST_VERSION_5_7_MIN = '5.7.51.1047'
    INVALID_STORAGE_VERSION = '8.0.1'
    REST_VERSION_5_7_MIN_PPRC_CG = '5.7.51.1068'
    REST_VERSION_5_8_MIN_PPRC_CG = '5.8.20.1059'

    def __init__(self, conf, HTTPConnectorObject=None):
        self.conf = conf
        self._connector_obj = HTTPConnectorObject
        self._storage_pools = None
        self._disable_thin_provision = False
        self._connection_type = self._get_value('connection_type')
        self._existing_lss = None
        self.backend = {}
        self.setup()

    @staticmethod
    def _gb2b(gb):
        return gb * (2 ** 30)

    def _get_value(self, key):
        if getattr(self.conf, 'safe_get', 'get') == 'get':
            value = self.conf.get(key)
        else:
            value = self.conf.safe_get(key)
        if not value and key not in self.OPTIONAL_PARAMS:
            raise exception.InvalidParameterValue(
                err=(_('Param [%s] should be provided.') % key))
        return value

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
        self._storage_pools = self.get_pools()
        self.verify_pools(self._storage_pools)
        self.backend['lss_ids_for_cg'] = self._get_lss_ids_for_cg()
        self._verify_rest_version()

    def update_client(self):
        self._client.close()
        self._create_client()

    def _get_certificate(self, host):
        cert_file = strings.CERTIFICATES_PATH + host + '.pem'
        LOG.debug("certificate file for DS8K %(host)s: %(cert)s",
                  {'host': host, 'cert': cert_file})
        # Use the certificate if it exists, otherwise use the System CA Bundle
        if os.path.exists(cert_file):
            return cert_file
        else:
            LOG.debug("certificate file not found.")
            return True

    def _create_client(self):
        san_ip = self._get_value('san_ip')
        try:
            clear_pass = cryptish.decrypt(self._get_value('san_password'))
        except TypeError:
            raise exception.InvalidParameterValue(
                err=_('Param [san_password] is invalid.'))
        verify = self._get_certificate(san_ip)
        try:
            self._client = restclient.RESTScheduler(
                san_ip,
                self._get_value('san_login'),
                clear_pass,
                self._connector_obj,
                verify)
        except restclient.TimeoutException:
            raise restclient.APIException(
                data=(_("Can't connect to %(host)s") % {'host': san_ip}))
        self.backend['rest_version'] = self._get_version()['bundle_version']
        LOG.info("Connection to DS8K storage system %(host)s has been "
                 "established successfully, the version of REST is %(rest)s.",
                 {'host': self._get_value('san_ip'),
                  'rest': self.backend['rest_version']})

    def _get_storage_information(self):
        storage_info = self.get_systems()
        self.backend['storage_unit'] = storage_info['id']
        self.backend['storage_wwnn'] = storage_info['wwnn']
        self.backend['storage_version'] = storage_info['release']

    def _get_lss_ids_for_cg(self):
        lss_ids_for_cg = set()
        lss_range = self._get_value('lss_range_for_cg')
        if lss_range:
            lss_range = lss_range.replace(' ', '').split('-')
            if len(lss_range) == 1:
                begin = int(lss_range[0], 16)
                end = begin
            else:
                begin = int(lss_range[0], 16)
                end = int(lss_range[1], 16)
            if begin > 0xFF or end > 0xFF or begin > end:
                raise exception.InvalidParameterValue(
                    err=_('Param [lss_range_for_cg] is invalid, it '
                          'should be within 00-FF.'))
            lss_ids_for_cg = set(
                ('%02x' % i).upper() for i in range(begin, end + 1))
        return lss_ids_for_cg

    def _check_host_type(self):
        ds8k_host_type = self._get_value('ds8k_host_type')
        if (ds8k_host_type and
           (ds8k_host_type not in VALID_HOST_TYPES)):
            msg = (_("Param [ds8k_host_type] must be one of: %(values)s.")
                   % {'values': VALID_HOST_TYPES[1:-1]})
            LOG.error(msg)
            raise exception.InvalidParameterValue(err=msg)
        self.backend['host_type_override'] = (
            None if ds8k_host_type == 'auto' else ds8k_host_type)

    def _verify_rest_version(self):
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

    def verify_rest_version_for_pprc_cg(self):
        if '8.1' in self.backend['rest_version']:
            raise exception.VolumeDriverException(
                message=_("REST for DS8K 8.1 does not support PPRC "
                          "consistency group, please upgrade the CCL."))
        valid_rest_version = None
        if ('5.7' in self.backend['rest_version'] and
           dist_version.LooseVersion(self.backend['rest_version']) <
           dist_version.LooseVersion(self.REST_VERSION_5_7_MIN_PPRC_CG)):
            valid_rest_version = self.REST_VERSION_5_7_MIN_PPRC_CG
        elif ('5.8' in self.backend['rest_version'] and
              dist_version.LooseVersion(self.backend['rest_version']) <
              dist_version.LooseVersion(self.REST_VERSION_5_8_MIN_PPRC_CG)):
            valid_rest_version = self.REST_VERSION_5_8_MIN_PPRC_CG

        if valid_rest_version:
            raise exception.VolumeDriverException(
                message=(_("REST version %(invalid)s is lower than "
                           "%(valid)s, please upgrade it in DS8K.")
                         % {'invalid': self.backend['rest_version'],
                            'valid': valid_rest_version}))

    def verify_pools(self, storage_pools):
        if self._connection_type == storage.XIV_CONNECTION_TYPE_FC:
            ptype = 'fb'
        elif self._connection_type == storage.XIV_CONNECTION_TYPE_FC_ECKD:
            ptype = 'ckd'
        else:
            raise exception.InvalidParameterValue(
                err=_('Param [connection_type] is invalid.'))
        for pid, pool in storage_pools.items():
            if pool['stgtype'] != ptype:
                LOG.error('The stgtype of pool %(pool)s is %(ptype)s.',
                          {'pool': pid, 'ptype': pool['stgtype']})
                raise exception.InvalidParameterValue(
                    err='Param [san_clustername] is invalid.')

    @proxy.logger
    def get_pools(self, specific_pools=None):
        if specific_pools:
            pools_str = specific_pools.replace(' ', '').upper().split(',')
        else:
            pools_str = self.backend['pools_str'].replace(
                ' ', '').upper().split(',')
        pools = self._get_pools(pools_str)
        unsorted_pools = self._format_pools(pools)
        storage_pools = collections.OrderedDict(sorted(
            unsorted_pools, key=lambda i: i[1]['capavail'], reverse=True))
        return storage_pools

    @proxy.logger
    def update_storage_pools(self, storage_pools):
        self._storage_pools = storage_pools

    def _format_pools(self, pools):
        return ((p['id'], {
            'name': p['name'],
            'node': int(p['node']),
            'stgtype': p['stgtype'],
            'cap': int(p['cap']),
            'capavail': int(p['capavail'])
        }) for p in pools)

    def verify_lss_ids(self, specified_lss_ids):
        if not specified_lss_ids:
            return None
        lss_ids = specified_lss_ids.upper().replace(' ', '').split(',')
        # verify LSS IDs.
        for lss_id in lss_ids:
            if int(lss_id, 16) > 255:
                raise exception.InvalidParameterValue(
                    _('LSS %s should be within 00-FF.') % lss_id)
        # verify address group
        self._existing_lss = self.get_all_lss()
        ckd_addrgrps = set(int(lss['id'], 16) // 16 for lss in
                           self._existing_lss if lss['type'] == 'ckd')
        fb_addrgrps = set((int(lss, 16) // 16) for lss in lss_ids)
        intersection = ckd_addrgrps & fb_addrgrps
        if intersection:
            raise exception.VolumeDriverException(
                message=_('LSSes in the address group %s are reserved '
                          'for CKD volumes') % list(intersection))
        # verify whether LSSs specified have been reserved for
        # consistency group or not.
        if self.backend['lss_ids_for_cg']:
            for lss_id in lss_ids:
                if lss_id in self.backend['lss_ids_for_cg']:
                    raise exception.InvalidParameterValue(
                        _('LSS %s has been reserved for CG.') % lss_id)
        return lss_ids

    @proxy.logger
    def find_pool_lss_pair(self, pool, find_new_pid, excluded_lss):
        if pool:
            node = int(pool[1:], 16) % 2
            lss = self._find_lss(node, excluded_lss)
            if lss:
                return (pool, lss)
            else:
                if not find_new_pid:
                    raise restclient.LssIDExhaustError(
                        message=_('All LSS/LCU IDs for configured pools '
                                  'on storage are exhausted.'))
        # find new pool id and lss for lun
        return self.find_biggest_pool_and_lss(excluded_lss)

    @proxy.logger
    def find_biggest_pool_and_lss(self, excluded_lss, specified_pool_lss=None):
        if specified_pool_lss:
            # pool and lss should be verified every time user create volume or
            # snapshot, because they can be changed in extra-sepcs at any time.
            specified_pool_ids, specified_lss_ids = specified_pool_lss
            storage_pools = self.get_pools(specified_pool_ids)
            self.verify_pools(storage_pools)
            storage_lss = self.verify_lss_ids(specified_lss_ids)
        else:
            storage_pools, storage_lss = self._storage_pools, None
        # pools are ordered by capacity
        for pool_id, pool in storage_pools.items():
            lss = self._find_lss(pool['node'], excluded_lss, storage_lss)
            if lss:
                return pool_id, lss
        raise restclient.LssIDExhaustError(
            message=_("All LSS/LCU IDs for configured pools are exhausted."))

    @proxy.logger
    def _find_lss(self, node, excluded_lss, specified_lss_ids=None):
        if specified_lss_ids:
            existing_lss = self._existing_lss
        else:
            existing_lss = self.get_all_lss()
        LOG.info("Existing LSS IDs are: %s.",
                 ','.join([lss['id'] for lss in existing_lss]))
        saved_existing_lss = copy.copy(existing_lss)

        # exclude LSSs that are full.
        existing_lss = [lss for lss in existing_lss
                        if lss['id'] not in excluded_lss]
        if not existing_lss:
            LOG.info("All LSSs are full.")
            return None

        # user specify LSSs in extra-specs.
        if specified_lss_ids:
            specified_lss_ids = [lss for lss in specified_lss_ids
                                 if lss not in excluded_lss]
            if specified_lss_ids:
                existing_lss = [lss for lss in existing_lss
                                if lss['id'] in specified_lss_ids]
                nonexistent_lss_ids = (set(specified_lss_ids) -
                                       set(lss['id'] for lss in existing_lss))
                lss = None
                for lss_id in nonexistent_lss_ids:
                    if int(lss_id, 16) % 2 == node:
                        lss = lss_id
                        break
                if not lss:
                    lss = self._find_from_existing_lss(
                        node, existing_lss, True)
            else:
                LOG.info("All appropriate LSSs specified are full.")
                return None
        else:
            # exclude LSSs that reserved for CG.
            if self.backend['lss_ids_for_cg']:
                existing_lss_cg, nonexistent_lss_cg = (
                    self._classify_lss_for_cg(existing_lss))
                existing_lss = [lss for lss in existing_lss
                                if lss['id'] not in existing_lss_cg]
            else:
                existing_lss_cg = set()
                nonexistent_lss_cg = set()
            lss = self._find_from_existing_lss(node, existing_lss)
            if not lss:
                lss = self._find_from_nonexistent_lss(node, saved_existing_lss,
                                                      nonexistent_lss_cg)
        return lss

    def _classify_lss_for_cg(self, existing_lss):
        existing_lss_ids = set(lss['id'] for lss in existing_lss)
        existing_lss_cg = existing_lss_ids & self.backend['lss_ids_for_cg']
        nonexistent_lss_cg = self.backend['lss_ids_for_cg'] - existing_lss_cg
        return existing_lss_cg, nonexistent_lss_cg

    def _find_from_existing_lss(self, node, existing_lss, ignore_pprc=False):
        if not ignore_pprc:
            # exclude LSSs that are used by PPRC paths.
            lss_in_pprc = self.get_lss_in_pprc_paths()
            if lss_in_pprc:
                existing_lss = [lss for lss in existing_lss
                                if lss['id'] not in lss_in_pprc]
        # exclude wrong type of LSSs and those that are not in expected node.
        existing_lss = [lss for lss in existing_lss if lss['type'] == 'fb'
                        and int(lss['group']) == node]
        lss_id = None
        if existing_lss:
            # look for the emptiest lss from existing lss
            lss = sorted(existing_lss, key=lambda k: int(k['configvols']))[0]
            if int(lss['configvols']) < LSS_VOL_SLOTS:
                lss_id = lss['id']
                LOG.info('_find_from_existing_lss: choose %(lss)s. '
                         'now it has %(num)s volumes.',
                         {'lss': lss_id, 'num': lss['configvols']})
        return lss_id

    def _find_from_nonexistent_lss(self, node, existing_lss, lss_cg=None):
        ckd_addrgrps = set(int(lss['id'], 16) // 16 for lss in existing_lss if
                           lss['type'] == 'ckd' and int(lss['group']) == node)
        full_lss = set(int(lss['id'], 16) for lss in existing_lss if
                       lss['type'] == 'fb' and int(lss['group']) == node)
        cg_lss = set(int(lss, 16) for lss in lss_cg) if lss_cg else set()
        # look for an available lss from nonexistent lss
        lss_id = None
        for lss in range(node, LSS_SLOTS, 2):
            addrgrp = lss // 16
            if (addrgrp not in ckd_addrgrps and
               lss not in full_lss and
               lss not in cg_lss):
                lss_id = ("%02x" % lss).upper()
                break
        LOG.info('_find_from_unexisting_lss: choose %s.', lss_id)
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
        volData['pool'], volData['lss'] = lun.pool_lss_pair['source']
        lun.ds_id = self._create_lun(volData)
        return lun

    def delete_lun(self, luns):
        lun_ids = []
        luns = [luns] if not isinstance(luns, list) else luns
        for lun in luns:
            if lun.ds_id is None:
                # create_lun must have failed and not returned the id
                LOG.error("delete_lun: volume id is None.")
                continue
            if not self.lun_exists(lun.ds_id):
                LOG.error("delete_lun: volume %s not found.", lun.ds_id)
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
            LOG.info("Deleting volumes: %s.", lun_ids_str)
            self._delete_lun(lun_ids_str)

    def get_lss_in_pprc_paths(self):
        # TODO(Jiamin): when the REST API that get the licenses installed
        # in DS8K is ready, this function should be improved.
        try:
            paths = self.get_pprc_paths()
        except restclient.APIException:
            paths = []
            LOG.exception("Can not get the LSS")
        lss_ids = set(p['source_lss_id'] for p in paths)
        LOG.info('LSS in PPRC paths are: %s.', ','.join(lss_ids))
        return lss_ids

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
                            raise restclient.APIException(
                                data=(_('Flashcopy ended up in bad state %s. '
                                        'Rolling back.') % fcs[0]['state']))
                if fc_state.count(False) == 0:
                    break
            finished = True
        finally:
            if not finished:
                for src_lun, tgt_lun in zip(src_luns, tgt_luns):
                    self.delete_flashcopy(src_lun.ds_id, tgt_lun.ds_id)
        return finished

    def wait_pprc_copy_finished(self, vol_ids, state, delete=True):
        LOG.info("Wait for PPRC pair to enter into state %s", state)
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
                        raise restclient.APIException(
                            data=(_('Metro Mirror pair %(id)s enters into '
                                    'state %(state)s. ')
                                  % {'id': p['id'], 'state': p['state']}))
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

    @coordination.synchronized('ibm-ds8k-{connector[host]}')
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
        LOG.debug("initialize_connection: defined_hosts: %(defined)s, "
                  "unknown_ports: %(unknown)s, unconfigured_ports: "
                  "%(unconfigured)s.", {"defined": defined_hosts,
                                        "unknown": unknown_ports,
                                        "unconfigured": unconfigured_ports})
        # Create host if it is not defined
        if not defined_hosts:
            host_id = self._create_host(host)['id']
        elif len(defined_hosts) == 1:
            host_id = defined_hosts.pop()
        else:
            raise restclient.APIException(
                message='More than one host defined for requested ports.')
        LOG.info('Volume will be attached to host %s.', host_id)

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

    @coordination.synchronized('ibm-ds8k-{connector[host]}')
    def terminate_connection(self, vol_id, connector, force, **kwargs):
        host = self._get_host(connector)
        host_wwpn_set = set(wwpn.upper() for wwpn in connector['wwpns'])
        host_ports = self._get_host_ports(host_wwpn_set)
        defined_hosts = set(
            hp['host_id'] for hp in host_ports if hp['host_id'])
        delete_ports = set(
            hp['wwpn'] for hp in host_ports if not hp['host_id'])
        LOG.debug("terminate_connection: host_ports: %(host)s, "
                  "defined_hosts: %(defined)s, delete_ports: %(delete)s.",
                  {"host": host_ports,
                   "defined": defined_hosts,
                   "delete": delete_ports})

        if not defined_hosts:
            LOG.info('Could not find host.')
            return None
        elif len(defined_hosts) > 1:
            raise restclient.APIException(_('More than one host found.'))
        else:
            host_id = defined_hosts.pop()
            mappings = self._get_mappings(host_id)
            lun_ids = [
                m['lunid'] for m in mappings if m['volume']['id'] == vol_id]
            LOG.info('Volumes attached to host %(host)s are %(vols)s.',
                     {'host': host_id, 'vols': ','.join(lun_ids)})
            for lun_id in lun_ids:
                self._delete_mappings(host_id, lun_id)
            if not lun_ids:
                LOG.warning("Volume %(vol)s is already not mapped to "
                            "host %(host)s.",
                            {'vol': vol_id, 'host': host.name})
            # if this host only has volumes that have been detached,
            # remove the host and its ports
            ret_info = {
                'driver_volume_type': 'fibre_channel',
                'data': {}
            }
            if len(mappings) == len(lun_ids):
                for port in delete_ports:
                    self._delete_host_ports(port)
                self._delete_host(host_id)
                target_ports = [p['wwpn'] for p in self._get_ioports()]
                target_map = {initiator.upper(): target_ports
                              for initiator in connector['wwpns']}
                ret_info['data']['initiator_target_map'] = target_map
            return ret_info

    def create_group(self, group):
        return {'status': fields.GroupStatus.AVAILABLE}

    def delete_group(self, group, src_luns):
        volumes_model_update = []
        model_update = {'status': fields.GroupStatus.DELETED}
        if src_luns:
            try:
                self.delete_lun(src_luns)
            except restclient.APIException as e:
                model_update['status'] = fields.GroupStatus.ERROR_DELETING
                LOG.exception(
                    "Failed to delete the volumes in group %(group)s, "
                    "Exception = %(ex)s",
                    {'group': group.id, 'ex': e})

            for src_lun in src_luns:
                volumes_model_update.append({
                    'id': src_lun.os_id,
                    'status': model_update['status']
                })
        return model_update, volumes_model_update

    def delete_group_snapshot(self, group_snapshot, tgt_luns):
        snapshots_model_update = []
        model_update = {'status': fields.GroupSnapshotStatus.DELETED}
        if tgt_luns:
            try:
                self.delete_lun(tgt_luns)
            except restclient.APIException as e:
                model_update['status'] = (
                    fields.GroupSnapshotStatus.ERROR_DELETING)
                LOG.error("Failed to delete snapshots in group snapshot "
                          "%(gsnapshot)s, Exception = %(ex)s",
                          {'gsnapshot': group_snapshot.id, 'ex': e})
        for tgt_lun in tgt_luns:
            snapshots_model_update.append({
                'id': tgt_lun.os_id,
                'status': model_update['status']
            })
        return model_update, snapshots_model_update

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

    def _delete_host_ports(self, port):
        self._client.send('DELETE', '/host_ports/%s' % port)

    def _delete_host(self, host_id):
        # delete the host will delete all of the ports belong to it
        self._client.send('DELETE', '/hosts%5Bid=' + host_id + '%5D')

    def _get_ioports(self):
        return self._client.fetchall('GET', '/ioports', fields=['wwpn'])

    def unfreeze_lss(self, lss_ids):
        self._client.send(
            'POST', '/cs/flashcopies/unfreeze', {"lss_ids": lss_ids})

    def get_all_lss(self, fields=None):
        fields = (fields if fields else
                  ['id', 'type', 'group', 'configvols'])
        return self._client.fetchall('GET', '/lss', fields=fields)

    def lun_exists(self, lun_id):
        return self._client.statusok('GET', '/volumes/%s' % lun_id)

    def get_lun_pool(self, lun_id):
        return self._client.fetchone(
            'GET', '/volumes/%s' % lun_id, fields=['pool'])['pool']

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

    def create_pprc_pair(self, pair_data):
        self._client.send('POST', '/cs/pprcs', pair_data)

    def delete_pprc_pair_by_pair_id(self, pids):
        self._client.statusok('DELETE', '/cs/pprcs', params=pids)

    def do_failback(self, pair_data):
        self._client.send('POST', '/cs/pprcs/resume', pair_data)

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
        pair_data = {
            'volume_full_ids': [{
                'volume_id': vol_id,
                'system_id': self.backend['storage_unit']
            }],
            'options': ['unconditional', 'issue_source']
        }
        self._client.send('POST', '/cs/pprcs/delete', pair_data)

    def pause_pprc_pairs(self, pprc_pair_ids):
        pair_data = {'pprc_ids': pprc_pair_ids}
        self._client.send('POST', '/cs/pprcs/pause', pair_data)

    def resume_pprc_pairs(self, pprc_pair_ids):
        pair_data = {
            'pprc_ids': pprc_pair_ids,
            'type': 'metro_mirror',
            'options': ['permit_space_efficient_target',
                        'initial_copy_out_of_sync']
        }
        self._client.send('POST', '/cs/pprcs/resume', pair_data)


class DS8KReplicationSourceHelper(DS8KCommonHelper):
    """Manage source storage for replication."""

    @proxy.logger
    def find_pool_and_lss(self, excluded_lss=None):
        for pool_id, pool in self._storage_pools.items():
            lss = self._find_lss_for_type_replication(pool['node'],
                                                      excluded_lss)
            if lss:
                return pool_id, lss
        raise restclient.LssIDExhaustError(
            message=_("All LSS/LCU IDs for configured pools are exhausted."))

    @proxy.logger
    def _find_lss_for_type_replication(self, node, excluded_lss):
        # prefer to choose non-existing one first.
        existing_lss = self.get_all_lss()
        LOG.info("existing LSS IDs are %s",
                 ','.join([lss['id'] for lss in existing_lss]))
        existing_lss_cg, nonexistent_lss_cg = (
            self._classify_lss_for_cg(existing_lss))
        lss_id = self._find_from_nonexistent_lss(node, existing_lss,
                                                 nonexistent_lss_cg)
        if not lss_id:
            if excluded_lss:
                existing_lss = [lss for lss in existing_lss
                                if lss['id'] not in excluded_lss]
            candidates = [lss for lss in existing_lss
                          if lss['id'] not in existing_lss_cg]
            lss_id = self._find_from_existing_lss(node, candidates)
        return lss_id


class DS8KReplicationTargetHelper(DS8KReplicationSourceHelper):
    """Manage target storage for replication."""

    OPTIONAL_PARAMS = ['ds8k_host_type', 'port_pairs', 'lss_range_for_cg']

    def setup(self):
        self._create_client()
        self._get_storage_information()
        self._get_replication_information()
        self._check_host_type()
        self.backend['lss_ids_for_cg'] = self._get_lss_ids_for_cg()
        self.backend['pools_str'] = self._get_value(
            'san_clustername').replace('_', ',')
        self._storage_pools = self.get_pools()
        self.verify_pools(self._storage_pools)
        self._verify_rest_version()

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
        volData['pool'], volData['lss'] = lun.pool_lss_pair['target']
        volID = self._create_lun(volData)
        lun.replication_driver_data.update(
            {self.backend['id']: {'vol_hex_id': volID}})
        return lun

    def delete_pprc_pair(self, vol_id):
        if not self.get_pprc_pairs(vol_id, vol_id):
            return None
        pair_data = {
            'volume_full_ids': [{
                'volume_id': vol_id,
                'system_id': self.backend['storage_unit']
            }],
            'options': ['unconditional', 'issue_target']
        }
        self._client.send('POST', '/cs/pprcs/delete', pair_data)


class DS8KECKDHelper(DS8KCommonHelper):
    """Manage ECKD volume."""

    OPTIONAL_PARAMS = ['ds8k_host_type', 'port_pairs', 'ds8k_ssid_prefix',
                       'lss_range_for_cg']
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
            raise exception.VolumeDriverException(
                message=(_("For 3390 volume, capacity can be in the range "
                           "1-65520(849KiB to 55.68GiB) cylinders, now it "
                           "is %(gb)d GiB, equals to %(cyl)d cylinders.")
                         % {'gb': gb, 'cyl': cyl}))
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
        self.backend['lss_ids_for_cg'] = self._get_lss_ids_for_cg()
        self.backend['pools_str'] = self._get_value('san_clustername')
        self._storage_pools = self.get_pools()
        self.verify_pools(self._storage_pools)
        ssid_prefix = self._get_value('ds8k_ssid_prefix')
        self.backend['ssid_prefix'] = ssid_prefix if ssid_prefix else 'FF'
        self.backend['device_mapping'] = self._get_device_mapping()
        self._verify_rest_version()

    def _verify_rest_version(self):
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
    def _get_device_mapping(self):
        map_str = self._get_value('ds8k_devadd_unitadd_mapping')
        mappings = map_str.replace(' ', '').upper().split(';')
        pairs = [m.split('-') for m in mappings]
        self.verify_lss_ids(','.join([p[1] for p in pairs]))
        return {p[1]: int(p[0], 16) for p in pairs}

    @proxy.logger
    def verify_lss_ids(self, specified_lcu_ids):
        if not specified_lcu_ids:
            return None
        lcu_ids = specified_lcu_ids.upper().replace(' ', '').split(',')
        # verify the LCU ID.
        for lcu in lcu_ids:
            if int(lcu, 16) > 255:
                raise exception.InvalidParameterValue(
                    err=_('LCU %s should be within 00-FF.') % lcu)

        # verify address group
        self._existing_lss = self.get_all_lss()
        fb_addrgrps = set(int(lss['id'], 16) // 16 for lss in
                          self._existing_lss if lss['type'] == 'fb')
        ckd_addrgrps = set((int(lcu, 16) // 16) for lcu in lcu_ids)
        intersection = ckd_addrgrps & fb_addrgrps
        if intersection:
            raise exception.VolumeDriverException(
                message=_('LCUs in the address group %s are reserved '
                          'for FB volumes') % list(intersection))

        # create LCU that doesn't exist
        nonexistent_lcu = set(lcu_ids) - set(
            lss['id'] for lss in self._existing_lss if lss['type'] == 'ckd')
        if nonexistent_lcu:
            LOG.info('LCUs %s do not exist in DS8K, they will be '
                     'created.', ','.join(nonexistent_lcu))
            for lcu in nonexistent_lcu:
                try:
                    self._create_lcu(self.backend['ssid_prefix'], lcu)
                except restclient.APIException as e:
                    raise exception.VolumeDriverException(
                        message=(_('Can not create lcu %(lcu)s, '
                                   'Exception = %(e)s.')
                                 % {'lcu': lcu, 'e': six.text_type(e)}))
        return lcu_ids

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
    def _find_lss(self, node, excluded_lcu, specified_lcu_ids=None):
        # all LCUs have existed, unlike LSS.
        if specified_lcu_ids:
            for lcu_id in specified_lcu_ids:
                if lcu_id not in self.backend['device_mapping'].keys():
                    raise exception.InvalidParameterValue(
                        err=_("LCU %s is not in parameter "
                              "ds8k_devadd_unitadd_mapping, "
                              "Please specify LCU in it, otherwise "
                              "driver can not attach volume.") % lcu_id)
            all_lss = self._existing_lss
        else:
            all_lss = self.get_all_lss()
        existing_lcu = [lcu for lcu in all_lss if
                        lcu['type'] == 'ckd' and
                        lcu['id'] in self.backend['device_mapping'].keys() and
                        lcu['group'] == six.text_type(node)]
        LOG.info("All appropriate LCUs are %s.",
                 ','.join([lcu['id'] for lcu in existing_lcu]))

        # exclude full LCUs.
        if excluded_lcu:
            existing_lcu = [lcu for lcu in existing_lcu if
                            lcu['id'] not in excluded_lcu]
            if not existing_lcu:
                LOG.info("All appropriate LCUs are full.")
                return None

        ignore_pprc = False
        if specified_lcu_ids:
            # user specify LCUs in extra-specs.
            existing_lcu = [lcu for lcu in existing_lcu
                            if lcu['id'] in specified_lcu_ids]
            ignore_pprc = True

        # exclude LCUs reserved for CG.
        existing_lcu = [lcu for lcu in existing_lcu if lcu['id']
                        not in self.backend['lss_ids_for_cg']]
        if not existing_lcu:
            LOG.info("All appropriate LCUs have been reserved for "
                     "for consistency group.")
            return None

        if not ignore_pprc:
            # prefer to use LCU that is not in PPRC path first.
            lcu_pprc = self.get_lss_in_pprc_paths() & set(
                self.backend['device_mapping'].keys())
            if lcu_pprc:
                lcu_non_pprc = [
                    lcu for lcu in existing_lcu if lcu['id'] not in lcu_pprc]
                if lcu_non_pprc:
                    existing_lcu = lcu_non_pprc

        # return LCU which has max number of empty slots.
        emptiest_lcu = sorted(
            existing_lcu, key=lambda i: int(i['configvols']))[0]
        if int(emptiest_lcu['configvols']) == LSS_VOL_SLOTS:
            return None
        else:
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
        volData['pool'], volData['lss'] = lun.pool_lss_pair['source']
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
        self.backend['lss_ids_for_cg'] = self._get_lss_ids_for_cg()
        self.backend['pools_str'] = self._get_value(
            'san_clustername').replace('_', ',')
        self._storage_pools = self.get_pools()
        self.verify_pools(self._storage_pools)
        ssid_prefix = self._get_value('ds8k_ssid_prefix')
        self.backend['ssid_prefix'] = ssid_prefix if ssid_prefix else 'FF'
        self.backend['device_mapping'] = self._get_device_mapping()
        self._verify_rest_version()

    def create_lun(self, lun):
        volData = {
            'cap': self._gb2cyl(lun.size),
            'captype': 'cyl',
            'stgtype': 'ckd',
            'tp': 'ese' if lun.type_thin else 'none'
        }
        lun.data_type = '3390'

        volData['name'] = lun.replica_ds_name
        volData['pool'], volData['lss'] = lun.pool_lss_pair['target']
        volID = self._create_lun(volData)
        lun.replication_driver_data.update(
            {self.backend['id']: {'vol_hex_id': volID}})
        return lun
