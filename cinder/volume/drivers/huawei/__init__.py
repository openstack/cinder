# Copyright (c) 2013 - 2014 Huawei Technologies Co., Ltd.
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
"""
Provide a unified driver class for users.

The product type and the protocol should be specified in config file before.
"""

from oslo_config import cfg
from oslo_log import log as logging
import six

from cinder import exception
from cinder.i18n import _, _LI, _LW
from cinder.volume.drivers.huawei import huawei_18000
from cinder.volume.drivers.huawei import huawei_utils


LOG = logging.getLogger(__name__)

huawei_opt = [
    cfg.StrOpt('cinder_huawei_conf_file',
               default='/etc/cinder/cinder_huawei_conf.xml',
               help='The configuration file for the Cinder Huawei '
                    'driver')]

CONF = cfg.CONF
CONF.register_opts(huawei_opt)
MAPPING = {'HVS': '18000'}


class HuaweiVolumeDriver(object):
    """Define an unified driver for Huawei drivers."""

    def __init__(self, *args, **kwargs):
        super(HuaweiVolumeDriver, self).__init__()
        self._product = {'18000': huawei_18000, 'HVS': huawei_18000}
        self._protocol = {'iSCSI': 'ISCSIDriver', 'FC': 'FCDriver'}

        self.driver = self._instantiate_driver(*args, **kwargs)

    def _instantiate_driver(self, *args, **kwargs):
        """Instantiate the specified driver."""
        self.configuration = kwargs.get('configuration', None)
        if not self.configuration:
            msg = (_('_instantiate_driver: configuration not found.'))
            raise exception.InvalidInput(reason=msg)

        self.configuration.append_config_values(huawei_opt)
        conf_file = self.configuration.cinder_huawei_conf_file
        (product, protocol) = self._get_conf_info(conf_file)

        LOG.info(_LI(
            '_instantiate_driver: Loading %(protocol)s driver for '
            'Huawei OceanStor %(product)s series storage arrays.')
            % {'protocol': protocol,
               'product': product})
        # Map HVS to 18000
        if product in MAPPING:
            LOG.warn(_LW("Product name %s is deprecated, update your "
                         "configuration to the new product name."), product)
            product = MAPPING[product]

        driver_module = self._product[product]
        driver_class = 'Huawei' + product + self._protocol[protocol]

        driver_class = getattr(driver_module, driver_class)
        return driver_class(*args, **kwargs)

    def _get_conf_info(self, filename):
        """Get product type and connection protocol from config file."""
        root = huawei_utils.parse_xml_file(filename)
        product = root.findtext('Storage/Product').strip()
        protocol = root.findtext('Storage/Protocol').strip()
        if (product in self._product.keys() and
                protocol in self._protocol.keys()):
            return (product, protocol)
        else:
            msg = (_('"Product" or "Protocol" is illegal. "Product" should be '
                     'set to 18000. "Protocol" should be set to either iSCSI '
                     'or FC. Product: %(product)s Protocol: %(protocol)s')
                   % {'product': six.text_type(product),
                      'protocol': six.text_type(protocol)})
            raise exception.InvalidInput(reason=msg)

    def __setattr__(self, name, value):
        """Set the attribute."""
        if getattr(self, 'driver', None):
            self.driver.__setattr__(name, value)
            return
        object.__setattr__(self, name, value)

    def __getattr__(self, name):
        """"Get the attribute."""
        drver = object.__getattribute__(self, 'driver')
        return getattr(drver, name)
