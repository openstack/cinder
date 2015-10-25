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

import base64
import json
import six
import time
import uuid
from xml.etree import ElementTree as ET

from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder import utils
from cinder.i18n import _, _LE, _LI
from cinder.volume.drivers.huawei import constants
from cinder.volume import qos_specs
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)


opts_capability = {
    'smarttier': False,
    'smartcache': False,
    'smartpartition': False,
    'thin_provisioning_support': False,
    'thick_provisioning_support': False,
    'hypermetro': False,
}


opts_value = {
    'policy': None,
    'partitionname': None,
    'cachename': None,
}


opts_associate = {
    'smarttier': 'policy',
    'smartcache': 'cachename',
    'smartpartition': 'partitionname',
}


def get_volume_params(volume):
    opts = {}
    ctxt = context.get_admin_context()
    type_id = volume['volume_type_id']
    if type_id is not None:
        volume_type = volume_types.get_volume_type(ctxt, type_id)
        specs = dict(volume_type).get('extra_specs')
        opts = _get_extra_spec_value(specs)
    else:
        opts.update(opts_capability)
        opts.update(opts_value)

    return opts


def _get_extra_spec_value(specs):
    """Return the parameters for creating the volume."""
    opts = {}
    opts.update(opts_capability)
    opts.update(opts_value)

    opts = _get_opts_from_specs(opts_capability, opts_value, specs)
    LOG.debug('get_volume_params opts %(opts)s.', {'opts': opts})

    return opts


def _get_opts_from_specs(opts_capability, opts_value, specs):
    opts = {}
    opts.update(opts_capability)
    opts.update(opts_value)

    for key, value in specs.items():

        # Get the scope, if is using scope format.
        scope = None
        key_split = key.split(':')
        if len(key_split) > 2 and key_split[0] != "capabilities":
            continue

        if len(key_split) == 1:
            key = key_split[0]
        else:
            scope = key_split[0]
            key = key_split[1]

        if scope:
            scope = scope.lower()
        if key:
            key = key.lower()

        if ((not scope or scope == 'capabilities')
                and key in opts_capability):

            words = value.split()

            if not (words and len(words) == 2 and words[0] == '<is>'):
                LOG.error(_LE("Extra specs must be specified as "
                              "capabilities:%s='<is> True' or "
                              "'<is> true'."), key)
            else:
                opts[key] = words[1].lower()

        if (scope in opts_capability) and (key in opts_value):
            if (scope in opts_associate) and (opts_associate[scope] == key):
                opts[key] = value

    return opts


def _get_smartx_specs_params(lunsetinfo, smartx_opts):
    """Get parameters from config file for creating lun."""
    # Default lun set information.
    if 'LUNType' in smartx_opts:
        lunsetinfo['LUNType'] = smartx_opts['LUNType']
    lunsetinfo['policy'] = smartx_opts['policy']

    return lunsetinfo


def get_lun_params(xml_file_path, smartx_opts):
    lunsetinfo = get_lun_conf_params(xml_file_path)
    lunsetinfo = _get_smartx_specs_params(lunsetinfo, smartx_opts)
    return lunsetinfo


def parse_xml_file(xml_file_path):
    """Get root of xml file."""
    try:
        tree = ET.parse(xml_file_path)
        root = tree.getroot()
        return root
    except IOError as err:
        LOG.error(_LE('parse_xml_file: %s.'), err)
        raise


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


def get_conf_host_os_type(host_ip, conf):
    """Get host OS type from xml config file.

    :param host_ip: The IP of Nova host
    :param config: xml config file
    :return: host OS type
    """
    os_conf = {}
    xml_file_path = conf.cinder_huawei_conf_file
    root = parse_xml_file(xml_file_path)
    hosts_list = get_xml_item(root, 'Host')
    for host in hosts_list:
        os = host['attrib']['OSType'].strip()
        ips = [ip.strip() for ip in host['attrib']['HostIP'].split(',')]
        os_conf[os] = ips
    host_os = None
    for k, v in os_conf.items():
        if host_ip in v:
            host_os = constants.OS_TYPE.get(k, None)
    if not host_os:
        host_os = constants.OS_TYPE['Linux']  # Default OS type.

    LOG.debug('_get_host_os_type: Host %(ip)s OS type is %(os)s.',
              {'ip': host_ip, 'os': host_os})

    return host_os


def get_qos_by_volume_type(volume_type):
    qos = {}
    qos_specs_id = volume_type.get('qos_specs_id')

    # We prefer the qos_specs association
    # and override any existing extra-specs settings
    # if present.
    if qos_specs_id is not None:
        kvs = qos_specs.get_qos_specs(context.get_admin_context(),
                                      qos_specs_id)['specs']
    else:
        return qos

    LOG.info(_LI('The QoS sepcs is: %s.'), kvs)
    for key, value in kvs.items():
        if key in constants.HUAWEI_VALID_KEYS:
            if (key.upper() != 'IOTYPE') and (int(value) <= 0):
                err_msg = (_('Qos config is wrong. %(key)s'
                             ' must be set greater than 0.')
                           % {'key': key})
                LOG.error(err_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)
            elif (key.upper() == 'IOTYPE') and (value not in ['0', '1', '2']):
                raise exception.InvalidInput(
                    reason=(_('Illegal value specified for IOTYPE: '
                              'set to either 0, 1, or 2.')))
            else:
                qos[key.upper()] = value

    return qos


def get_volume_qos(volume):
    qos = {}
    ctxt = context.get_admin_context()
    type_id = volume['volume_type_id']
    if type_id is not None:
        volume_type = volume_types.get_volume_type(ctxt, type_id)
        qos = get_qos_by_volume_type(volume_type)

    return qos


def _get_volume_type(type_id):
    ctxt = context.get_admin_context()
    return volume_types.get_volume_type(ctxt, type_id)


def get_lun_conf_params(xml_file_path):
    """Get parameters from config file for creating lun."""
    lunsetinfo = {
        'LUNType': 0,
        'StripUnitSize': '64',
        'WriteType': '1',
        'MirrorSwitch': '1',
        'PrefetchType': '3',
        'PrefetchValue': '0',
        'PrefetchTimes': '0',
        'policy': '0',
        'readcachepolicy': '2',
        'writecachepolicy': '5',
    }
    # Default lun set information.
    root = parse_xml_file(xml_file_path)
    luntype = root.findtext('LUN/LUNType')
    if luntype:
        if luntype.strip() in ['Thick', 'Thin']:
            lunsetinfo['LUNType'] = luntype.strip()
            if luntype.strip() == 'Thick':
                lunsetinfo['LUNType'] = 0
            elif luntype.strip() == 'Thin':
                lunsetinfo['LUNType'] = 1

        else:
            err_msg = (_(
                "LUNType config is wrong. LUNType must be 'Thin'"
                " or 'Thick'. LUNType: %(fetchtype)s.")
                % {'fetchtype': luntype})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)
    else:
        lunsetinfo['LUNType'] = 0

    stripunitsize = root.findtext('LUN/StripUnitSize')
    if stripunitsize is not None:
        lunsetinfo['StripUnitSize'] = stripunitsize.strip()
    writetype = root.findtext('LUN/WriteType')
    if writetype is not None:
        lunsetinfo['WriteType'] = writetype.strip()
    mirrorswitch = root.findtext('LUN/MirrorSwitch')
    if mirrorswitch is not None:
        lunsetinfo['MirrorSwitch'] = mirrorswitch.strip()

    prefetch = root.find('LUN/Prefetch')
    if prefetch is not None and prefetch.attrib['Type']:
        fetchtype = prefetch.attrib['Type']
        if fetchtype in ['0', '1', '2', '3']:
            lunsetinfo['PrefetchType'] = fetchtype.strip()
            typevalue = prefetch.attrib['Value'].strip()
            if lunsetinfo['PrefetchType'] == '1':
                double_value = int(typevalue) * 2
                typevalue_double = six.text_type(double_value)
                lunsetinfo['PrefetchValue'] = typevalue_double
            elif lunsetinfo['PrefetchType'] == '2':
                lunsetinfo['PrefetchValue'] = typevalue
        else:
            err_msg = (_(
                'PrefetchType config is wrong. PrefetchType'
                ' must be in 0,1,2,3. PrefetchType is: %(fetchtype)s.')
                % {'fetchtype': fetchtype})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)
    else:
        LOG.info(_LI(
            'Use default PrefetchType. '
            'PrefetchType: Intelligent.'))

    return lunsetinfo


def find_luntype_in_xml(xml_file_path):
    root = parse_xml_file(xml_file_path)
    luntype = root.findtext('LUN/LUNType')
    if luntype:
        if luntype.strip() in ['Thick', 'Thin']:
            if luntype.strip() == 'Thick':
                luntype = constants.THICK_LUNTYPE
            elif luntype.strip() == 'Thin':
                luntype = constants.THIN_LUNTYPE
        else:
            err_msg = (_(
                "LUNType config is wrong. LUNType must be 'Thin'"
                " or 'Thick'. LUNType: %(fetchtype)s.")
                % {'fetchtype': luntype})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)
    else:
        luntype = constants.THICK_LUNTYPE
    return luntype


def encode_name(name):
    uuid_str = name.replace("-", "")
    vol_uuid = uuid.UUID('urn:uuid:%s' % uuid_str)
    vol_encoded = base64.urlsafe_b64encode(vol_uuid.bytes)
    vol_encoded = vol_encoded.decode("utf-8")  # Make it compatible to py3.
    newuuid = vol_encoded.replace("=", "")
    return newuuid


def init_lun_parameters(name, parameters):
    """Initialize basic LUN parameters."""
    lunparam = {"TYPE": "11",
                "NAME": name,
                "PARENTTYPE": "216",
                "PARENTID": parameters['pool_id'],
                "DESCRIPTION": parameters['volume_description'],
                "ALLOCTYPE": parameters['LUNType'],
                "CAPACITY": parameters['volume_size'],
                "WRITEPOLICY": parameters['WriteType'],
                "MIRRORPOLICY": parameters['MirrorSwitch'],
                "PREFETCHPOLICY": parameters['PrefetchType'],
                "PREFETCHVALUE": parameters['PrefetchValue'],
                "DATATRANSFERPOLICY": parameters['policy'],
                "READCACHEPOLICY": parameters['readcachepolicy'],
                "WRITECACHEPOLICY": parameters['writecachepolicy'],
                }

    return lunparam


def volume_in_use(volume):
    """Check if the given volume is in use."""
    return (volume['volume_attachment'] and
            len(volume['volume_attachment']) > 0)


def get_wait_interval(xml_file_path, event_type):
    """Get wait interval from huawei conf file."""
    root = parse_xml_file(xml_file_path)
    wait_interval = root.findtext('LUN/%s' % event_type)
    if wait_interval is None:
        wait_interval = constants.DEFAULT_WAIT_INTERVAL
        LOG.info(_LI(
            "Wait interval for %(event_type)s is not configured in huawei "
            "conf file. Use default: %(default_wait_interval)d."),
            {"event_type": event_type,
             "default_wait_interval": wait_interval})

    return int(wait_interval)


def get_default_timeout(xml_file_path):
    """Get timeout from huawei conf file."""
    root = parse_xml_file(xml_file_path)
    timeout = root.findtext('LUN/Timeout')
    if timeout is None:
        timeout = constants.DEFAULT_WAIT_TIMEOUT
        LOG.info(_LI(
            "Timeout is not configured in huawei conf file. "
            "Use default: %(default_timeout)d."),
            {"default_timeout": timeout})

    return timeout


def wait_for_condition(xml_file_path, func, interval, timeout=None):
    start_time = time.time()
    if timeout is None:
        timeout = get_default_timeout(xml_file_path)

    def _inner():
        try:
            res = func()
        except Exception as ex:
            raise exception.VolumeBackendAPIException(data=ex)
        if res:
            raise loopingcall.LoopingCallDone()

        if int(time.time()) - start_time > timeout:
            msg = (_('wait_for_condition: %s timed out.')
                   % func.__name__)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    timer = loopingcall.FixedIntervalLoopingCall(_inner)
    timer.start(interval=interval).wait()


def get_login_info(xml_file_path):
    """Get login IP, user name and password from config file."""
    login_info = {}
    root = parse_xml_file(xml_file_path)

    login_info['RestURL'] = root.findtext('Storage/RestURL').strip()

    for key in ['UserName', 'UserPassword']:
        node = root.find('Storage/%s' % key)
        node_text = node.text
        login_info[key] = node_text

    return login_info


def _change_file_mode(filepath):
    utils.execute('chmod', '640', filepath, run_as_root=True)


def get_iscsi_conf(xml_file_path):
    """Get iSCSI info from config file."""
    iscsiinfo = {}
    root = parse_xml_file(xml_file_path)
    target_ip = root.findtext('iSCSI/DefaultTargetIP').strip()
    iscsiinfo['DefaultTargetIP'] = target_ip
    initiator_list = []

    for dic in root.findall('iSCSI/Initiator'):
        # Strip values of dict.
        tmp_dic = {}
        for k in dic.items():
            tmp_dic[k[0]] = k[1].strip()

        initiator_list.append(tmp_dic)

    iscsiinfo['Initiator'] = initiator_list

    return iscsiinfo


def check_qos_high_priority(qos):
    """Check QoS priority."""
    for key, value in qos.items():
        if (key.find('MIN') == 0) or (key.find('LATENCY') == 0):
            return True

    return False


def check_conf_file(xml_file_path):
    """Check the config file, make sure the essential items are set."""
    root = parse_xml_file(xml_file_path)
    resturl = root.findtext('Storage/RestURL')
    username = root.findtext('Storage/UserName')
    pwd = root.findtext('Storage/UserPassword')
    pool_node = root.findall('LUN/StoragePool')

    if (not resturl) or (not username) or (not pwd):
        err_msg = (_(
            'check_conf_file: Config file invalid. RestURL,'
            ' UserName and UserPassword must be set.'))
        LOG.error(err_msg)
        raise exception.InvalidInput(reason=err_msg)

    if not pool_node:
        err_msg = (_(
            'check_conf_file: Config file invalid. '
            'StoragePool must be set.'))
        LOG.error(err_msg)
        raise exception.InvalidInput(reason=err_msg)


def get_volume_size(volume):
    """Calculate the volume size.

    We should divide the given volume size by 512 for the 18000 system
    calculates volume size with sectors, which is 512 bytes.
    """
    volume_size = units.Gi / 512  # 1G
    if int(volume['size']) != 0:
        volume_size = int(volume['size']) * units.Gi / 512

    return volume_size


def get_protocol(xml_file_path):
    """Get protocol from huawei conf file."""
    root = parse_xml_file(xml_file_path)
    protocol = root.findtext('Storage/Protocol')
    if not protocol:
        err_msg = (_('Get protocol from huawei conf file error.'))
        LOG.error(err_msg)
        raise exception.InvalidInput(reason=err_msg)

    return protocol


def get_pools(xml_file_path):
    """Get pools from huawei conf file."""
    root = parse_xml_file(xml_file_path)
    pool_names = root.findtext('LUN/StoragePool')
    if not pool_names:
        msg = _('Invalid resource pool name. '
                'Please check the config file.')
        LOG.error(msg)
        raise exception.InvalidInput(msg)
    return pool_names


def get_remote_device_info(valid_hypermetro_devices):
    remote_device_info = {}
    try:
        if valid_hypermetro_devices:
            remote_device_info = json.loads(valid_hypermetro_devices)
        else:
            return

    except ValueError as err:
        msg = _("Get remote device info error. %s.") % err
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    if len(remote_device_info) == 1:
        for device_key, device_value in remote_device_info.items():
            return remote_device_info.get(device_key)


def get_volume_metadata(volume):
    if 'volume_metadata' in volume:
        metadata = volume.get('volume_metadata')
        return {item['key']: item['value'] for item in metadata}

    return {}
