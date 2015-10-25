# Copyright (c) 2015 Huawei Technologies Co., Ltd.
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
#

import six

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _, _LI, _LW
from cinder.volume.drivers.huawei import constants
from cinder.volume.drivers.huawei import huawei_utils
from cinder.volume.drivers.huawei import rest_client

LOG = logging.getLogger(__name__)


class HuaweiHyperMetro(object):

    def __init__(self, client, rmt_client, configuration):
        self.client = client
        self.rmt_client = rmt_client
        self.configuration = configuration
        self.xml_file_path = self.configuration.cinder_huawei_conf_file

    def create_hypermetro(self, local_lun_id, lun_param):
        """Create hypermetro."""
        metro_devices = self.configuration.hypermetro_devices
        device_info = huawei_utils.get_remote_device_info(metro_devices)
        self.rmt_client = rest_client.RestClient(self.configuration)
        self.rmt_client.login_with_ip(device_info)

        try:
            # Get the remote pool info.
            config_pool = device_info['StoragePool']
            remote_pool = self.rmt_client.find_all_pools()
            pool = self.rmt_client.find_pool_info(config_pool,
                                                  remote_pool)
            # Create remote lun
            lun_param['PARENTID'] = pool['ID']
            remotelun_info = self.rmt_client.create_volume(lun_param)
            remote_lun_id = remotelun_info['ID']

            # Get hypermetro domain
            try:
                domain_name = device_info['domain_name']
                domain_id = self.rmt_client.get_hyper_domain_id(domain_name)
                self._wait_volume_ready(remote_lun_id)
                hypermetro = self._create_hypermetro_pair(domain_id,
                                                          local_lun_id,
                                                          remote_lun_id)

                return hypermetro['ID'], remote_lun_id
            except Exception as err:
                self.rmt_client.delete_lun(remote_lun_id)
                msg = _('Create hypermetro error. %s.') % err
                raise exception.VolumeBackendAPIException(data=msg)
        except exception.VolumeBackendAPIException:
            raise
        except Exception as err:
            msg = _("Create remote LUN error. %s.") % err
            LOG.exception(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        finally:
            self.rmt_client.logout()

    def delete_hypermetro(self, volume):
        """Delete hypermetro."""
        metadata = huawei_utils.get_volume_metadata(volume)
        metro_id = metadata['hypermetro_id']
        remote_lun_id = metadata['remote_lun_id']

        if metro_id:
            exst_flag = self.client.check_hypermetro_exist(metro_id)
            if exst_flag:
                metro_info = self.client.get_hypermetro_by_id(metro_id)
                metro_status = int(metro_info['data']['RUNNINGSTATUS'])

                LOG.debug("Hypermetro status is: %s.", metro_status)
                if constants.HYPERMETRO_RUNNSTATUS_STOP != metro_status:
                    self.client.stop_hypermetro(metro_id)

                # Delete hypermetro
                self.client.delete_hypermetro(metro_id)

        # Delete remote lun.
        if remote_lun_id:
            metro_devices = self.configuration.hypermetro_devices
            device_info = huawei_utils.get_remote_device_info(metro_devices)
            self.rmt_client = rest_client.RestClient(self.configuration)
            self.rmt_client.login_with_ip(device_info)

            try:
                if self.rmt_client.check_lun_exist(remote_lun_id):
                    self.rmt_client.delete_lun(remote_lun_id)
            except Exception as err:
                msg = _("Delete remote lun err. %s.") % err
                LOG.exception(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            finally:
                self.rmt_client.logout()

    def _create_hypermetro_pair(self, domain_id, lun_id, remote_lun_id):
        """Create a HyperMetroPair."""
        hcp_param = {"DOMAINID": domain_id,
                     "HCRESOURCETYPE": '1',
                     "ISFIRSTSYNC": False,
                     "LOCALOBJID": lun_id,
                     "RECONVERYPOLICY": '1',
                     "REMOTEOBJID": remote_lun_id,
                     "SPEED": '2'}

        return self.client.create_hypermetro(hcp_param)

    def connect_volume_fc(self, volume, connector):
        """Create map between a volume and a host for FC."""
        self.xml_file_path = self.configuration.cinder_huawei_conf_file
        metro_devices = self.configuration.hypermetro_devices
        device_info = huawei_utils.get_remote_device_info(metro_devices)
        self.rmt_client = rest_client.RestClient(self.configuration)
        self.rmt_client.login_with_ip(device_info)

        try:
            wwns = connector['wwpns']
            volume_name = huawei_utils.encode_name(volume['id'])

            LOG.info(_LI(
                'initialize_connection_fc, initiator: %(wwpns)s,'
                ' volume name: %(volume)s.'),
                {'wwpns': wwns,
                 'volume': volume_name})

            metadata = huawei_utils.get_volume_metadata(volume)
            lun_id = metadata['remote_lun_id']

            if lun_id is None:
                lun_id = self.rmt_client.get_volume_by_name(volume_name)
            if lun_id is None:
                msg = _("Can't get volume id. Volume name: %s.") % volume_name
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            host_name_before_hash = None
            host_name = connector['host']
            if host_name and (len(host_name) > constants.MAX_HOSTNAME_LENGTH):
                host_name_before_hash = host_name
                host_name = six.text_type(hash(host_name))

            # Create hostgroup if not exist.
            host_id = self.rmt_client.add_host_with_check(
                host_name, host_name_before_hash)

            online_wwns_in_host = (
                self.rmt_client.get_host_online_fc_initiators(host_id))
            online_free_wwns = self.rmt_client.get_online_free_wwns()
            for wwn in wwns:
                if (wwn not in online_wwns_in_host
                        and wwn not in online_free_wwns):
                    wwns_in_host = (
                        self.rmt_client.get_host_fc_initiators(host_id))
                    iqns_in_host = (
                        self.rmt_client.get_host_iscsi_initiators(host_id))
                    if not wwns_in_host and not iqns_in_host:
                        self.rmt_client.remove_host(host_id)

                    msg = _('Can not add FC port to host.')
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

            for wwn in wwns:
                if wwn in online_free_wwns:
                    self.rmt_client.add_fc_port_to_host(host_id, wwn)

            (tgt_port_wwns, init_targ_map) = (
                self.rmt_client.get_init_targ_map(wwns))

            # Add host into hostgroup.
            hostgroup_id = self.rmt_client.add_host_into_hostgroup(host_id)
            map_info = self.rmt_client.do_mapping(lun_id,
                                                  hostgroup_id,
                                                  host_id)
            host_lun_id = self.rmt_client.find_host_lun_id(host_id, lun_id)
        except exception.VolumeBackendAPIException:
            raise
        except Exception as err:
            msg = _("Connect volume fc: connect volume error. %s.") % err
            LOG.exception(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Return FC properties.
        fc_info = {'driver_volume_type': 'fibre_channel',
                   'data': {'target_lun': int(host_lun_id),
                            'target_discovered': True,
                            'target_wwn': tgt_port_wwns,
                            'volume_id': volume['id'],
                            'initiator_target_map': init_targ_map,
                            'map_info': map_info},
                   }

        LOG.info(_LI('Remote return FC info is: %s.'), fc_info)

        return fc_info

    def disconnect_volume_fc(self, volume, connector):
        """Delete map between a volume and a host for FC."""
        # Login remote storage device.
        self.xml_file_path = self.configuration.cinder_huawei_conf_file
        metro_devices = self.configuration.hypermetro_devices
        device_info = huawei_utils.get_remote_device_info(metro_devices)
        self.rmt_client = rest_client.RestClient(self.configuration)
        self.rmt_client.login_with_ip(device_info)

        try:
            wwns = connector['wwpns']
            volume_name = huawei_utils.encode_name(volume['id'])
            metadata = huawei_utils.get_volume_metadata(volume)
            lun_id = metadata['remote_lun_id']
            host_name = connector['host']
            left_lunnum = -1
            lungroup_id = None
            view_id = None

            LOG.info(_LI('terminate_connection_fc: volume name: %(volume)s, '
                         'wwpns: %(wwns)s, '
                         'lun_id: %(lunid)s.'),
                     {'volume': volume_name,
                      'wwns': wwns,
                      'lunid': lun_id},)

            if host_name and (len(host_name) > constants.MAX_HOSTNAME_LENGTH):
                host_name = six.text_type(hash(host_name))

            hostid = self.rmt_client.find_host(host_name)
            if hostid:
                mapping_view_name = constants.MAPPING_VIEW_PREFIX + hostid
                view_id = self.rmt_client.find_mapping_view(
                    mapping_view_name)
                if view_id:
                    lungroup_id = self.rmt_client.find_lungroup_from_map(
                        view_id)

            if lun_id and self.rmt_client.check_lun_exist(lun_id):
                if lungroup_id:
                    lungroup_ids = self.rmt_client.get_lungroupids_by_lunid(
                        lun_id)
                    if lungroup_id in lungroup_ids:
                        self.rmt_client.remove_lun_from_lungroup(
                            lungroup_id, lun_id)
                    else:
                        LOG.warning(_LW("Lun is not in lungroup. "
                                        "Lun id: %(lun_id)s, "
                                        "lungroup id: %(lungroup_id)s"),
                                    {"lun_id": lun_id,
                                     "lungroup_id": lungroup_id})

            (tgt_port_wwns, init_targ_map) = (
                self.rmt_client.get_init_targ_map(wwns))

            hostid = self.rmt_client.find_host(host_name)
            if hostid:
                mapping_view_name = constants.MAPPING_VIEW_PREFIX + hostid
                view_id = self.rmt_client.find_mapping_view(
                    mapping_view_name)
                if view_id:
                    lungroup_id = self.rmt_client.find_lungroup_from_map(
                        view_id)
            if lungroup_id:
                left_lunnum = self.rmt_client.get_lunnum_from_lungroup(
                    lungroup_id)

        except Exception as err:
            msg = _("Remote detatch volume error. %s.") % err
            LOG.exception(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        finally:
            self.rmt_client.logout()

        if int(left_lunnum) > 0:
            info = {'driver_volume_type': 'fibre_channel',
                    'data': {}}
        else:
            info = {'driver_volume_type': 'fibre_channel',
                    'data': {'target_wwn': tgt_port_wwns,
                             'initiator_target_map': init_targ_map}, }

        return info

    def _wait_volume_ready(self, lun_id):
        event_type = 'LUNReadyWaitInterval'
        wait_interval = huawei_utils.get_wait_interval(self.xml_file_path,
                                                       event_type)

        def _volume_ready():
            result = self.rmt_client.get_lun_info(lun_id)
            if (result['HEALTHSTATUS'] == constants.STATUS_HEALTH
               and result['RUNNINGSTATUS'] == constants.STATUS_VOLUME_READY):
                return True
            return False

        huawei_utils.wait_for_condition(self.xml_file_path,
                                        _volume_ready,
                                        wait_interval,
                                        wait_interval * 10)

    def retype(self, volume, new_type):
        return False

    def get_hypermetro_stats(self, hypermetro_id):
        pass
