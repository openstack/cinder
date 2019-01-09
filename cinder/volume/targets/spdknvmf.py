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

import json
import string

from oslo_config import cfg
from oslo_log import log as logging
import requests

from cinder import exception
from cinder.i18n import _
from cinder.volume import configuration
from cinder.volume.targets import nvmeof
from cinder.volume import utils

spdk_opts = [
    cfg.StrOpt('spdk_rpc_ip',
               help='The NVMe target remote configuration IP address.'),
    cfg.PortOpt('spdk_rpc_port',
                default=8000,
                help='The NVMe target remote configuration port.'),
    cfg.StrOpt('spdk_rpc_username',
               help='The NVMe target remote configuration username.'),
    cfg.StrOpt('spdk_rpc_password',
               help='The NVMe target remote configuration password.',
               secret=True),
]
CONF = cfg.CONF
CONF.register_opts(spdk_opts, group=configuration.SHARED_CONF_GROUP)


LOG = logging.getLogger(__name__)


class SpdkNvmf(nvmeof.NVMeOF):

    def __init__(self, *args, **kwargs):
        super(SpdkNvmf, self).__init__(*args, **kwargs)

        self.configuration.append_config_values(spdk_opts)
        self.url = ('http://%(ip)s:%(port)s/' %
                    {'ip': self.configuration.spdk_rpc_ip,
                     'port': self.configuration.spdk_rpc_port})

        # SPDK NVMe-oF Target application requires one time creation
        # of RDMA transport type each time it is started. It will
        # fail on second attempt which is expected behavior.
        try:
            params = {
                'trtype': 'rdma',
            }
            self._rpc_call('nvmf_create_transport', params)
        except Exception:
            pass

    def _rpc_call(self, method, params=None):
        payload = {}
        payload['jsonrpc'] = '2.0'
        payload['id'] = 1
        payload['method'] = method
        if params is not None:
            payload['params'] = params

        req = requests.post(self.url,
                            data=json.dumps(payload),
                            auth=(self.configuration.spdk_rpc_username,
                                  self.configuration.spdk_rpc_password),
                            verify=self.configuration.driver_ssl_cert_verify,
                            timeout=30)

        if not req.ok:
            raise exception.VolumeBackendAPIException(
                data=_('SPDK target responded with error: %s') % req.text)

        return req.json()['result']

    def _get_spdk_volume_name(self, name):
        output = self._rpc_call('get_bdevs')

        for bdev in output:
            for alias in bdev['aliases']:
                if name in alias:
                    return bdev['name']

    def _get_nqn_with_volume_name(self, name):
        output = self._rpc_call('get_nvmf_subsystems')

        spdk_name = self._get_spdk_volume_name(name)

        if spdk_name is not None:
            for subsystem in output[1:]:
                for namespace in subsystem['namespaces']:
                    if spdk_name in namespace['bdev_name']:
                        return subsystem['nqn']

    def _get_first_free_node(self):
        cnode_num = []

        output = self._rpc_call('get_nvmf_subsystems')

        # Get node numbers for nqn string like this: nqn.2016-06.io.spdk:cnode1

        for subsystem in output[1:]:
            cnode_num.append(int(subsystem['nqn'].split("cnode")[1]))

        test_set = set(range(1, len(cnode_num) + 2))

        return list(test_set.difference(cnode_num))[0]

    def create_nvmeof_target(self,
                             volume_id,
                             subsystem_name,
                             target_ip,
                             target_port,
                             transport_type,
                             nvmet_port_id,
                             ns_id,
                             volume_path):

        LOG.debug('SPDK create target')

        nqn = self._get_nqn_with_volume_name(volume_id)

        if nqn is None:
            node = self._get_first_free_node()
            nqn = '%s:cnode%s' % (subsystem_name, node)
            choice = string.ascii_uppercase + string.digits
            serial = ''.join(
                utils.generate_password(length=12, symbolgroups=choice))

            params = {
                'nqn': nqn,
                'allow_any_host': True,
                'serial_number': serial,
            }
            self._rpc_call('nvmf_subsystem_create', params)

            listen_address = {
                'trtype': transport_type,
                'traddr': target_ip,
                'trsvcid': str(target_port),
            }
            params = {
                'nqn': nqn,
                'listen_address': listen_address,
            }
            self._rpc_call('nvmf_subsystem_add_listener', params)

            ns = {
                'bdev_name': self._get_spdk_volume_name(volume_id),
                'nsid': ns_id,
            }
            params = {
                'nqn': nqn,
                'namespace': ns,
            }
            self._rpc_call('nvmf_subsystem_add_ns', params)

        location = self.get_nvmeof_location(
            nqn,
            target_ip,
            target_port,
            transport_type,
            ns_id)

        return {'location': location, 'auth': '', 'provider_id': nqn}

    def delete_nvmeof_target(self, target_name):
        LOG.debug('SPDK delete target: %s', target_name)

        nqn = self._get_nqn_with_volume_name(target_name.name)

        if nqn is not None:
            try:
                params = {'nqn': nqn}
                self._rpc_call('delete_nvmf_subsystem', params)
                LOG.debug('SPDK subsystem %s deleted', nqn)
            except Exception as e:
                LOG.debug('SPDK ERROR: subsystem not deleted: %s', e)
