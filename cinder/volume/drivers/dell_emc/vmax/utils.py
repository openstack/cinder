# Copyright (c) 2017 Dell Inc. or its subsidiaries.
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

from copy import deepcopy
import datetime
import hashlib
import random
import re
from xml.dom import minidom

from cinder.objects.group import Group
from oslo_log import log as logging
from oslo_utils import strutils
import six

from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)
# SHARED CONSTANTS
ISCSI = 'iscsi'
FC = 'fc'
INTERVAL = 'interval'
RETRIES = 'retries'
VOLUME_ELEMENT_NAME_PREFIX = 'OS-'
MAX_SRP_LENGTH = 16
TRUNCATE_5 = 5
TRUNCATE_27 = 27

ARRAY = 'array'
SLO = 'slo'
WORKLOAD = 'workload'
SRP = 'srp'
PORTGROUPNAME = 'storagetype:portgroupname'
DEVICE_ID = 'device_id'
INITIATOR_CHECK = 'initiator_check'
SG_NAME = 'storagegroup_name'
MV_NAME = 'maskingview_name'
IG_NAME = 'init_group_name'
PARENT_SG_NAME = 'parent_sg_name'
CONNECTOR = 'connector'
VOL_NAME = 'volume_name'
EXTRA_SPECS = 'extra_specs'
IS_RE = 'replication_enabled'
DISABLECOMPRESSION = 'storagetype:disablecompression'


class VMAXUtils(object):
    """Utility class for Rest based VMAX volume drivers.

    This Utility class is for VMAX volume drivers based on Unisphere Rest API.
    """

    def __init__(self):
        """Utility class for Rest based VMAX volume drivers."""

    def get_host_short_name(self, host_name):
        """Returns the short name for a given qualified host name.

        Checks the host name to see if it is the fully qualified host name
        and returns part before the dot. If there is no dot in the host name
        the full host name is returned.
        :param host_name: the fully qualified host name
        :returns: string -- the short host_name
        """
        host_array = host_name.split('.')
        if len(host_array) > 1:
            short_host_name = host_array[0]
        else:
            short_host_name = host_name

        return self.generate_unique_trunc_host(short_host_name)

    @staticmethod
    def get_volumetype_extra_specs(volume, volume_type_id=None):
        """Gets the extra specs associated with a volume type.

        :param volume: the volume dictionary
        :param volume_type_id: Optional override for volume.volume_type_id
        :returns: dict -- extra_specs - the extra specs
        :raises: VolumeBackendAPIException
        """
        extra_specs = {}

        try:
            if volume_type_id:
                type_id = volume_type_id
            else:
                type_id = volume.volume_type_id
            if type_id is not None:
                extra_specs = volume_types.get_volume_type_extra_specs(type_id)
        except Exception as e:
            LOG.debug('Exception getting volume type extra specs: %(e)s',
                      {'e': six.text_type(e)})
        return extra_specs

    @staticmethod
    def get_short_protocol_type(protocol):
        """Given the protocol type, return I for iscsi and F for fc.

        :param protocol: iscsi or fc
        :returns: string -- 'I' for iscsi or 'F' for fc
        """
        if protocol.lower() == ISCSI.lower():
            return 'I'
        elif protocol.lower() == FC.lower():
            return 'F'
        else:
            return protocol

    @staticmethod
    def truncate_string(str_to_truncate, max_num):
        """Truncate a string by taking first and last characters.

        :param str_to_truncate: the string to be truncated
        :param max_num: the maximum number of characters
        :returns: string -- truncated string or original string
        """
        if len(str_to_truncate) > max_num:
            new_num = len(str_to_truncate) - max_num // 2
            first_chars = str_to_truncate[:max_num // 2]
            last_chars = str_to_truncate[new_num:]
            str_to_truncate = first_chars + last_chars
        return str_to_truncate

    @staticmethod
    def get_time_delta(start_time, end_time):
        """Get the delta between start and end time.

        :param start_time: the start time
        :param end_time: the end time
        :returns: string -- delta in string H:MM:SS
        """
        delta = end_time - start_time
        return six.text_type(datetime.timedelta(seconds=int(delta)))

    @staticmethod
    def get_default_storage_group_name(
            srp_name, slo, workload, is_compression_disabled=False,
            is_re=False):
        """Determine default storage group from extra_specs.

        :param srp_name: the name of the srp on the array
        :param slo: the service level string e.g Bronze
        :param workload: the workload string e.g DSS
        :param is_compression_disabled:  flag for disabling compression
        :param is_re: flag for replication
        :returns: storage_group_name
        """
        if slo and workload:
            prefix = ("OS-%(srpName)s-%(slo)s-%(workload)s"
                      % {'srpName': srp_name, 'slo': slo,
                         'workload': workload})

            if is_compression_disabled:
                prefix += "-CD"

        else:
            prefix = "OS-no_SLO"
        if is_re:
            prefix += "-RE"

        storage_group_name = ("%(prefix)s-SG" % {'prefix': prefix})
        return storage_group_name

    @staticmethod
    def get_volume_element_name(volume_id):
        """Get volume element name follows naming convention, i.e. 'OS-UUID'.

        :param volume_id: Openstack volume ID containing uuid
        :returns: volume element name in format of OS-UUID
        """
        element_name = volume_id
        uuid_regex = (re.compile(
            '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',
            re.I))
        match = uuid_regex.search(volume_id)
        if match:
            volume_uuid = match.group()
            element_name = ("%(prefix)s%(volumeUUID)s"
                            % {'prefix': VOLUME_ELEMENT_NAME_PREFIX,
                               'volumeUUID': volume_uuid})
            LOG.debug(
                "get_volume_element_name elementName:  %(elementName)s.",
                {'elementName': element_name})
        return element_name

    def generate_unique_trunc_host(self, host_name):
        """Create a unique short host name under 16 characters.

        :param host_name: long host name
        :returns: truncated host name
        """
        if host_name and len(host_name) > 16:
            host_name = host_name.lower()
            m = hashlib.md5()
            m.update(host_name.encode('utf-8'))
            uuid = m.hexdigest()
            new_name = ("%(host)s%(uuid)s"
                        % {'host': host_name[-6:],
                           'uuid': uuid})
            host_name = self.truncate_string(new_name, 16)
        return host_name

    def get_pg_short_name(self, portgroup_name):
        """Create a unique port group name under 12 characters.

        :param portgroup_name: long portgroup_name
        :returns: truncated portgroup_name
        """
        if portgroup_name and len(portgroup_name) > 12:
            portgroup_name = portgroup_name.lower()
            m = hashlib.md5()
            m.update(portgroup_name.encode('utf-8'))
            uuid = m.hexdigest()
            new_name = ("%(pg)s%(uuid)s"
                        % {'pg': portgroup_name[-6:],
                           'uuid': uuid})
            portgroup_name = self.truncate_string(new_name, 12)
        return portgroup_name

    @staticmethod
    def get_default_oversubscription_ratio(max_over_sub_ratio):
        """Override ratio if necessary.

        The over subscription ratio will be overridden if the user supplied
        max oversubscription ratio is less than 1.
        :param max_over_sub_ratio: user supplied over subscription ratio
        :returns: max_over_sub_ratio
        """
        if max_over_sub_ratio < 1.0:
            LOG.info("The user supplied value for max_over_subscription "
                     "ratio is less than 1.0. Using the default value of "
                     "20.0 instead...")
            max_over_sub_ratio = 20.0
        return max_over_sub_ratio

    @staticmethod
    def _process_tag(element, tag_name):
        """Process the tag to get the value.

        :param element: the parent element
        :param tag_name: the tag name
        :returns: nodeValue(can be None)
        """
        node_value = None
        try:
            processed_element = element.getElementsByTagName(tag_name)[0]
            node_value = processed_element.childNodes[0].nodeValue
            if node_value:
                node_value = node_value.strip()
        except IndexError:
            pass
        return node_value

    def _get_connection_info(self, rest_element):
        """Given the filename get the rest server connection details.

        :param rest_element: the rest element
        :returns: dict -- connargs - the connection info dictionary
        :raises: VolumeBackendAPIException
        """
        connargs = {
            'RestServerIp': (
                self._process_tag(rest_element, 'RestServerIp')),
            'RestServerPort': (
                self._process_tag(rest_element, 'RestServerPort')),
            'RestUserName': (
                self._process_tag(rest_element, 'RestUserName')),
            'RestPassword': (
                self._process_tag(rest_element, 'RestPassword'))}

        for k, __ in connargs.items():
            if connargs[k] is None:
                exception_message = (_(
                    "RestServerIp, RestServerPort, RestUserName, "
                    "RestPassword must have valid values."))
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        # These can be None
        connargs['SSLCert'] = self._process_tag(rest_element, 'SSLCert')
        connargs['SSLVerify'] = (
            self._process_tag(rest_element, 'SSLVerify'))

        return connargs

    def parse_file_to_get_array_map(self, file_name):
        """Parses a file and gets array map.

        Given a file, parse it to get array and pool(srp).

        .. code:: ini

          <EMC>
          <RestServerIp>10.108.246.202</RestServerIp>
          <RestServerPort>8443</RestServerPort>
          <RestUserName>smc</RestUserName>
          <RestPassword>smc</RestPassword>
          <SSLCert>/path/client.cert</SSLCert>
          <SSLVerify>/path/to/certfile.pem</SSLVerify>
          <PortGroups>
              <PortGroup>OS-PORTGROUP1-PG</PortGroup>
          </PortGroups>
          <Array>000198700439</Array>
          <SRP>SRP_1</SRP>
          </EMC>

        :param file_name: the configuration file
        :returns: list
        """
        kwargs = {}
        my_file = open(file_name, 'r')
        data = my_file.read()
        my_file.close()
        dom = minidom.parseString(data)
        try:
            connargs = self._get_connection_info(dom)
            portgroup = self._get_random_portgroup(dom)
            serialnumber = self._process_tag(dom, 'Array')
            if serialnumber is None:
                LOG.error("Array Serial Number must be in the file %(file)s.",
                          {'file': file_name})
            srp_name = self._process_tag(dom, 'SRP')
            if srp_name is None:
                LOG.error("SRP Name must be in the file %(file)s.",
                          {'file': file_name})
            slo = self._process_tag(dom, 'ServiceLevel')
            workload = self._process_tag(dom, 'Workload')
            kwargs = (
                {'RestServerIp': connargs['RestServerIp'],
                 'RestServerPort': connargs['RestServerPort'],
                 'RestUserName': connargs['RestUserName'],
                 'RestPassword': connargs['RestPassword'],
                 'SSLCert': connargs['SSLCert'],
                 'SSLVerify': connargs['SSLVerify'],
                 'SerialNumber': serialnumber,
                 'srpName': srp_name,
                 'PortGroup': portgroup})
            if slo is not None:
                kwargs.update({'ServiceLevel': slo, 'Workload': workload})

        except IndexError:
            pass
        return kwargs

    @staticmethod
    def _get_random_portgroup(element):
        """Randomly choose a portgroup from list of portgroups.

        :param element: the parent element
        :returns: the randomly chosen port group
        """
        portgroupelements = element.getElementsByTagName('PortGroup')
        if portgroupelements and len(portgroupelements) > 0:
            portgroupnames = [portgroupelement.childNodes[0].nodeValue.strip()
                              for portgroupelement in portgroupelements
                              if portgroupelement.childNodes]
            portgroupnames = list(set(filter(None, portgroupnames)))
            pg_len = len(portgroupnames)
            if pg_len > 0:
                return portgroupnames[random.randint(0, pg_len - 1)]
        return None

    def get_temp_snap_name(self, clone_name, source_device_id):
        """Construct a temporary snapshot name for clone operation.

        :param clone_name: the name of the clone
        :param source_device_id: the source device id
        :returns: snap_name
        """
        trunc_clone = self.truncate_string(clone_name, 10)
        snap_name = ("temp-%(device)s-%(clone)s"
                     % {'device': source_device_id, 'clone': trunc_clone})
        return snap_name

    @staticmethod
    def get_array_and_device_id(volume, external_ref):
        """Helper function for manage volume to get array name and device ID.

        :param volume: volume object from API
        :param external_ref: the existing volume object to be manged
        :returns: string value of the array name and device ID
        """
        device_id = external_ref.get(u'source-name', None)
        LOG.debug("External_ref: %(er)s", {'er': external_ref})
        if not device_id:
            device_id = external_ref.get(u'source-id', None)
        host = volume.host
        host_list = host.split('+')
        array = host_list[(len(host_list) - 1)]

        if device_id:
            LOG.debug("Get device ID of existing volume - device ID: "
                      "%(device_id)s, Array: %(array)s.",
                      {'device_id': device_id,
                       'array': array})
        else:
            exception_message = (_("Source volume device ID is required."))
            raise exception.VolumeBackendAPIException(
                data=exception_message)
        return array, device_id

    @staticmethod
    def is_compression_disabled(extra_specs):
        """Check is compression is to be disabled.

        :param extra_specs: extra specifications
        :returns: boolean
        """
        do_disable_compression = False
        if DISABLECOMPRESSION in extra_specs:
            if strutils.bool_from_string(extra_specs[DISABLECOMPRESSION]):
                do_disable_compression = True
        return do_disable_compression

    def change_compression_type(self, is_source_compr_disabled, new_type):
        """Check if volume type have different compression types

        :param is_source_compr_disabled: from source
        :param new_type: from target
        :returns: boolean
        """
        extra_specs = new_type['extra_specs']
        is_target_compr_disabled = self.is_compression_disabled(extra_specs)
        if is_target_compr_disabled == is_source_compr_disabled:
            return False
        else:
            return True

    @staticmethod
    def is_replication_enabled(extra_specs):
        """Check if replication is to be enabled.

        :param extra_specs: extra specifications
        :returns: bool - true if enabled, else false
        """
        replication_enabled = False
        if IS_RE in extra_specs:
            replication_enabled = True
        return replication_enabled

    def get_replication_config(self, rep_device_list):
        """Gather necessary replication configuration info.

        :param rep_device_list: the replication device list from cinder.conf
        :returns: rep_config, replication configuration dict
        """
        rep_config = {}
        if not rep_device_list:
            return None
        else:
            target = rep_device_list[0]
            try:
                rep_config['array'] = target['target_device_id']
                rep_config['srp'] = target['remote_pool']
                rep_config['rdf_group_label'] = target['rdf_group_label']
                rep_config['portgroup'] = target['remote_port_group']

            except KeyError as ke:
                error_message = (_("Failed to retrieve all necessary SRDF "
                                   "information. Error received: %(ke)s.") %
                                 {'ke': six.text_type(ke)})
                LOG.exception(error_message)
                raise exception.VolumeBackendAPIException(data=error_message)

            try:
                allow_extend = target['allow_extend']
                if strutils.bool_from_string(allow_extend):
                    rep_config['allow_extend'] = True
                else:
                    rep_config['allow_extend'] = False
            except KeyError:
                rep_config['allow_extend'] = False

        return rep_config

    @staticmethod
    def is_volume_failed_over(volume):
        """Check if a volume has been failed over.

        :param volume: the volume object
        :returns: bool
        """
        if volume is not None:
            if volume.get('replication_status') and (
                volume.replication_status ==
                    fields.ReplicationStatus.FAILED_OVER):
                    return True
        return False

    @staticmethod
    def update_volume_model_updates(volume_model_updates,
                                    volumes, group_id, status='available'):
        """Update the volume model's status and return it.

        :param volume_model_updates: list of volume model update dicts
        :param volumes: volumes object api
        :param group_id: consistency group id
        :param status: string value reflects the status of the member volume
        :returns: volume_model_updates - updated volumes
        """
        LOG.info(
            "Updating status for group: %(id)s.",
            {'id': group_id})
        if volumes:
            for volume in volumes:
                volume_model_updates.append({'id': volume.id,
                                             'status': status})
        else:
            LOG.info("No volume found for group: %(cg)s.",
                     {'cg': group_id})
        return volume_model_updates

    @staticmethod
    def update_extra_specs(extraspecs):
        """Update extra specs.

        :param extraspecs: the additional info
        :returns: extraspecs
        """
        try:
            pool_details = extraspecs['pool_name'].split('+')
            extraspecs[SLO] = pool_details[0]
            extraspecs[WORKLOAD] = pool_details[1]
            extraspecs[SRP] = pool_details[2]
            extraspecs[ARRAY] = pool_details[3]
        except KeyError:
            LOG.error("Error parsing SLO, workload from"
                      " the provided extra_specs.")
        return extraspecs

    @staticmethod
    def get_intervals_retries_dict(interval, retries):
        """Get the default intervals and retries.

        :param interval: Interval in seconds between retries
        :param retries: Retry count
        :returns: default_dict
        """
        default_dict = {}
        default_dict[INTERVAL] = interval
        default_dict[RETRIES] = retries
        return default_dict

    @staticmethod
    def update_admin_metadata(volumes_model_update, key, values):
        """Update the volume_model_updates with admin metadata.

        :param volumes_model_update: List of volume model updates
        :param key: Key to be updated in the admin_metadata
        :param values: Dictionary of values per volume id
        """
        for volume_model_update in volumes_model_update:
            volume_id = volume_model_update['id']
            if volume_id in values:
                admin_metadata = {}
                admin_metadata.update({key: values[volume_id]})
                volume_model_update.update(
                    {'admin_metadata': admin_metadata})

    def get_volume_group_utils(self, group, interval, retries):
        """Standard utility for generic volume groups.

        :param group: the generic volume group object to be created
        :param interval: Interval in seconds between retries
        :param retries: Retry count
        :returns: array, extra specs dict list
        :raises: VolumeBackendAPIException
        """
        arrays = set()
        extraspecs_dict_list = []
        # Check if it is a generic volume group instance
        if isinstance(group, Group):
            for volume_type in group.volume_types:
                extraspecs_dict = (
                    self._update_extra_specs_list(
                        volume_type.extra_specs,
                        volume_type.id, interval, retries))
                extraspecs_dict_list.append(extraspecs_dict)
                arrays.add(extraspecs_dict[EXTRA_SPECS][ARRAY])
        else:
            msg = (_("Unable to get volume type ids."))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if len(arrays) != 1:
            if not arrays:
                msg = (_("Failed to get an array associated with "
                         "volume group: %(groupid)s.")
                       % {'groupid': group.id})
            else:
                msg = (_("There are multiple arrays "
                         "associated with volume group: %(groupid)s.")
                       % {'groupid': group.id})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        array = arrays.pop()
        return array, extraspecs_dict_list

    def _update_extra_specs_list(self, extraspecs, volumetype_id,
                                 interval, retries):
        """Update the extra specs list.

        :param extraspecs: extraspecs
        :param volumetype_Id: volume type identifier
        :param interval: Interval in seconds between retries
        :param retries: Retry count
        :returns: extraspecs_dict_list
        """
        extraspecs_dict = {}
        extraspecs = self.update_extra_specs(extraspecs)
        extraspecs = self._update_intervals_and_retries(
            extraspecs, interval, retries)
        extraspecs_dict["volumeTypeId"] = volumetype_id
        extraspecs_dict[EXTRA_SPECS] = extraspecs
        return extraspecs_dict

    def update_volume_group_name(self, group):
        """Format id and name consistency group.

        :param group: the generic volume group object
        :returns: group_name -- formatted name + id
        """
        group_name = ""
        if group.name is not None:
            group_name = (
                self.truncate_string(
                    group.name, TRUNCATE_27) + "_")

        group_name += group.id
        return group_name

    @staticmethod
    def _update_intervals_and_retries(extra_specs, interval, retries):
        """Updates the extraSpecs with intervals and retries values.

        :param extra_specs:
        :param interval: Interval in seconds between retries
        :param retries: Retry count
        :returns: Updated extra_specs
        """
        extra_specs[INTERVAL] = interval
        LOG.debug("The interval is set at: %(intervalInSecs)s.",
                  {'intervalInSecs': interval})
        extra_specs[RETRIES] = retries
        LOG.debug("Retries are set at: %(retries)s.",
                  {'retries': retries})
        return extra_specs

    @staticmethod
    def add_legacy_pools(pools):
        """Add legacy pools to allow extending a volume after upgrade.

        :param pools: the pool list
        :return: pools - the updated pool list
        """
        extra_pools = []
        for pool in pools:
            if 'none' in pool['pool_name'].lower():
                extra_pools.append(pool)
        for pool in extra_pools:
            slo = pool['pool_name'].split('+')[0]
            srp = pool['pool_name'].split('+')[2]
            array = pool['pool_name'].split('+')[3]
            new_pool_name = ('%(slo)s+%(srp)s+%(array)s'
                             % {'slo': slo, 'srp': srp, 'array': array})
            new_pool = deepcopy(pool)
            new_pool['pool_name'] = new_pool_name
            pools.append(new_pool)
        return pools
