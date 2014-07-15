#    Copyright 2014 Objectif Libre
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

from cinder.openstack.common import log as logging
from cinder import utils
import cinder.volume.driver
from cinder.volume.drivers.san.hp import hp_msa_common as hpcommon
from cinder.volume.drivers.san import san
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


class HPMSAFCDriver(cinder.volume.driver.FibreChannelDriver):
    VERSION = "0.1"

    def __init__(self, *args, **kwargs):
        super(HPMSAFCDriver, self).__init__(*args, **kwargs)
        self.common = None
        self.configuration.append_config_values(hpcommon.hpmsa_opt)
        self.configuration.append_config_values(san.san_opts)

    def _init_common(self):
        return hpcommon.HPMSACommon(self.configuration)

    def _check_flags(self):
        required_flags = ['san_ip', 'san_login', 'san_password']
        self.common.check_flags(self.configuration, required_flags)

    def do_setup(self, context):
        self.common = self._init_common()
        self._check_flags()
        self.common.do_setup(context)

    def check_for_setup_error(self):
        self._check_flags()

    @utils.synchronized('msa', external=True)
    def create_volume(self, volume):
        self.common.client_login()
        try:
            metadata = self.common.create_volume(volume)
            return {'metadata': metadata}
        finally:
            self.common.client_logout()

    @utils.synchronized('msa', external=True)
    def create_volume_from_snapshot(self, volume, src_vref):
        self.common.client_login()
        try:
            self.common.create_volume_from_snapshot(volume, src_vref)
        finally:
            self.common.client_logout()

    @utils.synchronized('msa', external=True)
    def create_cloned_volume(self, volume, src_vref):
        self.common.client_login()
        try:
            new_vol = self.common.create_cloned_volume(volume, src_vref)
            return {'metadata': new_vol}
        finally:
            self.common.client_logout()

    @utils.synchronized('msa', external=True)
    def delete_volume(self, volume):
        self.common.client_login()
        try:
            self.common.delete_volume(volume)
        finally:
            self.common.client_logout()

    @fczm_utils.AddFCZone
    @utils.synchronized('msa', external=True)
    def initialize_connection(self, volume, connector):
        self.common.client_login()
        try:
            data = {}
            data['target_lun'] = self.common.map_volume(volume, connector)

            ports = self.common.get_active_fc_target_ports()
            data['target_discovered'] = True
            data['target_wwn'] = ports

            info = {'driver_volume_type': 'fibre_channel',
                    'data': data}
            return info
        finally:
            self.common.client_logout()

    @fczm_utils.RemoveFCZone
    @utils.synchronized('msa', external=True)
    def terminate_connection(self, volume, connector, **kwargs):
        self.common.client_login()
        try:
            self.common.unmap_volume(volume, connector)
        finally:
            self.common.client_logout()

    @utils.synchronized('msa', external=True)
    def get_volume_stats(self, refresh=False):
        if refresh:
            self.common.client_login()
        try:
            stats = self.common.get_volume_stats(refresh)
            stats['storage_protocol'] = 'FC'
            stats['driver_version'] = self.VERSION
            backend_name = self.configuration.safe_get('volume_backend_name')
            stats['volume_backend_name'] = (backend_name or
                                            self.__class__.__name__)
            return stats
        finally:
            if refresh:
                self.common.client_logout()

    @utils.synchronized('msa', external=True)
    def create_export(self, context, volume):
        pass

    @utils.synchronized('msa', external=True)
    def ensure_export(self, context, volume):
        pass

    @utils.synchronized('msa', external=True)
    def remove_export(self, context, volume):
        pass

    @utils.synchronized('msa', external=True)
    def create_snapshot(self, snapshot):
        self.common.client_login()
        try:
            self.common.create_snapshot(snapshot)
        finally:
            self.common.client_logout()

    @utils.synchronized('msa', external=True)
    def delete_snapshot(self, snapshot):
        self.common.client_login()
        try:
            self.common.delete_snapshot(snapshot)
        finally:
            self.common.client_logout()

    @utils.synchronized('msa', external=True)
    def extend_volume(self, volume, new_size):
        self.common.client_login()
        try:
            self.common.extend_volume(volume, new_size)
        finally:
            self.common.client_logout()
