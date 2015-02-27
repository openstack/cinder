# Copyright (c) 2013 Huawei Technologies Co., Ltd.
# Copyright (c) 2012 OpenStack LLC.
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

from xml.etree import ElementTree as ET

from cinder.i18n import _LE
from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)

os_type = {'Linux': '0',
           'Windows': '1',
           'Solaris': '2',
           'HP-UX': '3',
           'AIX': '4',
           'XenServer': '5',
           'Mac OS X': '6',
           'VMware ESX': '7'}


def parse_xml_file(filepath):
    """Get root of xml file."""
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        return root
    except IOError as err:
        LOG.error(_LE('parse_xml_file: %s') % err)
        raise err


def get_xml_item(xml_root, item):
    """Get the given item details.

    :param xml_root: The root of xml tree
    :param item: The tag need to get
    :return: A dict contains all the config info of the given item.
    """
    items_list = []
    items = xml_root.findall(item)
    for item in items:
        tmp_dict = {'text': None, 'attrib': {}}
        if item.text:
            tmp_dict['text'] = item.text.strip()
        for key, val in item.attrib.items():
            if val:
                item.attrib[key] = val.strip()
        tmp_dict['attrib'] = item.attrib
        items_list.append(tmp_dict)
    return items_list


def is_xml_item_exist(xml_root, item, attrib_key=None):
    """Check if the given item exits in xml config file.

    :param xml_root: The root of xml tree
    :param item: The xml tag to check
    :param attrib_key: The xml attrib to check
    :return: True of False
    """
    items_list = get_xml_item(xml_root, item)
    if attrib_key:
        for tmp_dict in items_list:
            if tmp_dict['attrib'].get(attrib_key, None):
                return True
    else:
        if items_list and items_list[0]['text']:
            return True
    return False


def is_xml_item_valid(xml_root, item, valid_list, attrib_key=None):
    """Check if the given item is valid in xml config file.

    :param xml_root: The root of xml tree
    :param item: The xml tag to check
    :param valid_list: The valid item value
    :param attrib_key: The xml attrib to check
    :return: True of False
    """
    items_list = get_xml_item(xml_root, item)
    if attrib_key:
        for tmp_dict in items_list:
            value = tmp_dict['attrib'].get(attrib_key, None)
            if value not in valid_list:
                return False
    else:
        value = items_list[0]['text']
        if value not in valid_list:
            return False

    return True


def get_conf_host_os_type(host_ip, config):
    """Get host OS type from xml config file.

    :param host_ip: The IP of Nova host
    :param config: xml config file
    :return: host OS type
    """
    os_conf = {}
    root = parse_xml_file(config)
    hosts_list = get_xml_item(root, 'Host')
    for host in hosts_list:
        os = host['attrib']['OSType'].strip()
        ips = [ip.strip() for ip in host['attrib']['HostIP'].split(',')]
        os_conf[os] = ips
    host_os = None
    for k, v in os_conf.items():
        if host_ip in v:
            host_os = os_type.get(k, None)
    if not host_os:
        host_os = os_type['Linux']  # default os type

    LOG.debug('_get_host_os_type: Host %(ip)s OS type is %(os)s.'
              % {'ip': host_ip, 'os': host_os})

    return host_os
