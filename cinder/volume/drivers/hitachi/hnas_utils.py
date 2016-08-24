# Copyright (c) 2016 Hitachi Data Systems, Inc.
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
Shared code for HNAS drivers
"""

import os
import re

from oslo_config import cfg
from oslo_log import log as logging
import six
from xml.etree import ElementTree as ETree

from cinder import exception
from cinder.i18n import _, _LW, _LE
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

HNAS_DEFAULT_CONFIG = {'ssc_cmd': 'ssc',
                       'chap_enabled': True,
                       'ssh_port': 22}

MAX_HNAS_ISCSI_TARGETS = 32

drivers_common_opts = [
    cfg.IPOpt('hnas_mgmt_ip0',
              help='Management IP address of HNAS. This can '
                   'be any IP in the admin address on HNAS or '
                   'the SMU IP.'),
    cfg.StrOpt('hnas_ssc_cmd',
               default='ssc',
               help='Command to communicate to HNAS.'),
    cfg.StrOpt('hnas_username',
               help='HNAS username.'),
    cfg.StrOpt('hnas_password',
               secret=True,
               help='HNAS password.'),
    cfg.PortOpt('hnas_ssh_port',
                default=22,
                help='Port to be used for SSH authentication.'),
    cfg.StrOpt('hnas_ssh_private_key',
               help='Path to the SSH private key used to '
                    'authenticate in HNAS SMU.'),
    cfg.StrOpt('hnas_cluster_admin_ip0',
               default=None,
               help='The IP of the HNAS cluster admin. '
                    'Required only for HNAS multi-cluster setups.'),
    cfg.StrOpt('hnas_svc0_volume_type',
               help='Service 0 volume type'),
    cfg.StrOpt('hnas_svc0_hdp',
               help='Service 0 HDP'),
    cfg.StrOpt('hnas_svc1_volume_type',
               help='Service 1 volume type'),
    cfg.StrOpt('hnas_svc1_hdp',
               help='Service 1 HDP'),
    cfg.StrOpt('hnas_svc2_volume_type',
               help='Service 2 volume type'),
    cfg.StrOpt('hnas_svc2_hdp',
               help='Service 2 HDP'),
    cfg.StrOpt('hnas_svc3_volume_type',
               help='Service 3 volume type'),
    cfg.StrOpt('hnas_svc3_hdp',
               help='Service 3 HDP')
]

CONF = cfg.CONF
CONF.register_opts(drivers_common_opts)


def _check_conf_params(config, vol_type, dv_type, idx):
    """Validates if the configuration on cinder.conf is complete.

    :param config: Dictionary with the driver configurations
    :param vol_type: The volume type of the current pool
    :param dv_type: The type of the driver (NFS or iSCSI)
    :param idx: Index of the current pool
    """

    # Validating the inputs on cinder.conf
    if config['username'] is None:
        msg = (_("The config parameter hnas_username "
                 "is not set in the cinder.conf."))
        LOG.error(msg)
        raise exception.InvalidParameterValue(err=msg)

    if (config['password'] is None and
            config['ssh_private_key'] is None):
        msg = (_("Credentials configuration parameters "
                 "missing: you need to set hnas_password "
                 "or hnas_ssh_private_key "
                 "in the cinder.conf."))
        LOG.error(msg)
        raise exception.InvalidParameterValue(err=msg)

    if config['mgmt_ip0'] is None:
        msg = (_("The config parameter hnas_mgmt_ip0 "
                 "is not set in the cinder.conf."))
        LOG.error(msg)
        raise exception.InvalidParameterValue(err=msg)

    if config['services'][vol_type]['hdp'] is None:
        msg = (_("The config parameter hnas_svc%(idx)s_hdp is "
                 "not set in the cinder.conf. Note that you need to "
                 "have at least one pool configured.") %
               {'idx': idx})
        LOG.error(msg)
        raise exception.InvalidParameterValue(err=msg)

    if config['services'][vol_type]['volume_type'] is None:
        msg = (_("The config parameter "
                 "hnas_svc%(idx)s_volume_type is not set "
                 "in the cinder.conf. Note that you need to "
                 "have at least one pool configured.") %
               {'idx': idx})
        LOG.error(msg)
        raise exception.InvalidParameterValue(err=msg)

    if (dv_type == 'iscsi' and
            config['services'][vol_type]['iscsi_ip'] is None):
        msg = (_("The config parameter "
                 "hnas_svc%(idx)s_iscsi_ip is not set "
                 "in the cinder.conf. Note that you need to "
                 "have at least one pool configured.") % {'idx': idx})
        LOG.error(msg)
        raise exception.InvalidParameterValue(err=msg)


def _xml_read(root, element, check=None):
    """Read an xml element.

    :param root: XML object
    :param element: string desired tag
    :param check: string if present, throw exception if element missing
    """

    val = root.findtext(element)

    # mandatory parameter not found
    if val is None and check:
        LOG.error(_LE("Mandatory parameter not found: %(p)s"), {'p': element})
        raise exception.ParameterNotFound(param=element)

    # tag not found
    if val is None:
        return None

    svc_tag_pattern = re.compile("svc_[0-3]$")
    # tag found but empty parameter.
    if not val.strip():
        if svc_tag_pattern.search(element):
            return ""
        LOG.error(_LE("Parameter not found: %(param)s"), {'param': element})
        raise exception.ParameterNotFound(param=element)

    LOG.debug("%(element)s: %(val)s",
              {'element': element,
               'val': val if element != 'password' else '***'})

    return val.strip()


def read_xml_config(xml_config_file, svc_params, optional_params):
    """Read Hitachi driver specific xml config file.

    :param xml_config_file: string filename containing XML configuration
    :param svc_params: parameters to configure the services
    ['volume_type', 'hdp', 'iscsi_ip']
    :param optional_params: parameters to configure that are not mandatory
    ['ssc_cmd', 'cluster_admin_ip0', 'chap_enabled']
    """

    if not os.access(xml_config_file, os.R_OK):
        msg = (_("Can't find HNAS configurations on cinder.conf neither "
                 "on the path %(xml)s.") % {'xml': xml_config_file})
        LOG.error(msg)
        raise exception.ConfigNotFound(message=msg)
    else:
        LOG.warning(_LW("This XML configuration file %(xml)s is deprecated. "
                        "Please, move all the configurations to the "
                        "cinder.conf file. If you keep both configuration "
                        "files, the options set on cinder.conf will be "
                        "used."), {'xml': xml_config_file})

    try:
        root = ETree.parse(xml_config_file).getroot()
    except ETree.ParseError:
        msg = (_("Error parsing config file: %(xml_config_file)s") %
               {'xml_config_file': xml_config_file})
        LOG.error(msg)
        raise exception.ConfigNotFound(message=msg)

    # mandatory parameters for NFS and iSCSI
    config = {}
    arg_prereqs = ['mgmt_ip0', 'username']
    for req in arg_prereqs:
        config[req] = _xml_read(root, req, 'check')

    # optional parameters for NFS and iSCSI
    for req in optional_params:
        config[req] = _xml_read(root, req)
        if config[req] is None and HNAS_DEFAULT_CONFIG.get(req) is not None:
            config[req] = HNAS_DEFAULT_CONFIG.get(req)

    config['ssh_private_key'] = _xml_read(root, 'ssh_private_key')
    config['password'] = _xml_read(root, 'password')

    if config['ssh_private_key'] is None and config['password'] is None:
        msg = _("Missing authentication option (passw or private key file).")
        LOG.error(msg)
        raise exception.ConfigNotFound(message=msg)

    if _xml_read(root, 'ssh_port') is not None:
        config['ssh_port'] = int(_xml_read(root, 'ssh_port'))
    else:
        config['ssh_port'] = HNAS_DEFAULT_CONFIG['ssh_port']

    config['fs'] = {}
    config['services'] = {}

    # min one needed
    for svc in ['svc_0', 'svc_1', 'svc_2', 'svc_3']:
        if _xml_read(root, svc) is None:
            continue
        service = {'label': svc}

        # none optional
        for arg in svc_params:
            service[arg] = _xml_read(root, svc + '/' + arg, 'check')
        config['services'][service['volume_type']] = service
        config['fs'][service['hdp']] = service['hdp']

    # at least one service required!
    if not config['services'].keys():
        LOG.error(_LE("No service found in xml config file"))
        raise exception.ParameterNotFound(param="svc_0")

    return config


def get_pool(config, volume):
    """Get the pool of a volume.

    :param config: dictionary containing the configuration parameters
    :param volume: dictionary volume reference
    :returns: the pool related to the volume
    """

    if volume.volume_type:
        metadata = {}
        type_id = volume.volume_type_id
        if type_id is not None:
            metadata = volume_types.get_volume_type_extra_specs(type_id)
        if metadata.get('service_label'):
            if metadata['service_label'] in config['services'].keys():
                return metadata['service_label']
    return 'default'


def read_cinder_conf(config_opts, dv_type):
    """Reads cinder.conf

    Gets the driver specific information set on cinder.conf configuration
    file.

    :param config_opts: Configuration object that contains the information
    needed by HNAS driver
    :param dv_type: The type of the driver (NFS or iSCSI)
    :returns: Dictionary with the driver configuration
    """

    config = {}
    config['services'] = {}
    config['fs'] = {}
    mandatory_parameters = ['username', 'password', 'mgmt_ip0']
    optional_parameters = ['ssc_cmd', 'chap_enabled',
                           'ssh_port', 'cluster_admin_ip0',
                           'ssh_private_key']

    # Trying to get the mandatory parameters from cinder.conf
    for opt in mandatory_parameters:
        config[opt] = config_opts.safe_get('hnas_%(opt)s' % {'opt': opt})

    # If there is at least one of the mandatory parameters in
    # cinder.conf, we assume that we should use the configuration
    # from this file.
    # Otherwise, we use the configuration from the deprecated XML file.
    for param in mandatory_parameters:
        if config[param] is not None:
            break
    else:
        return None

    # Getting the optional parameters from cinder.conf
    for opt in optional_parameters:
        config[opt] = config_opts.safe_get('hnas_%(opt)s' % {'opt': opt})

    # It's possible to have up to 4 pools configured.
    for i in range(0, 4):
        idx = six.text_type(i)
        svc_vol_type = (config_opts.safe_get(
            'hnas_svc%(idx)s_volume_type' % {'idx': idx}))

        svc_hdp = (config_opts.safe_get(
            'hnas_svc%(idx)s_hdp' % {'idx': idx}))

        # It's mandatory to have at least 1 pool configured (svc_0)
        if (idx == '0' or svc_vol_type is not None or
                svc_hdp is not None):
            config['services'][svc_vol_type] = {}
            config['fs'][svc_hdp] = svc_hdp
            config['services'][svc_vol_type]['hdp'] = svc_hdp
            config['services'][svc_vol_type]['volume_type'] = svc_vol_type

            if dv_type == 'iscsi':
                svc_ip = (config_opts.safe_get(
                    'hnas_svc%(idx)s_iscsi_ip' % {'idx': idx}))
                config['services'][svc_vol_type]['iscsi_ip'] = svc_ip

            config['services'][svc_vol_type]['label'] = (
                'svc_%(idx)s' % {'idx': idx})
            # Checking to ensure that the pools configurations are complete
            _check_conf_params(config, svc_vol_type, dv_type, idx)

    return config
