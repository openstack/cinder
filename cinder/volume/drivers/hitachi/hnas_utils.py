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

from oslo_log import log as logging
from xml.etree import ElementTree as ETree

from cinder import exception
from cinder.i18n import _, _LI
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

HNAS_DEFAULT_CONFIG = {'hnas_cmd': 'ssc',
                       'chap_enabled': 'True',
                       'ssh_port': '22'}

MAX_HNAS_ISCSI_TARGETS = 32


def _xml_read(root, element, check=None):
    """Read an xml element.

    :param root: XML object
    :param element: string desired tag
    :param check: string if present, throw exception if element missing
    """

    val = root.findtext(element)

    # mandatory parameter not found
    if val is None and check:
        raise exception.ParameterNotFound(param=element)

    # tag not found
    if val is None:
        return None

    svc_tag_pattern = re.compile("svc_[0-3]$")
    # tag found but empty parameter.
    if not val.strip():
        if svc_tag_pattern.search(element):
            return ""
        raise exception.ParameterNotFound(param=element)

    LOG.debug(_LI("%(element)s: %(val)s"),
              {'element': element,
               'val': val if element != 'password' else '***'})

    return val.strip()


def read_config(xml_config_file, svc_params, optional_params):
    """Read Hitachi driver specific xml config file.

    :param xml_config_file: string filename containing XML configuration
    :param svc_params: parameters to configure the services
    ['volume_type', 'hdp', 'iscsi_ip']
    :param optional_params: parameters to configure that are not mandatory
    ['hnas_cmd', 'ssh_enabled', 'cluster_admin_ip0', 'chap_enabled']
    """

    if not os.access(xml_config_file, os.R_OK):
        msg = (_("Can't open config file: %s") % xml_config_file)
        raise exception.NotFound(message=msg)

    try:
        root = ETree.parse(xml_config_file).getroot()
    except ETree.ParseError:
        msg = (_("Error parsing config file: %s") % xml_config_file)
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
        msg = (_("Missing authentication option (passw or private key file)."))
        raise exception.ConfigNotFound(message=msg)

    config['ssh_port'] = _xml_read(root, 'ssh_port')
    if config['ssh_port'] is None:
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
        msg = (_("svc_0"))
        raise exception.ParameterNotFound(param=msg)

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
