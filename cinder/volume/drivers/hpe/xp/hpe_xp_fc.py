# Copyright (C) 2022, Hewlett Packard Enterprise, Ltd.
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
"""Fibre channel module for Hewlett Packard Enterprise Driver."""

from cinder import interface
from cinder.volume.drivers.hitachi import hbsd_common
from cinder.volume.drivers.hitachi import hbsd_fc
from cinder.volume.drivers.hitachi import hbsd_rest
from cinder.volume.drivers.hitachi import hbsd_utils
from cinder.volume.drivers.hpe.xp import hpe_xp_rest as rest
from cinder.volume.drivers.hpe.xp import hpe_xp_utils as utils

MSG = hbsd_utils.HBSDMsg

_DRIVER_INFO = {
    'version': utils.VERSION,
    'proto': 'FC',
    'hba_id': 'wwpns',
    'hba_id_type': 'World Wide Name',
    'msg_id': {
        'target': MSG.CREATE_HOST_GROUP_FAILED,
    },
    'volume_backend_name': '%(prefix)sFC' % {
        'prefix': utils.DRIVER_PREFIX,
    },
    'volume_type': 'fibre_channel',
    'param_prefix': utils.PARAM_PREFIX,
    'vendor_name': utils.VENDOR_NAME,
    'driver_prefix': utils.DRIVER_PREFIX,
    'driver_file_prefix': utils.DRIVER_FILE_PREFIX,
    'target_prefix': utils.TARGET_PREFIX,
    'hdp_vol_attr': utils.HDP_VOL_ATTR,
    'hdt_vol_attr': utils.HDT_VOL_ATTR,
    'nvol_ldev_type': utils.NVOL_LDEV_TYPE,
    'target_iqn_suffix': utils.TARGET_IQN_SUFFIX,
    'pair_attr': utils.PAIR_ATTR,
}


@interface.volumedriver
class HPEXPFCDriver(hbsd_fc.HBSDFCDriver):
    """Fibre channel class for  Hewlett Packard Enterprise Driver.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver.

    """

    VERSION = utils.VERSION

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = utils.CI_WIKI_NAME

    def __init__(self, *args, **kwargs):
        """Initialize instance variables."""
        super(HPEXPFCDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(rest.COMMON_VOLUME_OPTS)
        self.configuration.append_config_values(rest.FC_VOLUME_OPTS)

    def _init_common(self, conf, db):
        return rest.HPEXPRESTFC(conf, _DRIVER_INFO, db)

    @staticmethod
    def get_driver_options():
        additional_opts = HPEXPFCDriver._get_oslo_driver_opts(
            *(hbsd_common._INHERITED_VOLUME_OPTS +
              hbsd_rest._REQUIRED_REST_OPTS +
              ['driver_ssl_cert_verify', 'driver_ssl_cert_path',
               'san_api_port', ]))
        return (rest.COMMON_VOLUME_OPTS +
                rest.REST_VOLUME_OPTS +
                rest.FC_VOLUME_OPTS +
                additional_opts)
