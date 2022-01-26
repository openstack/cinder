# Copyright (C) 2021 NEC corporation
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
"""Fibre channel module for NEC Driver."""

from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.hitachi import hbsd_common
from cinder.volume.drivers.hitachi import hbsd_fc
from cinder.volume.drivers.hitachi import hbsd_rest
from cinder.volume.drivers.hitachi import hbsd_utils
from cinder.volume.drivers.nec.v import nec_v_rest as rest
from cinder.volume.drivers.nec.v import nec_v_utils as utils

MSG = hbsd_utils.HBSDMsg


@interface.volumedriver
class VStorageFCDriver(hbsd_fc.HBSDFCDriver):
    """Fibre channel class for NEC Driver.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver.

    """

    VERSION = utils.VERSION

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = utils.CI_WIKI_NAME

    def __init__(self, *args, **kwargs):
        """Initialize instance variables."""
        super(VStorageFCDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(rest.COMMON_VOLUME_OPTS)
        self.configuration.append_config_values(rest.FC_VOLUME_OPTS)

    def _init_common(self, conf, db):
        utils.DRIVER_INFO['proto'] = 'FC'
        utils.DRIVER_INFO['hba_id'] = 'wwpns'
        utils.DRIVER_INFO['hba_id_type'] = 'World Wide Name'
        utils.DRIVER_INFO['msg_id'] = {
            'target': MSG.CREATE_HOST_GROUP_FAILED}
        utils.DRIVER_INFO['volume_backend_name'] = '%(prefix)sFC' % {
            'prefix': utils.DRIVER_PREFIX}
        utils.DRIVER_INFO['volume_type'] = 'fibre_channel'

        return rest.VStorageRESTFC(conf, utils.DRIVER_INFO, db)

    @staticmethod
    def get_driver_options():
        additional_opts = driver.BaseVD._get_oslo_driver_opts(
            *(hbsd_common._INHERITED_VOLUME_OPTS +
              hbsd_rest._REQUIRED_REST_OPTS +
              ['driver_ssl_cert_verify', 'driver_ssl_cert_path',
               'san_api_port']))
        return (rest.COMMON_VOLUME_OPTS + rest.REST_VOLUME_OPTS +
                rest.FC_VOLUME_OPTS + additional_opts)
