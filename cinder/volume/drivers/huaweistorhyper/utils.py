# Copyright (c) 2014 Huawei Technologies Co., Ltd.
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
 Utils for Huawei SDSHypervisor systems.
"""

import socket
from xml.etree import ElementTree as ETree

import six

from cinder.i18n import _LW, _LE
from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def serialize(title, para):
    para_list = ['[' + title + ']\n']
    if len(para):
        for key, value in para.items():
            if isinstance(value, list):
                for item in value:
                    para_list.append(key + "=" + six.text_type(item) + "\n")
            else:
                para_list.append(key + "=" + six.text_type(value) + "\n")
            LOG.debug('key=%(key)s  value=%(value)s.'
                      % {'key': key, 'value': value})

    return ''.join(para_list)


def deserialize(rsp_str, delimiter):
    LOG.debug('Calling deserialize: %s.' % rsp_str)
    rsp = {}
    if len(rsp_str) > 0:
        lines = rsp_str.split(delimiter)
        for line in lines:
            LOG.debug('line = %s.' % line)
            if line.find('=') != -1:
                paras = six.text_type(line).split('=', 1)
                key = paras[0].replace('=', '')
                value = paras[1].replace('\n', '').replace('\x00', '')
                rsp[key] = value.strip()
    return rsp


def parse_xml_file(file_path):
    """Get root of xml file."""
    try:
        tree = ETree.parse(file_path)
        root = tree.getroot()
        return root
    except IOError as err:
        LOG.error(_LE('Parse_xml_file: %s.'), exc_info=True)
        raise err


def check_ipv4(ip_string):
    """Check if ip(v4) valid."""
    if ip_string.find('.') == -1:
        return False
    try:
        socket.inet_aton(ip_string)
        return True
    except Exception:
        return False


def get_valid_ip_list(ip_list):
    valid_ip_list = []
    for ip in ip_list:
        ip = ip.strip()
        LOG.debug('IP=%s.' % ip)
        if not check_ipv4(ip):
            LOG.warn(_LW('Invalid ip, ip address is: %s.') % ip)
        else:
            valid_ip_list.append(ip)
    return valid_ip_list


def get_ip_and_port(config_file):
    root = parse_xml_file(config_file)
    vbs_url = root.findtext('controller/vbs_url').strip()
    LOG.debug('VbsClient   vbs_url=%s.' % vbs_url)
    vbs_port = root.findtext('controller/vbs_port').strip()
    LOG.debug('VbsClient   vbs_port=%s.' % vbs_port)

    valid_ip_list = get_valid_ip_list(vbs_url.split(','))
    port = int(vbs_port)

    return valid_ip_list, port


def log_dict(result):
    if result:
        for key, value in result.items():
            LOG.debug('key=%(key)s  value=%(value)s.'
                      % {'key': key, 'value': value})


def generate_dict_from_result(result):
    LOG.debug('Result from response=%s.' % result)
    result = result.replace('[', '').replace(']', '')
    result = deserialize(result, delimiter=',')
    log_dict(result)
    return result