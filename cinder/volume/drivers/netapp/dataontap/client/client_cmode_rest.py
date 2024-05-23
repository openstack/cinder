# Copyright (c) 2022 NetApp, Inc. All rights reserved.
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

import copy
from datetime import datetime
from datetime import timedelta
import math
from time import time

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)
DEFAULT_MAX_PAGE_LENGTH = 10000
ONTAP_SELECT_MODEL = 'FDvM300'
ONTAP_C190 = 'C190'
HTTP_ACCEPTED = 202
DELETED_PREFIX = 'deleted_cinder_'
DEFAULT_TIMEOUT = 15
REST_SYNC_TIMEOUT = 15

# Keys in this map are REST API's endpoints that the user shall have permission
# in order to enable extra specs reported to Cinder's scheduler.
# NOTE(sfernand): ONTAP does not retrieve volume efficiency information
# properly when using the pre-created "vsadmin" role (SVM scoped), causing
# dedup and compression extra specs to be reported as disabled despite its
# current configuration.
SSC_API_MAP = {
    '/storage/aggregates': [
        'netapp_raid_type',
    ],
    '/storage/disks': [
        'netapp_disk_type',
    ],
    '/snapmirror/relationships': [
        'netapp_mirrored',
    ],
    '/storage/volumes': [
        'netapp_flexvol_encryption'
        'netapp_dedup',
        'netapp_compression',
    ],
}


class RestClient(object, metaclass=volume_utils.TraceWrapperMetaclass):

    def __init__(self, **kwargs):

        host = kwargs['hostname']
        username = kwargs['username']
        password = kwargs['password']
        api_trace_pattern = kwargs['api_trace_pattern']
        self.connection = netapp_api.RestNaServer(
            host=host,
            transport_type=kwargs['transport_type'],
            ssl_cert_path=kwargs.pop('ssl_cert_path'),
            port=kwargs['port'],
            username=username,
            password=password,
            api_trace_pattern=api_trace_pattern)

        self.async_rest_timeout = kwargs.get('async_rest_timeout', 60)

        self.vserver = kwargs.get('vserver')
        self.connection.set_vserver(self.vserver)

        ontap_version = self.get_ontap_version(cached=False)
        if ontap_version < (9, 11, 1):
            msg = _('REST Client can be used only with ONTAP 9.11.1 or upper.')
            raise na_utils.NetAppDriverException(msg)
        self.connection.set_ontap_version(ontap_version)

        self.ssh_client = self._init_ssh_client(host, username, password)

        # NOTE(nahimsouza): ZAPI Client is needed to implement the fallback
        # when a REST method is not supported.
        self.zapi_client = client_cmode.Client(**kwargs)

        self._init_features()

    def _init_ssh_client(self, host, username, password):
        return netapp_api.SSHUtil(
            host=host,
            username=username,
            password=password)

    def _init_features(self):
        self.features = na_utils.Features()

        generation, major, minor = self.get_ontap_version()
        ontap_version = (generation, major)

        ontap_9_0 = ontap_version >= (9, 0)
        ontap_9_4 = ontap_version >= (9, 4)
        ontap_9_5 = ontap_version >= (9, 5)
        ontap_9_6 = ontap_version >= (9, 6)
        ontap_9_8 = ontap_version >= (9, 8)
        ontap_9_9 = ontap_version >= (9, 9)

        nodes_info = self._get_cluster_nodes_info()
        for node in nodes_info:
            qos_min_block = False
            qos_min_nfs = False
            if node['model'] == ONTAP_SELECT_MODEL:
                qos_min_block = node['is_all_flash_select'] and ontap_9_6
                qos_min_nfs = qos_min_block
            elif ONTAP_C190 in node['model']:
                qos_min_block = node['is_all_flash'] and ontap_9_6
                qos_min_nfs = qos_min_block
            else:
                qos_min_block = node['is_all_flash'] and ontap_9_0
                qos_min_nfs = node['is_all_flash'] and ontap_9_0

            qos_name = na_utils.qos_min_feature_name(True, node['name'])
            self.features.add_feature(qos_name, supported=qos_min_nfs)
            qos_name = na_utils.qos_min_feature_name(False, node['name'])
            self.features.add_feature(qos_name, supported=qos_min_block)

        self.features.add_feature('SNAPMIRROR_V2', supported=ontap_9_0)
        self.features.add_feature('USER_CAPABILITY_LIST',
                                  supported=ontap_9_0)
        self.features.add_feature('SYSTEM_METRICS', supported=ontap_9_0)
        self.features.add_feature('CLONE_SPLIT_STATUS', supported=ontap_9_0)
        self.features.add_feature('FAST_CLONE_DELETE', supported=ontap_9_0)
        self.features.add_feature('SYSTEM_CONSTITUENT_METRICS',
                                  supported=ontap_9_0)
        self.features.add_feature('ADVANCED_DISK_PARTITIONING',
                                  supported=ontap_9_0)
        self.features.add_feature('BACKUP_CLONE_PARAM', supported=ontap_9_0)
        self.features.add_feature('CLUSTER_PEER_POLICY', supported=ontap_9_0)
        self.features.add_feature('FLEXVOL_ENCRYPTION', supported=ontap_9_0)
        self.features.add_feature('FLEXGROUP', supported=ontap_9_8)
        self.features.add_feature('FLEXGROUP_CLONE_FILE',
                                  supported=ontap_9_9)

        self.features.add_feature('ADAPTIVE_QOS', supported=ontap_9_4)
        self.features.add_feature('ADAPTIVE_QOS_BLOCK_SIZE',
                                  supported=ontap_9_5)
        self.features.add_feature('ADAPTIVE_QOS_EXPECTED_IOPS_ALLOCATION',
                                  supported=ontap_9_5)

        LOG.info('ONTAP Version: %(generation)s.%(major)s.%(minor)s',
                 {'generation': ontap_version[0], 'major': ontap_version[1],
                  'minor': minor})

    def __getattr__(self, name):
        """If method is not implemented for REST, try to call the ZAPI."""
        LOG.debug("The %s call is not supported for REST, falling back to "
                  "ZAPI.", name)
        # Don't use self.zapi_client to avoid reentrant call to __getattr__()
        zapi_client = object.__getattribute__(self, 'zapi_client')
        return getattr(zapi_client, name)

    def _wait_job_result(self, job_url):
        """Waits for a job to finish."""

        interval = 2
        retries = (self.async_rest_timeout / interval)

        @utils.retry(netapp_api.NaRetryableError, interval=interval,
                     retries=retries, backoff_rate=1)
        def _waiter():
            response = self.send_request(job_url, 'get',
                                         enable_tunneling=False)

            job_state = response.get('state')
            if job_state == 'success':
                return response
            elif job_state == 'failure':
                message = response['error']['message']
                code = response['error']['code']
                raise netapp_api.NaApiError(message=message, code=code)

            msg_args = {'job': job_url, 'state': job_state}
            LOG.debug("Job %(job)s has not finished: %(state)s", msg_args)
            raise netapp_api.NaRetryableError(message='Job is running.')

        try:
            return _waiter()
        except netapp_api.NaRetryableError:
            msg = _("Job %s did not reach the expected state. Retries "
                    "exhausted. Aborting.") % job_url
            raise na_utils.NetAppDriverException(msg)

    def send_request(self, action_url, method, body=None, query=None,
                     enable_tunneling=True,
                     max_page_length=DEFAULT_MAX_PAGE_LENGTH,
                     wait_on_accepted=True):

        """Sends REST request to ONTAP.

        :param action_url: action URL for the request
        :param method: HTTP method for the request ('get', 'post', 'put',
            'delete' or 'patch')
        :param body: dict of arguments to be passed as request body
        :param query: dict of arguments to be passed as query string
        :param enable_tunneling: enable tunneling to the ONTAP host
        :param max_page_length: size of the page during pagination
        :param wait_on_accepted: if True, wait until the job finishes when
            HTTP code 202 (Accepted) is returned

        :returns: parsed REST response
        """

        response = None

        if method == 'get':
            response = self.get_records(
                action_url, query, enable_tunneling, max_page_length)
        else:
            code, response = self.connection.invoke_successfully(
                action_url, method, body=body, query=query,
                enable_tunneling=enable_tunneling)

            if code == HTTP_ACCEPTED and wait_on_accepted:
                # get job URL and discard '/api'
                job_url = response['job']['_links']['self']['href'][4:]
                response = self._wait_job_result(job_url)

        return response

    def get_records(self, action_url, query=None, enable_tunneling=True,
                    max_page_length=DEFAULT_MAX_PAGE_LENGTH):
        """Retrieves ONTAP resources using pagination REST request.

        :param action_url: action URL for the request
        :param query: dict of arguments to be passed as query string
        :param enable_tunneling: enable tunneling to the ONTAP host
        :param max_page_length: size of the page during pagination

        :returns: dict containing records and num_records
        """

        # Initialize query variable if it is None
        query = query if query else {}
        query['max_records'] = max_page_length

        _, response = self.connection.invoke_successfully(
            action_url, 'get', query=query,
            enable_tunneling=enable_tunneling)

        # NOTE(nahimsouza): if all records are returned in the first call,
        # 'next_url' will be None.
        next_url = response.get('_links', {}).get('next', {}).get('href')
        next_url = next_url[4:] if next_url else None  # discard '/api'

        # Get remaining pages, saving data into first page
        while next_url:
            # NOTE(nahimsouza): clean the 'query', because the parameters are
            # already included in 'next_url'.
            _, next_response = self.connection.invoke_successfully(
                next_url, 'get', query=None,
                enable_tunneling=enable_tunneling)

            response['num_records'] += next_response.get('num_records', 0)
            response['records'].extend(next_response.get('records'))

            next_url = (
                next_response.get('_links', {}).get('next', {}).get('href'))
            next_url = next_url[4:] if next_url else None  # discard '/api'

        return response

    def get_ontap_version(self, cached=True):
        """Gets the ONTAP version as tuple."""

        if cached:
            return self.connection.get_ontap_version()

        query = {
            'fields': 'version'
        }

        response = self.send_request('/cluster/', 'get', query=query)

        version = (response['version']['generation'],
                   response['version']['major'],
                   response['version']['minor'])

        return version

    def check_api_permissions(self):
        """Check which APIs that support SSC functionality are available."""

        inaccessible_apis = []
        invalid_extra_specs = []

        for api, extra_specs in SSC_API_MAP.items():
            if not self.check_cluster_api(api):
                inaccessible_apis.append(api)
                invalid_extra_specs.extend(extra_specs)

        if inaccessible_apis:
            if '/storage/volumes' in inaccessible_apis:
                msg = _('User not permitted to query Data ONTAP volumes.')
                raise exception.VolumeBackendAPIException(data=msg)
            else:
                LOG.warning('The configured user account does not have '
                            'sufficient privileges to use all needed '
                            'APIs. The following extra specs will fail '
                            'or be ignored: %s.', invalid_extra_specs)

        return invalid_extra_specs

    def check_cluster_api(self, api):
        """Checks the availability of a cluster API.

        Returns True if the specified cluster API exists and may be called by
        the current user.
        """
        try:
            # No need to return any records here since we just want to know if
            # the user is allowed to make the request. A "Permission Denied"
            # error code is expected in case user does not have the necessary
            # permissions.
            self.send_request('%s?return_records=false' % api, 'get',
                              enable_tunneling=False)
        except netapp_api.NaApiError as ex:
            # NOTE(nahimsouza): This function only returns false in case user
            # is not authorized. If other error is returned, it must be
            # handled in the function call that uses the same endpoint.
            if ex.code == netapp_api.REST_UNAUTHORIZED:
                return False

        return True

    def _get_cluster_nodes_info(self):
        """Return a list of models of the nodes in the cluster."""
        query_args = {'fields': 'model,'
                                'name,'
                                'is_all_flash_optimized,'
                                'is_all_flash_select_optimized'}

        nodes = []
        try:
            result = self.send_request('/cluster/nodes', 'get',
                                       query=query_args,
                                       enable_tunneling=False)

            for record in result['records']:
                node = {
                    'model': record['model'],
                    'name': record['name'],
                    'is_all_flash':
                        record['is_all_flash_optimized'],
                    'is_all_flash_select':
                        record['is_all_flash_select_optimized']
                }
                nodes.append(node)
        except netapp_api.NaApiError as e:
            if e.code == netapp_api.REST_UNAUTHORIZED:
                LOG.debug('Cluster nodes can only be collected with '
                          'cluster scoped credentials.')
            else:
                LOG.exception('Failed to get the cluster nodes.')

        return nodes

    def list_flexvols(self):
        """Returns the names of the flexvols on the controller."""

        query = {
            'type': 'rw',
            'style': 'flex*',  # Match both 'flexvol' and 'flexgroup'
            'is_svm_root': 'false',
            'error_state.is_inconsistent': 'false',
            'state': 'online',
            'fields': 'name'
        }

        response = self.send_request(
            '/storage/volumes/', 'get', query=query)

        records = response.get('records', [])
        volumes = [volume['name'] for volume in records]

        return volumes

    def _get_unique_volume(self, records):
        """Get the unique FlexVol or FlexGroup volume from a volume list."""
        if len(records) != 1:
            msg = _('Could not find unique volume. Volumes found: %(vol)s.')
            msg_args = {'vol': records}
            raise exception.VolumeBackendAPIException(data=msg % msg_args)

        return records[0]

    def _get_volume_by_args(self, vol_name=None, vol_path=None,
                            vserver=None, fields=None):
        """Get info from a single volume according to the args."""

        query = {
            'type': 'rw',
            'style': 'flex*',  # Match both 'flexvol' and 'flexgroup'
            'is_svm_root': 'false',
            'error_state.is_inconsistent': 'false',
            'state': 'online',
            'fields': 'name,style'
        }

        if vol_name:
            query['name'] = vol_name
        if vol_path:
            query['nas.path'] = vol_path
        if vserver:
            query['svm.name'] = vserver
        if fields:
            query['fields'] = fields

        volumes_response = self.send_request(
            '/storage/volumes/', 'get', query=query)

        records = volumes_response.get('records', [])
        volume = self._get_unique_volume(records)
        return volume

    def get_flexvol(self, flexvol_path=None, flexvol_name=None):
        """Get flexvol attributes needed for the storage service catalog."""

        fields = ('aggregates.name,name,svm.name,nas.path,'
                  'type,guarantee.honored,guarantee.type,'
                  'space.snapshot.reserve_percent,space.size,'
                  'qos.policy.name,snapshot_policy,language,style')
        unique_volume = self._get_volume_by_args(
            vol_name=flexvol_name, vol_path=flexvol_path, fields=fields)

        aggregate = None
        if unique_volume['style'] == 'flexvol':
            # flexvol has only 1 aggregate
            aggregate = [unique_volume['aggregates'][0]['name']]
        else:
            aggregate = [aggr["name"]
                         for aggr in unique_volume.get('aggregates', [])]

        qos_policy_group = (
            unique_volume.get('qos', {}).get('policy', {}).get('name'))

        volume = {
            'name': unique_volume['name'],
            'vserver': unique_volume['svm']['name'],
            'junction-path': unique_volume.get('nas', {}).get('path'),
            'aggregate': aggregate,
            'type': unique_volume['type'],
            'space-guarantee-enabled': unique_volume['guarantee']['honored'],
            'space-guarantee': unique_volume['guarantee']['type'],
            'percentage-snapshot-reserve':
                str(unique_volume['space']['snapshot']['reserve_percent']),
            'size': str(unique_volume['space']['size']),
            'qos-policy-group': qos_policy_group,
            'snapshot-policy': unique_volume['snapshot_policy']['name'],
            'language': unique_volume['language'],
            'style-extended': unique_volume['style'],
        }

        return volume

    def is_flexvol_mirrored(self, flexvol_name, vserver_name):
        """Check if flexvol is a SnapMirror source."""

        query = {
            'source.path': vserver_name + ':' + flexvol_name,
            'state': 'snapmirrored',
            'return_records': 'false',
        }

        try:
            response = self.send_request('/snapmirror/relationships/',
                                         'get', query=query)
            return response['num_records'] > 0
        except netapp_api.NaApiError:
            LOG.exception('Failed to get SnapMirror info for volume %s.',
                          flexvol_name)

        return False

    def is_flexvol_encrypted(self, flexvol_name, vserver_name):
        """Check if a flexvol is encrypted."""

        if not self.features.FLEXVOL_ENCRYPTION:
            return False

        query = {
            'encryption.enabled': 'true',
            'name': flexvol_name,
            'svm.name': vserver_name,
            'return_records': 'false',
        }

        try:
            response = self.send_request(
                '/storage/volumes/', 'get', query=query)
            return response['num_records'] > 0
        except netapp_api.NaApiError:
            LOG.exception('Failed to get Encryption info for volume %s.',
                          flexvol_name)

        return False

    def get_aggregate_disk_types(self, aggregate_name):
        """Get the disk type(s) of an aggregate."""
        disk_types = self._get_aggregate_disk_types(aggregate_name)
        return list(disk_types) if disk_types else None

    def _get_aggregate_disk_types(self, aggregate_name):
        """Get the disk type(s) of an aggregate"""

        disk_types = set()

        query = {
            'aggregates.name': aggregate_name,
            'fields': 'effective_type'
        }

        try:
            response = self.send_request(
                '/storage/disks', 'get', query=query, enable_tunneling=False)
        except netapp_api.NaApiError:
            LOG.exception('Failed to get disk info for aggregate %s.',
                          aggregate_name)
            return disk_types

        for storage_disk_info in response['records']:
            disk_types.add(storage_disk_info['effective_type'])

        return disk_types

    def _get_aggregates(self, aggregate_names=None, fields=None):

        query = {}
        if aggregate_names:
            query['name'] = ','.join(aggregate_names)

        if fields:
            query['fields'] = fields

        response = self.send_request(
            '/storage/aggregates', 'get', query=query, enable_tunneling=False)

        return response['records']

    def get_aggregate(self, aggregate_name):
        """Get aggregate attributes needed for the storage service catalog."""

        if not aggregate_name:
            return {}

        fields = ('name,block_storage.primary.raid_type,'
                  'block_storage.storage_type,home_node.name')

        try:
            aggrs = self._get_aggregates(aggregate_names=[aggregate_name],
                                         fields=fields)
        except netapp_api.NaApiError:
            LOG.exception('Failed to get info for aggregate %s.',
                          aggregate_name)
            return {}

        if len(aggrs) < 1:
            return {}

        aggr_attributes = aggrs[0]

        aggregate = {
            'name': aggr_attributes['name'],
            'raid-type':
                aggr_attributes['block_storage']['primary']['raid_type'],
            'is-hybrid':
                aggr_attributes['block_storage']['storage_type'] == 'hybrid',
            'node-name': aggr_attributes['home_node']['name'],
        }

        return aggregate

    def is_qos_min_supported(self, is_nfs, node_name):
        """Check if the node supports QoS minimum."""
        if node_name is None:
            # whether no access to node name (SVM account or error), the QoS
            # min support is dropped.
            return False

        qos_min_name = na_utils.qos_min_feature_name(is_nfs, node_name)
        return getattr(self.features, qos_min_name, False).__bool__()

    def get_flexvol_dedupe_info(self, flexvol_name):
        """Get dedupe attributes needed for the storage service catalog."""

        query = {
            'efficiency.volume_path': '/vol/%s' % flexvol_name,
            'fields': 'efficiency.state,efficiency.compression'
        }

        # Set default values for the case there is no response.
        no_dedupe_response = {
            'compression': False,
            'dedupe': False,
            'logical-data-size': 0,
            'logical-data-limit': 1,
        }

        try:
            response = self.send_request('/storage/volumes',
                                         'get', query=query)
        except netapp_api.NaApiError:
            LOG.exception('Failed to get dedupe info for volume %s.',
                          flexvol_name)
            return no_dedupe_response

        if response["num_records"] != 1:
            return no_dedupe_response

        state = response["records"][0]["efficiency"]["state"]
        compression = response["records"][0]["efficiency"]["compression"]

        # TODO(nahimsouza): as soon as REST API supports the fields
        # 'logical-data-size and 'logical-data-limit', we should include
        # them in the query and set them correctly.
        # NOTE(nahimsouza): these fields are only used by the client function
        # `get_flexvol_dedupe_used_percent`, since the function is not
        # implemented on REST yet, the below hard-coded fields are not
        # affecting the driver in anyway.
        logical_data_size = 0
        logical_data_limit = 1

        dedupe_info = {
            'compression': False if compression == "none" else True,
            'dedupe': False if state == "disabled" else True,
            'logical-data-size': logical_data_size,
            'logical-data-limit': logical_data_limit,
        }

        return dedupe_info

    def get_lun_list(self):
        """Gets the list of LUNs on filer.

        Gets the LUNs from cluster with vserver.
        """

        query = {
            'svm.name': self.vserver,
            'fields': 'svm.name,location.volume.name,space.size,'
                      'location.qtree.name,name,os_type,'
                      'space.scsi_thin_provisioning_support_enabled,'
                      'space.guarantee.requested,uuid'
        }

        response = self.send_request(
            '/storage/luns/', 'get', query=query)

        if response['num_records'] == '0':
            return []

        lun_list = []
        for lun in response['records']:
            lun_info = {}
            lun_info['Vserver'] = lun['svm']['name']
            lun_info['Volume'] = lun['location']['volume']['name']
            lun_info['Size'] = lun['space']['size']
            lun_info['Qtree'] = \
                lun['location'].get('qtree', {}).get('name', '')
            lun_info['Path'] = lun['name']
            lun_info['OsType'] = lun['os_type']
            lun_info['SpaceReserved'] = lun['space']['guarantee']['requested']
            lun_info['SpaceAllocated'] = \
                lun['space']['scsi_thin_provisioning_support_enabled']
            lun_info['UUID'] = lun['uuid']

            lun_list.append(lun_info)

        return lun_list

    def get_lun_by_args(self, **lun_info_args):
        """Retrieves LUN with specified args."""

        query = {
            'fields': 'svm.name,location.volume.name,space.size,'
                      'location.qtree.name,name,os_type,'
                      'space.scsi_thin_provisioning_support_enabled,'
                      'space.guarantee.requested,uuid'
        }

        if lun_info_args:
            if 'vserver' in lun_info_args:
                query['svm.name'] = lun_info_args['vserver']
            if 'path' in lun_info_args:
                query['name'] = lun_info_args['path']
            if 'uuid' in lun_info_args:
                query['uuid'] = lun_info_args['uuid']

        response = self.send_request(
            '/storage/luns/', 'get', query=query)

        if response['num_records'] == '0':
            return []

        lun_list = []
        for lun in response['records']:
            lun_info = {}
            lun_info['Vserver'] = lun['svm']['name']
            lun_info['Volume'] = lun['location']['volume']['name']
            lun_info['Size'] = lun['space']['size']
            lun_info['Qtree'] = \
                lun['location'].get('qtree', {}).get('name', '')
            lun_info['Path'] = lun['name']
            lun_info['OsType'] = lun['os_type']
            lun_info['SpaceReserved'] = lun['space']['guarantee']['requested']
            lun_info['SpaceAllocated'] = \
                lun['space']['scsi_thin_provisioning_support_enabled']
            lun_info['UUID'] = lun['uuid']

            # NOTE(nahimsouza): Currently, ONTAP REST API does not have the
            # 'block-size' in the response. By default, we are setting its
            # value to 512, since traditional block size advertised by hard
            # disks is 512 bytes.
            lun_info['BlockSize'] = 512

            lun_list.append(lun_info)

        return lun_list

    def get_lun_sizes_by_volume(self, volume_name):
        """"Gets the list of LUNs and their sizes from a given volume name"""

        query = {
            'location.volume.name': volume_name,
            'fields': 'space.size,name'
        }

        response = self.send_request('/storage/luns/', 'get', query=query)

        if response['num_records'] == '0':
            return []

        luns = []
        for lun_info in response['records']:
            luns.append({
                'path': lun_info.get('name', ''),
                'size': float(lun_info.get('space', {}).get('size', 0))
            })
        return luns

    def get_file_sizes_by_dir(self, dir_path):
        """Gets the list of files and their sizes from a given directory."""

        # 'dir_path' will always be a FlexVol name
        volume = self._get_volume_by_args(vol_name=dir_path)

        query = {
            'type': 'file',
            'fields': 'size,name'
        }

        vol_uuid = volume['uuid']
        try:
            response = self.send_request(
                f'/storage/volumes/{vol_uuid}/files',
                'get', query=query)
        except netapp_api.NaApiError as e:
            if e.code == netapp_api.REST_NO_SUCH_FILE:
                return []
            else:
                raise e

        files = []
        for file_info in response['records']:
            files.append({
                'name': file_info.get('name', ''),
                'file-size': float(file_info.get('size', 0))
            })
        return files

    def get_volume_state(self, junction_path=None, name=None):
        """Returns volume state for a given name or junction path."""

        query_args = {}

        if name:
            query_args['name'] = name
        if junction_path:
            query_args['nas.path'] = junction_path

        query_args['fields'] = 'state'

        response = self.send_request('/storage/volumes/',
                                     'get', query=query_args)
        try:
            records = response.get('records', [])
            unique_volume = self._get_unique_volume(records)
        except exception.VolumeBackendAPIException:
            return None

        return unique_volume['state']

    def delete_snapshot(self, volume_name, snapshot_name):
        """Deletes a volume snapshot."""
        volume = self._get_volume_by_args(vol_name=volume_name)
        self.send_request(
            f'/storage/volumes/{volume["uuid"]}/snapshots'
            f'?name={snapshot_name}', 'delete')

    def get_operational_lif_addresses(self):
        """Gets the IP addresses of operational LIFs on the vserver."""

        query = {
            'state': 'up',
            'fields': 'ip.address',
        }

        response = self.send_request(
            '/network/ip/interfaces/', 'get', query=query)

        return [lif_info['ip']['address']
                for lif_info in response['records']]

    def _list_vservers(self):
        """Get the names of vservers present"""
        query = {
            'fields': 'name',
        }
        response = self.send_request('/svm/svms', 'get', query=query,
                                     enable_tunneling=False)

        return [svm['name'] for svm in response.get('records', [])]

    def _get_ems_log_destination_vserver(self):
        """Returns the best vserver destination for EMS messages."""

        # NOTE(nahimsouza): Differently from ZAPI, only 'data' SVMs can be
        # managed by the SVM REST APIs - that's why the vserver type is not
        # specified.
        vservers = self._list_vservers()

        if vservers:
            return vservers[0]

        raise exception.NotFound("No Vserver found to receive EMS messages.")

    def send_ems_log_message(self, message_dict):
        """Sends a message to the Data ONTAP EMS log."""

        body = {
            'computer_name': message_dict['computer-name'],
            'event_source': message_dict['event-source'],
            'app_version': message_dict['app-version'],
            'category': message_dict['category'],
            'severity': 'notice',
            'autosupport_required': message_dict['auto-support'] == 'true',
            'event_id': message_dict['event-id'],
            'event_description': message_dict['event-description'],
        }

        bkp_connection = copy.copy(self.connection)
        bkp_timeout = self.connection.get_timeout()
        bkp_vserver = self.vserver

        self.connection.set_timeout(25)
        try:
            # TODO(nahimsouza): Vserver is being set to replicate the ZAPI
            # behavior, but need to check if this could be removed in REST API
            self.connection.set_vserver(
                self._get_ems_log_destination_vserver())
            self.send_request('/support/ems/application-logs',
                              'post', body=body)
            LOG.debug('EMS executed successfully.')
        except netapp_api.NaApiError as e:
            LOG.warning('Failed to invoke EMS. %s', e)
        finally:
            # Restores the data
            timeout = (
                bkp_timeout if bkp_timeout is not None else DEFAULT_TIMEOUT)
            self.connection.set_timeout(timeout)
            self.connection = copy.copy(bkp_connection)
            self.connection.set_vserver(bkp_vserver)

    def get_performance_counter_info(self, object_name, counter_name):
        """Gets info about one or more Data ONTAP performance counters."""

        # NOTE(nahimsouza): This conversion is nedeed because different names
        # are used in ZAPI and we want to avoid changes in the driver for now.
        rest_counter_names = {
            'domain_busy': 'domain_busy_percent',
            'processor_elapsed_time': 'elapsed_time',
            'avg_processor_busy': 'average_processor_busy_percent',
        }

        rest_counter_name = counter_name
        if counter_name in rest_counter_names:
            rest_counter_name = rest_counter_names[counter_name]

        # Get counter table info
        query = {
            'counter_schemas.name': rest_counter_name,
            'fields': 'counter_schemas.*'
        }

        try:
            table = self.send_request(
                f'/cluster/counter/tables/{object_name}',
                'get', query=query, enable_tunneling=False)

            name = counter_name  # use the original name (ZAPI compatible)
            base_counter = table['counter_schemas'][0]['denominator']['name']

            query = {
                'counters.name': rest_counter_name,
                'fields': 'counters.*'
            }

            response = self.send_request(
                f'/cluster/counter/tables/{object_name}/rows',
                'get', query=query, enable_tunneling=False)

            table_rows = response.get('records', [])
            labels = []
            if len(table_rows) != 0:
                labels = table_rows[0]['counters'][0].get('labels', [])

                # NOTE(nahimsouza): Values have a different format on REST API
                # and we want to keep compatibility with ZAPI for a while
                if object_name == 'wafl' and counter_name == 'cp_phase_times':
                    # discard the prefix 'cp_'
                    labels = [label[3:] for label in labels]

            return {
                'name': name,
                'labels': labels,
                'base-counter': base_counter,
            }
        except netapp_api.NaApiError:
            raise exception.NotFound(_('Counter %s not found') % counter_name)

    def get_performance_instance_uuids(self, object_name, node_name):
        """Get UUIDs of performance instances for a cluster node."""

        query = {
            'id': node_name + ':*',
        }

        response = self.send_request(
            f'/cluster/counter/tables/{object_name}/rows',
            'get', query=query, enable_tunneling=False)

        records = response.get('records', [])

        uuids = []
        for record in records:
            uuids.append(record['id'])

        return uuids

    def get_performance_counters(self, object_name, instance_uuids,
                                 counter_names):
        """Gets more cDOT performance counters."""

        # NOTE(nahimsouza): This conversion is nedeed because different names
        # are used in ZAPI and we want to avoid changes in the driver for now.
        rest_counter_names = {
            'domain_busy': 'domain_busy_percent',
            'processor_elapsed_time': 'elapsed_time',
            'avg_processor_busy': 'average_processor_busy_percent',
        }

        zapi_counter_names = {
            'domain_busy_percent': 'domain_busy',
            'elapsed_time': 'processor_elapsed_time',
            'average_processor_busy_percent': 'avg_processor_busy',
        }

        for i in range(len(counter_names)):
            if counter_names[i] in rest_counter_names:
                counter_names[i] = rest_counter_names[counter_names[i]]

        query = {
            'id': '|'.join(instance_uuids),
            'counters.name': '|'.join(counter_names),
            'fields': 'id,counter_table.name,counters.*',
        }

        response = self.send_request(
            f'/cluster/counter/tables/{object_name}/rows',
            'get', query=query, enable_tunneling=False)

        counter_data = []
        for record in response.get('records', []):
            for counter in record['counters']:

                counter_name = counter['name']

                # Reverts the name conversion
                if counter_name in zapi_counter_names:
                    counter_name = zapi_counter_names[counter_name]

                counter_value = ''
                if counter.get('value'):
                    counter_value = counter.get('value')
                elif counter.get('values'):
                    # NOTE(nahimsouza): Conversion made to keep compatibility
                    # with old ZAPI format
                    values = counter.get('values')
                    counter_value = ','.join([str(v) for v in values])

                counter_data.append({
                    'instance-name': record['counter_table']['name'],
                    'instance-uuid': record['id'],
                    'node-name': record['id'].split(':')[0],
                    'timestamp': int(time()),
                    counter_name: counter_value,
                })

        return counter_data

    def get_aggregate_capacities(self, aggregate_names):
        """Gets capacity info for multiple aggregates."""

        if not isinstance(aggregate_names, list):
            return {}

        aggregates = {}
        for aggregate_name in aggregate_names:
            aggregates[aggregate_name] = self._get_aggregate_capacity(
                aggregate_name)

        return aggregates

    def _get_aggregate_capacity(self, aggregate_name):
        """Gets capacity info for an aggregate."""

        fields = ('space.block_storage.available,space.block_storage.size,'
                  'space.block_storage.used')

        try:
            aggrs = self._get_aggregates(aggregate_names=[aggregate_name],
                                         fields=fields)

            result = {}
            if len(aggrs) > 0:
                aggr = aggrs[0]

                available = float(aggr['space']['block_storage']['available'])
                total = float(aggr['space']['block_storage']['size'])
                used = float(aggr['space']['block_storage']['used'])
                percent_used = int((used * 100) // total)

                result = {
                    'percent-used': percent_used,
                    'size-available': available,
                    'size-total': total,
                }

            return result
        except netapp_api.NaApiError as e:
            if (e.code == netapp_api.REST_API_NOT_FOUND or
                    e.code == netapp_api.REST_UNAUTHORIZED):
                LOG.debug('Aggregate capacity can only be collected with '
                          'cluster scoped credentials.')
            else:
                LOG.exception('Failed to get info for aggregate %s.',
                              aggregate_name)
            return {}

    def get_node_for_aggregate(self, aggregate_name):
        """Get home node for the specified aggregate.

        This API could return None, most notably if it was sent
        to a Vserver LIF, so the caller must be able to handle that case.
        """

        if not aggregate_name:
            return None

        fields = 'home_node.name'
        try:
            aggrs = self._get_aggregates(aggregate_names=[aggregate_name],
                                         fields=fields)
            node = None
            if len(aggrs) > 0:
                aggr = aggrs[0]
                node = aggr['home_node']['name']

            return node
        except netapp_api.NaApiError as e:
            if e.code == netapp_api.REST_API_NOT_FOUND:
                return None
            else:
                raise e

    def provision_qos_policy_group(self, qos_policy_group_info,
                                   qos_min_support):
        """Create QoS policy group on the backend if appropriate."""
        if qos_policy_group_info is None:
            return

        # Legacy QoS uses externally provisioned QoS policy group,
        # so we don't need to create one on the backend.
        legacy = qos_policy_group_info.get('legacy')
        if legacy:
            return

        spec = qos_policy_group_info.get('spec')

        if not spec:
            return

        is_adaptive = na_utils.is_qos_policy_group_spec_adaptive(
            qos_policy_group_info)
        self._validate_qos_policy_group(is_adaptive, spec=spec,
                                        qos_min_support=qos_min_support)

        qos_policy_group = self._get_qos_first_policy_group_by_name(
            spec['policy_name'])

        if not qos_policy_group:
            self._create_qos_policy_group(spec, is_adaptive)
        else:
            self._modify_qos_policy_group(spec, is_adaptive,
                                          qos_policy_group)

    def _get_qos_first_policy_group_by_name(self, qos_policy_group_name):
        records = self._get_qos_policy_group_by_name(qos_policy_group_name)
        if len(records) == 0:
            return None

        return records[0]

    def _get_qos_policy_group_by_name(self, qos_policy_group_name):
        query = {'name': qos_policy_group_name}

        response = self.send_request('/storage/qos/policies/',
                                     'get', query=query)

        records = response.get('records')
        if not records:
            return []

        return records

    def _qos_spec_to_api_args(self, spec, is_adaptive, vserver=None):
        """Convert a QoS spec to REST args."""
        rest_args = {}
        if is_adaptive:
            rest_args['adaptive'] = {}
            if spec.get('absolute_min_iops'):
                rest_args['adaptive']['absolute_min_iops'] = (
                    self._sanitize_qos_spec_value(
                        spec.get('absolute_min_iops')))
            if spec.get('expected_iops'):
                rest_args['adaptive']['expected_iops'] = (
                    self._sanitize_qos_spec_value(spec.get('expected_iops')))
            if spec.get('expected_iops_allocation'):
                rest_args['adaptive']['expected_iops_allocation'] = (
                    spec.get('expected_iops_allocation'))
            if spec.get('peak_iops'):
                rest_args['adaptive']['peak_iops'] = (
                    self._sanitize_qos_spec_value(spec.get('peak_iops')))
            if spec.get('peak_iops_allocation'):
                rest_args['adaptive']['peak_iops_allocation'] = (
                    spec.get('peak_iops_allocation'))
            if spec.get('block_size'):
                rest_args['adaptive']['block_size'] = (
                    spec.get('block_size'))
        else:
            rest_args['fixed'] = {}
            qos_max = spec.get('max_throughput')
            if qos_max and 'iops' in qos_max:
                rest_args['fixed']['max_throughput_iops'] = (
                    self._sanitize_qos_spec_value(qos_max))
            elif qos_max:
                # Convert from B/s to MB/s
                value = math.ceil(
                    self._sanitize_qos_spec_value(qos_max) / (10**6))
                rest_args['fixed']['max_throughput_mbps'] = value

            qos_min = spec.get('min_throughput')
            if qos_min and 'iops' in qos_min:
                rest_args['fixed']['min_throughput_iops'] = (
                    self._sanitize_qos_spec_value(qos_min))

        if spec.get('policy_name'):
            rest_args['name'] = spec.get('policy_name')
        if spec.get('return_record'):
            rest_args['return_records'] = spec.get('return_record')

        if vserver:
            rest_args['svm'] = {}
            rest_args['svm']['name'] = vserver

        return rest_args

    def _sanitize_qos_spec_value(self, value):
        value = value.lower()
        value = value.replace('iops', '').replace('b/s', '')
        value = int(value)
        return value

    def _create_qos_policy_group(self, spec, is_adaptive):
        """Creates a QoS policy group."""
        body = self._qos_spec_to_api_args(
            spec, is_adaptive, vserver=self.vserver)

        self.send_request('/storage/qos/policies/', 'post', body=body,
                          enable_tunneling=False)

    def _modify_qos_policy_group(self, spec, is_adaptive, qos_policy_group):
        """Modifies a QoS policy group."""
        body = self._qos_spec_to_api_args(spec, is_adaptive)
        if qos_policy_group['name'] == body['name']:
            body.pop('name')

        self.send_request(
            f'/storage/qos/policies/{qos_policy_group["uuid"]}', 'patch',
            body=body, enable_tunneling=False)

    def get_vol_by_junc_vserver(self, vserver, junction):
        """Gets the volume by junction path and vserver."""
        volume = self._get_volume_by_args(vol_path=junction, vserver=vserver)
        return volume['name']

    def file_assign_qos(self, flex_vol, qos_policy_group_name,
                        qos_policy_group_is_adaptive, file_path):
        """Assigns the named QoS policy-group to a file."""
        volume = self._get_volume_by_args(flex_vol)
        body = {
            'qos_policy.name': qos_policy_group_name
        }

        self.send_request(
            f'/storage/volumes/{volume["uuid"]}/files/{file_path}',
            'patch', body=body, enable_tunneling=False)

    def mark_qos_policy_group_for_deletion(self, qos_policy_group_info,
                                           is_adaptive=False):
        """Soft delete a QoS policy group backing a cinder volume."""
        if qos_policy_group_info is None:
            return

        spec = qos_policy_group_info.get('spec')

        # For cDOT we want to delete the QoS policy group that we created for
        # this cinder volume.  Because the QoS policy may still be "in use"
        # after the zapi call to delete the volume itself returns successfully,
        # we instead rename the QoS policy group using a specific pattern and
        # later attempt on a best effort basis to delete any QoS policy groups
        # matching that pattern.
        if spec:
            current_name = spec['policy_name']
            new_name = DELETED_PREFIX + current_name
            try:
                self._rename_qos_policy_group(current_name, new_name)
            except netapp_api.NaApiError as ex:
                LOG.warning('Rename failure in cleanup of cDOT QoS policy '
                            'group %(current_name)s: %(ex)s',
                            {'current_name': current_name, 'ex': ex})

        # Attempt to delete any QoS policies named "delete-openstack-*".
        self.remove_unused_qos_policy_groups()

    def delete_file(self, path_to_file):
        """Delete file at path."""
        LOG.debug('Deleting file: %s', path_to_file)

        volume_name = path_to_file.split('/')[2]
        relative_path = '/'.join(path_to_file.split('/')[3:])
        volume = self._get_volume_by_args(volume_name)

        # Path requires "%2E" to represent "." and "%2F" to represent "/".
        relative_path = relative_path.replace('.', '%2E').replace('/', '%2F')

        self.send_request(f'/storage/volumes/{volume["uuid"]}'
                          + f'/files/{relative_path}', 'delete')

    def _rename_qos_policy_group(self, qos_policy_group_name, new_name):
        """Renames a QoS policy group."""
        body = {'name': new_name}
        query = {'name': qos_policy_group_name}
        self.send_request('/storage/qos/policies/', 'patch', body=body,
                          query=query, enable_tunneling=False)

    def remove_unused_qos_policy_groups(self):
        """Deletes all QoS policy groups that are marked for deletion."""
        query = {'name': f'{DELETED_PREFIX}*'}
        self.send_request('/storage/qos/policies', 'delete', query=query)

    def create_lun(self, volume_name, lun_name, size, metadata,
                   qos_policy_group_name=None,
                   qos_policy_group_is_adaptive=False):
        """Issues API request for creating LUN on volume."""
        self._validate_qos_policy_group(qos_policy_group_is_adaptive)

        path = f'/vol/{volume_name}/{lun_name}'
        space_reservation = metadata['SpaceReserved']
        space_allocation = metadata['SpaceAllocated']
        initial_size = size

        body = {
            'name': path,
            'space.size': str(initial_size),
            'os_type': metadata['OsType'],
            'space.guarantee.requested': space_reservation,
            'space.scsi_thin_provisioning_support_enabled': space_allocation
        }

        if qos_policy_group_name:
            body['qos_policy.name'] = qos_policy_group_name

        try:
            self.send_request('/storage/luns', 'post', body=body)
        except netapp_api.NaApiError as ex:
            with excutils.save_and_reraise_exception():
                LOG.error('Error provisioning volume %(lun_name)s on '
                          '%(volume_name)s. Details: %(ex)s',
                          {
                              'lun_name': lun_name,
                              'volume_name': volume_name,
                              'ex': ex,
                          })

    def do_direct_resize(self, path, new_size_bytes, force=True):
        """Resize the LUN."""
        seg = path.split("/")
        LOG.info('Resizing LUN %s directly to new size.', seg[-1])

        body = {'name': path, 'space.size': new_size_bytes}

        self._lun_update_by_path(path, body)

    def _get_lun_by_path(self, path, fields=None):
        query = {'name': path}

        if fields:
            query['fields'] = fields

        response = self.send_request('/storage/luns', 'get', query=query)
        records = response.get('records', [])

        return records

    def _get_first_lun_by_path(self, path, fields=None):
        records = self._get_lun_by_path(path, fields=fields)
        if len(records) == 0:
            return None

        return records[0]

    def _lun_update_by_path(self, path, body):
        """Update the LUN."""
        lun = self._get_first_lun_by_path(path)

        if not lun:
            raise netapp_api.NaApiError(code=netapp_api.EOBJECTNOTFOUND)

        self.send_request(f'/storage/luns/{lun["uuid"]}', 'patch', body=body)

    def _validate_qos_policy_group(self, is_adaptive, spec=None,
                                   qos_min_support=False):
        if is_adaptive and not self.features.ADAPTIVE_QOS:
            msg = _("Adaptive QoS feature requires ONTAP 9.4 or later.")
            raise na_utils.NetAppDriverException(msg)

        if not spec:
            return

        if 'min_throughput' in spec and not qos_min_support:
            msg = 'min_throughput is not supported by this back end.'
            raise na_utils.NetAppDriverException(msg)

    def get_if_info_by_ip(self, ip):
        """Gets the network interface info by ip."""
        query_args = {}
        query_args['ip.address'] = volume_utils.resolve_hostname(ip)
        query_args['fields'] = 'svm'

        result = self.send_request('/network/ip/interfaces/', 'get',
                                   query=query_args, enable_tunneling=False)
        num_records = result['num_records']
        records = result.get('records', [])

        if num_records == 0:
            raise exception.NotFound(
                _('No interface found on cluster for ip %s') % ip)

        return [{'vserver': item['svm']['name']} for item in records]

    def get_igroup_by_initiators(self, initiator_list):
        """Get igroups exactly matching a set of initiators."""

        igroup_list = []
        if not initiator_list:
            return igroup_list

        query = {
            'svm.name': self.vserver,
            'initiators.name': ' '.join(initiator_list),
            'fields': 'name,protocol,os_type'
        }

        response = self.send_request('/protocols/san/igroups',
                                     'get', query=query)
        records = response.get('records', [])
        for igroup_item in records:
            igroup = {'initiator-group-os-type': igroup_item['os_type'],
                      'initiator-group-type': igroup_item['protocol'],
                      'initiator-group-name': igroup_item['name']}
            igroup_list.append(igroup)

        return igroup_list

    def add_igroup_initiator(self, igroup, initiator):
        """Adds initiators to the specified igroup."""
        query_initiator_uuid = {
            'name': igroup,
            'fields': 'uuid'
        }

        response_initiator_uuid = self.send_request(
            '/protocols/san/igroups/', 'get', query=query_initiator_uuid)

        response = response_initiator_uuid.get('records', [])
        if len(response) < 1:
            msg = _('Could not find igroup initiator.')
            raise exception.VolumeBackendAPIException(data=msg)

        igroup_uuid = response[0]['uuid']

        body = {
            'name': initiator
        }

        self.send_request('/protocols/san/igroups/' +
                          igroup_uuid + '/initiators',
                          'post', body=body)

    def create_igroup(self, igroup, igroup_type='iscsi', os_type='default'):
        """Creates igroup with specified args."""
        body = {
            'name': igroup,
            'protocol': igroup_type,
            'os_type': os_type,
        }
        self.send_request('/protocols/san/igroups', 'post', body=body)

    def map_lun(self, path, igroup_name, lun_id=None):
        """Maps LUN to the initiator and returns LUN id assigned."""

        body_post = {
            'lun.name': path,
            'igroup.name': igroup_name,
        }

        if lun_id is not None:
            body_post['logical_unit_number'] = lun_id

        try:
            result = self.send_request('/protocols/san/lun-maps', 'post',
                                       body=body_post,
                                       query={'return_records': 'true'})
            records = result.get('records')
            lun_id_assigned = records[0].get('logical_unit_number')
            return lun_id_assigned
        except netapp_api.NaApiError as e:
            code = e.code
            message = e.message
            LOG.warning('Error mapping LUN. Code :%(code)s, Message: '
                        '%(message)s', {'code': code, 'message': message})
            raise

    def get_lun_map(self, path):
        """Gets the LUN map by LUN path."""
        map_list = []

        query = {
            'lun.name': path,
            'fields': 'igroup.name,logical_unit_number,svm.name',
        }

        response = self.send_request('/protocols/san/lun-maps',
                                     'get',
                                     query=query)
        num_records = response.get('num_records')
        records = response.get('records', None)
        if records is None or num_records is None:
            return map_list

        for element in records:
            map_lun = {}
            map_lun['initiator-group'] = element['igroup']['name']
            map_lun['lun-id'] = element['logical_unit_number']
            map_lun['vserver'] = element['svm']['name']
            map_list.append(map_lun)

        return map_list

    def get_fc_target_wwpns(self):
        """Gets the FC target details."""
        wwpns = []
        query = {
            'fields': 'wwpn'
        }
        response = self.send_request('/network/fc/interfaces',
                                     'get', query=query)

        records = response.get('records')
        for record in records:
            wwpn = record.get('wwpn').lower()
            wwpns.append(wwpn)

        return wwpns

    def unmap_lun(self, path, igroup_name):
        """Unmaps a LUN from given initiator."""

        # get lun amd igroup uuids
        query_uuid = {
            'igroup.name': igroup_name,
            'lun.name': path,
            'fields': 'lun.uuid,igroup.uuid'
        }

        response_uuid = self.send_request(
            '/protocols/san/lun-maps', 'get', query=query_uuid)

        if response_uuid['num_records'] > 0:
            lun_uuid = response_uuid['records'][0]['lun']['uuid']
            igroup_uuid = response_uuid['records'][0]['igroup']['uuid']

            try:
                self.send_request(
                    f'/protocols/san/lun-maps/{lun_uuid}/{igroup_uuid}',
                    'delete')
            except netapp_api.NaApiError as e:
                LOG.warning("Error unmapping LUN. Code: %(code)s, Message: "
                            "%(message)s", {'code': e.code,
                                            'message': e.message})
                # if the LUN is already unmapped
                if e.code == netapp_api.REST_NO_SUCH_LUN_MAP:
                    pass
                else:
                    raise e
        else:
            # Input is invalid or LUN may already be unmapped
            LOG.warning("Error unmapping LUN. Invalid input.")

    def has_luns_mapped_to_initiators(self, initiator_list):
        """Checks whether any LUNs are mapped to the given initiator(s)."""
        query = {
            'initiators.name': ' '.join(initiator_list),
            'fields': 'lun_maps'
        }

        response = self.send_request('/protocols/san/igroups',
                                     'get', query=query)

        records = response.get('records', [])
        if len(records) > 0:
            for record in records:
                lun_maps = record.get('lun_maps', [])
                if len(lun_maps) > 0:
                    return True

        return False

    def get_iscsi_service_details(self):
        """Returns iscsi iqn."""
        query = {
            'fields': 'target.name'
        }
        response = self.send_request(
            '/protocols/san/iscsi/services', 'get', query=query)
        records = response.get('records')
        if records:
            return records[0]['target']['name']

        LOG.debug('No iSCSI service found for vserver %s', self.vserver)
        return None

    def check_iscsi_initiator_exists(self, iqn):
        """Returns True if initiator exists."""
        endpoint_url = '/protocols/san/iscsi/credentials'
        initiator_exists = True
        try:
            query = {
                'initiator': iqn,
            }
            response = self.send_request(endpoint_url, 'get', query=query)
            records = response.get('records')
            if not records:
                initiator_exists = False

        except netapp_api.NaApiError:
            initiator_exists = False

        return initiator_exists

    def set_iscsi_chap_authentication(self, iqn, username, password):
        """Provides NetApp host's CHAP credentials to the backend."""
        initiator_exists = self.check_iscsi_initiator_exists(iqn)

        command_template = ('iscsi security %(mode)s -vserver %(vserver)s '
                            '-initiator-name %(iqn)s -auth-type CHAP '
                            '-user-name %(username)s')

        if initiator_exists:
            LOG.debug('Updating CHAP authentication for %(iqn)s.',
                      {'iqn': iqn})
            command = command_template % {
                'mode': 'modify',
                'vserver': self.vserver,
                'iqn': iqn,
                'username': username,
            }
        else:
            LOG.debug('Adding initiator %(iqn)s with CHAP authentication.',
                      {'iqn': iqn})
            command = command_template % {
                'mode': 'create',
                'vserver': self.vserver,
                'iqn': iqn,
                'username': username,
            }

        try:
            with self.ssh_client.ssh_connect_semaphore:
                ssh_pool = self.ssh_client.ssh_pool
                with ssh_pool.item() as ssh:
                    self.ssh_client.execute_command_with_prompt(ssh,
                                                                command,
                                                                'Password:',
                                                                password)
        except Exception as e:
            msg = _('Failed to set CHAP authentication for target IQN %(iqn)s.'
                    ' Details: %(ex)s') % {
                'iqn': iqn,
                'ex': e,
            }
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def get_iscsi_target_details(self):
        """Gets the iSCSI target portal details."""
        query = {
            'services': 'data_iscsi',
            'fields': 'ip.address,enabled'
        }

        response = self.send_request('/network/ip/interfaces',
                                     'get', query=query)

        target_list = []
        records = response.get('records', [])
        for record in records:
            details = dict()
            details['address'] = record['ip']['address']
            details['tpgroup-tag'] = None
            details['interface-enabled'] = record['enabled']
            # NOTE(nahimsouza): from ONTAP documentation:
            # ONTAP does not support changing the port number for iSCSI.
            # Port number 3260 is registered as part of the iSCSI specification
            # and cannot be used by any other application or service.
            details['port'] = 3260
            target_list.append(details)

        return target_list

    def move_lun(self, path, new_path):
        """Moves the LUN at path to new path."""
        seg = path.split("/")
        new_seg = new_path.split("/")
        LOG.debug("Moving LUN %(name)s to %(new_name)s.",
                  {'name': seg[-1], 'new_name': new_seg[-1]})
        query = {
            'svm.name': self.vserver,
            'name': path
        }
        body = {
            'name': new_path,
        }
        self.send_request('/storage/luns/', 'patch', query=query, body=body)

    def clone_file(self, flex_vol, src_path, dest_path, vserver,
                   dest_exists=False, source_snapshot=None, is_snapshot=False):
        """Clones file on vserver."""
        LOG.debug('Cloning file - volume %(flex_vol)s, src %(src_path)s, '
                  'dest %(dest_path)s, vserver %(vserver)s,'
                  'source_snapshot %(source_snapshot)s',
                  {
                      'flex_vol': flex_vol,
                      'src_path': src_path,
                      'dest_path': dest_path,
                      'vserver': vserver,
                      'source_snapshot': source_snapshot,
                  })

        volume = self._get_volume_by_args(flex_vol)
        body = {
            'volume': {
                'uuid': volume['uuid'],
                'name': volume['name']
            },
            'source_path': src_path,
            'destination_path': dest_path,
        }
        if is_snapshot and self.features.BACKUP_CLONE_PARAM:
            body['is_backup'] = True

        if dest_exists:
            body['overwrite_destination'] = True

        self.send_request('/storage/file/clone', 'post', body=body)

    def clone_lun(self, volume, name, new_name, space_reserved='true',
                  qos_policy_group_name=None, src_block=0, dest_block=0,
                  block_count=0, source_snapshot=None, is_snapshot=False,
                  qos_policy_group_is_adaptive=False):
        """Clones lun on vserver."""
        LOG.debug('Cloning lun - volume: %(volume)s, name: %(name)s, '
                  'new_name: %(new_name)s, space_reserved: %(space_reserved)s,'
                  ' qos_policy_group_name: %(qos_policy_group_name)s',
                  {
                      'volume': volume,
                      'name': name,
                      'new_name': new_name,
                      'space_reserved': space_reserved,
                      'qos_policy_group_name': qos_policy_group_name,
                  })

        # NOTE(nahimsouza): some parameters are not available on REST API,
        # but they are in the header just to keep compatilbility with ZAPI:
        # src_block, dest_block, block_count, is_snapshot

        self._validate_qos_policy_group(qos_policy_group_is_adaptive)

        source_path = f'/vol/{volume}'
        if source_snapshot:
            source_path += f'/.snapshot/{source_snapshot}'
        source_path += f'/{name}'
        body = {
            'svm': {
                'name': self.vserver
            },
            'name': f'/vol/{volume}/{new_name}',
            'clone': {
                'source': {
                    'name': source_path,
                }
            },
            'space': {
                'guarantee': {
                    'requested': space_reserved == 'true',
                }
            }
        }

        if qos_policy_group_name:
            body['qos_policy'] = {'name': qos_policy_group_name}

        self.send_request('/storage/luns', 'post', body=body)

    def destroy_lun(self, path, force=True):
        """Destroys the LUN at the path."""
        query = {}
        query['name'] = path
        query['svm'] = self.vserver

        if force:
            query['allow_delete_while_mapped'] = 'true'

        self.send_request('/storage/luns/', 'delete', query=query)

    def get_flexvol_capacity(self, flexvol_path=None, flexvol_name=None):
        """Gets total capacity and free capacity, in bytes, of the flexvol."""
        fields = 'name,space.available,space.afs_total'
        try:
            volume = self._get_volume_by_args(
                vol_name=flexvol_name, vol_path=flexvol_path, fields=fields)
            capacity = {
                'size-total': float(volume['space']['afs_total']),
                'size-available': float(volume['space']['available']),
            }
            return capacity
        except exception.VolumeBackendAPIException:
            msg = _('Volume %s not found.')
            msg_args = flexvol_path or flexvol_name
            raise na_utils.NetAppDriverException(msg % msg_args)

    def get_provisioning_options_from_flexvol(self, flexvol_name):
        """Get a dict of provisioning options matching existing flexvol."""

        flexvol_info = self.get_flexvol(flexvol_name=flexvol_name)
        dedupe_info = self.get_flexvol_dedupe_info(flexvol_name)

        provisioning_opts = {
            'aggregate': flexvol_info['aggregate'],
            # space-guarantee can be 'none', 'file', 'volume'
            'space_guarantee_type': flexvol_info.get('space-guarantee'),
            'snapshot_policy': flexvol_info['snapshot-policy'],
            'language': flexvol_info['language'],
            'dedupe_enabled': dedupe_info['dedupe'],
            'compression_enabled': dedupe_info['compression'],
            'snapshot_reserve': flexvol_info['percentage-snapshot-reserve'],
            'volume_type': flexvol_info['type'],
            'size': int(math.ceil(float(flexvol_info['size']) / units.Gi)),
            'is_flexgroup': flexvol_info['style-extended'] == 'flexgroup',
        }

        return provisioning_opts

    def flexvol_exists(self, volume_name):
        """Checks if a flexvol exists on the storage array."""
        LOG.debug('Checking if volume %s exists', volume_name)

        query = {
            'name': volume_name,
            'return_records': 'false'
        }

        response = self.send_request('/storage/volumes/', 'get', query=query)

        return response['num_records'] > 0

    def create_volume_async(self, name, aggregate_list, size_gb,
                            space_guarantee_type=None, snapshot_policy=None,
                            language=None, dedupe_enabled=False,
                            compression_enabled=False, snapshot_reserve=None,
                            volume_type='rw'):
        """Creates a volume asynchronously."""

        body = {
            'name': name,
            'size': size_gb * units.Gi,
            'type': volume_type,
        }

        if isinstance(aggregate_list, list):
            body['style'] = 'flexgroup'
            body['aggregates'] = [{'name': aggr} for aggr in aggregate_list]
        else:
            body['style'] = 'flexvol'
            body['aggregates'] = [{'name': aggregate_list}]

        if volume_type == 'dp':
            snapshot_policy = None
        else:
            body['nas'] = {'path': '/%s' % name}

        if snapshot_policy is not None:
            body['snapshot_policy'] = {'name': snapshot_policy}

        if space_guarantee_type:
            body['guarantee'] = {'type': space_guarantee_type}

        if language is not None:
            body['language'] = language

        if snapshot_reserve is not None:
            body['space'] = {
                'snapshot': {
                    'reserve_percent': str(snapshot_reserve)
                }
            }

        # cDOT compression requires that deduplication be enabled.
        if dedupe_enabled or compression_enabled:
            body['efficiency'] = {'dedupe': 'background'}

        if compression_enabled:
            body['efficiency']['compression'] = 'background'

        response = self.send_request('/storage/volumes/', 'post', body=body,
                                     wait_on_accepted=False)

        job_info = {
            'status': None,
            'jobid': response["job"]["uuid"],
            'error-code': None,
            'error-message': None,
        }

        return job_info

    def create_flexvol(self, flexvol_name, aggregate_name, size_gb,
                       space_guarantee_type=None, snapshot_policy=None,
                       language=None, dedupe_enabled=False,
                       compression_enabled=False, snapshot_reserve=None,
                       volume_type='rw'):
        """Creates a flexvol asynchronously and return the job info."""

        return self.create_volume_async(
            flexvol_name, aggregate_name, size_gb,
            space_guarantee_type=space_guarantee_type,
            snapshot_policy=snapshot_policy, language=language,
            dedupe_enabled=dedupe_enabled,
            compression_enabled=compression_enabled,
            snapshot_reserve=snapshot_reserve, volume_type=volume_type)

    def enable_volume_dedupe_async(self, volume_name):
        """Enable deduplication on FlexVol/FlexGroup volume asynchronously."""

        query = {
            'name': volume_name,
            'fields': 'uuid,style',
        }
        body = {
            'efficiency': {'dedupe': 'background'}
        }
        self.send_request('/storage/volumes/', 'patch', body=body, query=query,
                          wait_on_accepted=False)

    def enable_volume_compression_async(self, volume_name):
        """Enable compression on FlexVol/FlexGroup volume asynchronously."""
        query = {
            'name': volume_name
        }
        body = {
            'efficiency': {'compression': 'background'}
        }
        self.send_request('/storage/volumes/', 'patch', body=body, query=query,
                          wait_on_accepted=False)

    def _parse_lagtime(self, time_str):
        """Parse lagtime string (ISO 8601) into a number of seconds."""

        fmt_str = 'PT'
        if 'H' in time_str:
            fmt_str += '%HH'
        if 'M' in time_str:
            fmt_str += '%MM'
        if 'S' in time_str:
            fmt_str += '%SS'

        t = None
        try:
            t = datetime.strptime(time_str, fmt_str)
        except Exception:
            LOG.debug("Failed to parse lagtime: %s", time_str)
            raise

        # convert to timedelta to get the total seconds
        td = timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
        return td.total_seconds()

    def _get_snapmirrors(self, source_vserver=None, source_volume=None,
                         destination_vserver=None, destination_volume=None):

        fields = ['state', 'source.svm.name', 'source.path',
                  'destination.svm.name', 'destination.path', 'transfer.state',
                  'transfer.end_time', 'lag_time', 'healthy', 'uuid']

        query = {}
        query['fields'] = '{}'.format(','.join(f for f in fields))

        query_src_vol = source_volume if source_volume else '*'
        query_src_vserver = source_vserver if source_vserver else '*'
        query['source.path'] = query_src_vserver + ':' + query_src_vol

        query_dst_vol = destination_volume if destination_volume else '*'
        query_dst_vserver = destination_vserver if destination_vserver else '*'
        query['destination.path'] = query_dst_vserver + ':' + query_dst_vol

        response = self.send_request(
            '/snapmirror/relationships', 'get', query=query)

        snapmirrors = []
        for record in response.get('records', []):
            snapmirrors.append({
                'relationship-status': (
                    'idle'
                    if record.get('state') == 'snapmirrored'
                    else record.get('state')),
                'transferring-state': record.get('transfer', {}).get('state'),
                'mirror-state': record['state'],
                'source-vserver': record['source']['svm']['name'],
                'source-volume': (record['source']['path'].split(':')[1] if
                                  record.get('source') else None),
                'destination-vserver': record['destination']['svm']['name'],
                'destination-volume': (
                    record['destination']['path'].split(':')[1]
                    if record.get('destination') else None),
                'last-transfer-end-timestamp':
                    (record['transfer']['end_time'] if
                     record.get('transfer', {}).get('end_time') else None),
                'lag-time': (self._parse_lagtime(record['lag_time']) if
                             record.get('lag_time') else None),
                'is-healthy': record['healthy'],
                'uuid': record['uuid']
            })

        return snapmirrors

    def get_snapmirrors(self, source_vserver, source_volume,
                        destination_vserver, destination_volume,
                        desired_attributes=None):
        """Gets one or more SnapMirror relationships.

        Either the source or destination info may be omitted.
        Desired attributes exists only to keep consistent with ZAPI client
        signature and has no effect in the output.
        """

        snapmirrors = self._get_snapmirrors(
            source_vserver=source_vserver,
            source_volume=source_volume,
            destination_vserver=destination_vserver,
            destination_volume=destination_volume)

        return snapmirrors

    def create_snapmirror(self, source_vserver, source_volume,
                          destination_vserver, destination_volume,
                          schedule=None, policy=None,
                          relationship_type='data_protection'):
        """Creates a SnapMirror relationship.

        The schedule and relationship type is kept to avoid breaking
        the API used by data_motion, but are not used on the REST API.

        The schedule is part of the policy associated the relationship and the
        relationship_type will be ignored because XDP is the only type
        supported through REST API.
        """

        body = {
            'source': {
                'path': source_vserver + ':' + source_volume
            },
            'destination': {
                'path': destination_vserver + ':' + destination_volume
            }
        }

        if policy:
            body['policy'] = {'name': policy}

        try:
            self.send_request('/snapmirror/relationships/', 'post', body=body)
        except netapp_api.NaApiError as e:
            if e.code != netapp_api.REST_ERELATION_EXISTS:
                raise e

    def _set_snapmirror_state(self, state, source_vserver, source_volume,
                              destination_vserver, destination_volume,
                              wait_result=True):
        """Change the snapmirror state between two volumes."""

        snapmirror = self.get_snapmirrors(source_vserver, source_volume,
                                          destination_vserver,
                                          destination_volume)

        if not snapmirror:
            msg = _('Failed to get information about relationship between '
                    'source %(src_vserver)s:%(src_volume)s and '
                    'destination %(dst_vserver)s:%(dst_volume)s.') % {
                'src_vserver': source_vserver,
                'src_volume': source_volume,
                'dst_vserver': destination_vserver,
                'dst_volume': destination_volume}
            raise na_utils.NetAppDriverException(msg)

        uuid = snapmirror[0]['uuid']
        body = {'state': state}
        result = self.send_request('/snapmirror/relationships/' + uuid,
                                   'patch', body=body,
                                   wait_on_accepted=wait_result)

        job_info = {
            'operation-id': None,
            'status': None,
            'jobid': result.get('job', {}).get('uuid'),
            'error-code': None,
            'error-message': None,
            'relationship-uuid': uuid,
        }

        return job_info

    def initialize_snapmirror(self, source_vserver, source_volume,
                              destination_vserver, destination_volume,
                              source_snapshot=None, transfer_priority=None):
        """Initializes a SnapMirror relationship."""

        # TODO: Trigger a geometry exception to be caught by data_motion.
        # This error is raised when using ZAPI with different volume component
        # numbers, but in REST, the job must be checked sometimes before that
        # error occurs.

        return self._set_snapmirror_state(
            'snapmirrored', source_vserver, source_volume,
            destination_vserver, destination_volume, wait_result=False)

    def abort_snapmirror(self, source_vserver, source_volume,
                         destination_vserver, destination_volume,
                         clear_checkpoint=False):
        """Stops ongoing transfers for a SnapMirror relationship."""

        snapmirror = self.get_snapmirrors(source_vserver, source_volume,
                                          destination_vserver,
                                          destination_volume)
        if not snapmirror:
            msg = _('Failed to get information about relationship between '
                    'source %(src_vserver)s:%(src_volume)s and '
                    'destination %(dst_vserver)s:%(dst_volume)s.') % {
                'src_vserver': source_vserver,
                'src_volume': source_volume,
                'dst_vserver': destination_vserver,
                'dst_volume': destination_volume}
            raise na_utils.NetAppDriverException(msg)

        snapmirror_uuid = snapmirror[0]['uuid']

        query = {'state': 'transferring'}
        transfers = self.send_request('/snapmirror/relationships/' +
                                      snapmirror_uuid + '/transfers/', 'get',
                                      query=query)

        if not transfers.get('records'):
            raise netapp_api.NaApiError(
                code=netapp_api.ENOTRANSFER_IN_PROGRESS)

        body = {'state': 'hard_aborted' if clear_checkpoint else 'aborted'}

        for transfer in transfers['records']:
            transfer_uuid = transfer['uuid']
            self.send_request('/snapmirror/relationships/' +
                              snapmirror_uuid + '/transfers/' +
                              transfer_uuid, 'patch', body=body)

    def delete_snapmirror(self, source_vserver, source_volume,
                          destination_vserver, destination_volume):

        """Deletes an SnapMirror relationship on destination."""

        query_uuid = {}
        query_uuid['source.path'] = source_vserver + ':' + source_volume
        query_uuid['destination.path'] = (destination_vserver + ':' +
                                          destination_volume)
        query_uuid['fields'] = 'uuid'

        response = self.send_request('/snapmirror/relationships/', 'get',
                                     query=query_uuid)

        records = response.get('records')
        if not records:
            raise netapp_api.NaApiError(code=netapp_api.EOBJECTNOTFOUND)

        # 'destination_only' deletes the snapmirror on destination but does not
        # release it on source.
        query_delete = {"destination_only": "true"}

        snapmirror_uuid = records[0].get('uuid')
        self.send_request('/snapmirror/relationships/' +
                          snapmirror_uuid, 'delete',
                          query=query_delete)

    def resume_snapmirror(self, source_vserver, source_volume,
                          destination_vserver, destination_volume):

        """Resume a SnapMirror relationship."""

        query_uuid = {}
        query_uuid['source.path'] = source_vserver + ':' + source_volume
        query_uuid['destination.path'] = (destination_vserver + ':' +
                                          destination_volume)
        query_uuid['fields'] = 'uuid,policy.type'

        response_snapmirrors = self.send_request('/snapmirror/relationships/',
                                                 'get', query=query_uuid)

        records = response_snapmirrors.get('records')
        if not records:
            raise netapp_api.NaApiError(code=netapp_api.EOBJECTNOTFOUND)

        snapmirror_uuid = records[0]['uuid']
        snapmirror_policy = records[0]['policy']['type']

        body_resync = {}
        if snapmirror_policy == 'async':
            body_resync['state'] = 'snapmirrored'
        elif snapmirror_policy == 'sync':
            body_resync['state'] = 'in_sync'

        self.send_request('/snapmirror/relationships/' +
                          snapmirror_uuid, 'patch',
                          body=body_resync)

    def release_snapmirror(self, source_vserver, source_volume,
                           destination_vserver, destination_volume,
                           relationship_info_only=False):
        """Removes a SnapMirror relationship on the source endpoint."""

        query_uuid = {}
        query_uuid['list_destinations_only'] = 'true'
        query_uuid['source.path'] = source_vserver + ':' + source_volume
        query_uuid['destination.path'] = (destination_vserver + ':' +
                                          destination_volume)
        query_uuid['fields'] = 'uuid'

        response_snapmirrors = self.send_request('/snapmirror/relationships/',
                                                 'get', query=query_uuid)

        records = response_snapmirrors.get('records')
        if not records:
            raise netapp_api.NaApiError(code=netapp_api.EOBJECTNOTFOUND)

        query_release = {}
        if relationship_info_only:
            # release without removing related snapshots
            query_release['source_info_only'] = 'true'
        else:
            # release and removing all related snapshots
            query_release['source_only'] = 'true'

        snapmirror_uuid = records[0].get('uuid')
        self.send_request('/snapmirror/relationships/' +
                          snapmirror_uuid, 'delete',
                          query=query_release)

    def resync_snapmirror(self, source_vserver, source_volume,
                          destination_vserver, destination_volume):
        """Resync a SnapMirror relationship."""

        # We reuse the resume operation for resync since both are handled in
        # the same way in the REST API, by setting the snapmirror relationship
        # to the snapmirrored state.
        self.resume_snapmirror(source_vserver,
                               source_volume,
                               destination_vserver,
                               destination_volume)

    def quiesce_snapmirror(self, source_vserver, source_volume,
                           destination_vserver, destination_volume):
        """Disables future transfers to a SnapMirror destination."""

        return self._set_snapmirror_state(
            'paused', source_vserver, source_volume,
            destination_vserver, destination_volume)

    def break_snapmirror(self, source_vserver, source_volume,
                         destination_vserver, destination_volume):
        """Breaks a data protection SnapMirror relationship."""

        interval = 2
        retries = (10 / interval)

        @utils.retry(netapp_api.NaRetryableError, interval=interval,
                     retries=retries, backoff_rate=1)
        def _waiter():
            snapmirror = self.get_snapmirrors(
                source_vserver=source_vserver,
                source_volume=source_volume,
                destination_vserver=destination_vserver,
                destination_volume=destination_volume)

            snapmirror_state = None
            if snapmirror:
                snapmirror_state = snapmirror[0].get('transferring-state')

            if snapmirror_state == 'success':
                uuid = snapmirror[0]['uuid']
                body = {'state': 'broken_off'}
                self.send_request(f'/snapmirror/relationships/{uuid}', 'patch',
                                  body=body)
                return
            else:
                message = 'Waiting for transfer state to be SUCCESS.'
                code = ''
                raise netapp_api.NaRetryableError(message=message, code=code)

        try:
            return _waiter()
        except netapp_api.NaRetryableError:
            msg = _("Transfer state did not reach the expected state. Retries "
                    "exhausted. Aborting.")
            raise na_utils.NetAppDriverException(msg)

    def update_snapmirror(self, source_vserver, source_volume,
                          destination_vserver, destination_volume):
        """Schedules a SnapMirror update."""

        snapmirror = self.get_snapmirrors(source_vserver, source_volume,
                                          destination_vserver,
                                          destination_volume)
        if not snapmirror:
            msg = _('Failed to get information about relationship between '
                    'source %(src_vserver)s:%(src_volume)s and '
                    'destination %(dst_vserver)s:%(dst_volume)s.') % {
                'src_vserver': source_vserver,
                'src_volume': source_volume,
                'dst_vserver': destination_vserver,
                'dst_volume': destination_volume}

            raise na_utils.NetAppDriverException(msg)

        snapmirror_uuid = snapmirror[0]['uuid']

        # NOTE(nahimsouza): A POST with an empty body starts the update
        # snapmirror operation.
        try:
            self.send_request('/snapmirror/relationships/' +
                              snapmirror_uuid + '/transfers/', 'post',
                              wait_on_accepted=False)
        except netapp_api.NaApiError as e:
            if (e.code != netapp_api.REST_UPDATE_SNAPMIRROR_FAILED):
                LOG.warning('Unexpected failure during snapmirror update.'
                            'Code: %(code)s, Message: %(message)s',
                            {'code': e.code, 'message': e.message})
            raise

    def mount_flexvol(self, flexvol_name, junction_path=None):
        """Mounts a volume on a junction path."""
        query = {'name': flexvol_name}
        body = {'nas.path': (
            junction_path if junction_path else '/%s' % flexvol_name)}
        self.send_request('/storage/volumes', 'patch', query=query, body=body)

    def get_cluster_name(self):
        """Gets cluster name."""
        query = {'fields': 'name'}

        response = self.send_request('/cluster', 'get', query=query,
                                     enable_tunneling=False)

        return response['name']

    def get_vserver_peers(self, vserver_name=None, peer_vserver_name=None):
        """Gets one or more Vserver peer relationships."""
        query = {
            'fields': 'svm.name,state,peer.svm.name,peer.cluster.name,'
                      'applications'
        }

        if peer_vserver_name:
            query['name'] = peer_vserver_name
        if vserver_name:
            query['svm.name'] = vserver_name

        response = self.send_request('/svm/peers', 'get', query=query,
                                     enable_tunneling=False)
        records = response.get('records', [])

        vserver_peers = []
        for vserver_info in records:
            vserver_peer = {
                'vserver': vserver_info['svm']['name'],
                'peer-vserver': vserver_info['peer']['svm']['name'],
                'peer-state': vserver_info['state'],
                'peer-cluster': vserver_info['peer']['cluster']['name'],
                'applications': vserver_info['applications'],
            }
            vserver_peers.append(vserver_peer)

        return vserver_peers

    def create_vserver_peer(self, vserver_name, peer_vserver_name,
                            vserver_peer_application=None):
        """Creates a Vserver peer relationship."""
        # default peering application to `snapmirror` if none is specified.
        if not vserver_peer_application:
            vserver_peer_application = ['snapmirror']

        body = {
            'svm.name': vserver_name,
            'name': peer_vserver_name,
            'applications': vserver_peer_application
        }

        self.send_request('/svm/peers', 'post', body=body,
                          enable_tunneling=False)

    def start_lun_move(self, lun_name, dest_ontap_volume,
                       src_ontap_volume=None, dest_lun_name=None):
        """Starts a lun move operation between ONTAP volumes."""
        if dest_lun_name is None:
            dest_lun_name = lun_name
        if src_ontap_volume is None:
            src_ontap_volume = dest_ontap_volume

        src_path = f'/vol/{src_ontap_volume}/{lun_name}'
        dest_path = f'/vol/{dest_ontap_volume}/{dest_lun_name}'
        body = {'name': dest_path}
        self._lun_update_by_path(src_path, body)

        return dest_path

    def get_lun_move_status(self, dest_path):
        """Get lun move job status from a given dest_path."""
        lun = self._get_first_lun_by_path(
            dest_path, fields='movement.progress')

        if not lun:
            return None

        move_progress = lun['movement']['progress']
        move_status = {
            'job-status': move_progress['state'],
            'last-failure-reason': (move_progress
                                    .get('failure', {})
                                    .get('message', None))
        }

        return move_status

    def start_lun_copy(self, lun_name, dest_ontap_volume, dest_vserver,
                       src_ontap_volume=None, src_vserver=None,
                       dest_lun_name=None):
        """Starts a lun copy operation between ONTAP volumes."""
        if src_ontap_volume is None:
            src_ontap_volume = dest_ontap_volume
        if src_vserver is None:
            src_vserver = dest_vserver
        if dest_lun_name is None:
            dest_lun_name = lun_name

        src_path = f'/vol/{src_ontap_volume}/{lun_name}'
        dest_path = f'/vol/{dest_ontap_volume}/{dest_lun_name}'

        body = {
            'name': dest_path,
            'copy.source.name': src_path,
            'svm.name': dest_vserver
        }

        self.send_request('/storage/luns', 'post', body=body,
                          enable_tunneling=False)

        return dest_path

    def get_lun_copy_status(self, dest_path):
        """Get lun copy job status from a given dest_path."""
        lun = self._get_first_lun_by_path(
            dest_path, fields='copy.source.progress')

        if not lun:
            return None

        copy_progress = lun['copy']['source']['progress']
        copy_status = {
            'job-status': copy_progress['state'],
            'last-failure-reason': (copy_progress
                                    .get('failure', {})
                                    .get('message', None))
        }

        return copy_status

    def cancel_lun_copy(self, dest_path):
        """Cancel an in-progress lun copy by deleting the lun."""
        query = {
            'name': dest_path,
            'svm.name': self.vserver
        }

        try:
            self.send_request('/storage/luns/', 'delete', query=query)
        except netapp_api.NaApiError as e:
            msg = (_('Could not cancel lun copy by deleting lun at %s. %s'))
            raise na_utils.NetAppDriverException(msg % (dest_path, e))

    def start_file_copy(self, file_name, dest_ontap_volume,
                        src_ontap_volume=None,
                        dest_file_name=None):
        """Starts a file copy operation between ONTAP volumes."""
        if src_ontap_volume is None:
            src_ontap_volume = dest_ontap_volume
        if dest_file_name is None:
            dest_file_name = file_name

        source_vol = self._get_volume_by_args(src_ontap_volume)

        dest_vol = source_vol
        if dest_ontap_volume != src_ontap_volume:
            dest_vol = self._get_volume_by_args(dest_ontap_volume)

        body = {
            'files_to_copy': [
                {
                    'source': {
                        'path': f'{src_ontap_volume}/{file_name}',
                        'volume': {
                            'uuid': source_vol['uuid']
                        }
                    },
                    'destination': {
                        'path': f'{dest_ontap_volume}/{dest_file_name}',
                        'volume': {
                            'uuid': dest_vol['uuid']
                        }
                    }
                }
            ]
        }

        result = self.send_request('/storage/file/copy', 'post', body=body,
                                   enable_tunneling=False)
        return result['job']['uuid']

    def get_file_copy_status(self, job_uuid):
        """Get file copy job status from a given job's UUID."""
        # TODO(rfluisa): Select only the fields that are needed here.
        query = {}
        query['fields'] = '*'

        result = self.send_request(
            f'/cluster/jobs/{job_uuid}', 'get', query=query,
            enable_tunneling=False)

        if not result or not result.get('state', None):
            return None

        state = result.get('state')
        if state == 'success':
            state = 'complete'
        elif state == 'failure':
            state = 'destroyed'

        copy_status = {
            'job-status': state,
            'last-failure-reason': result.get('error', {}).get('message', None)
        }

        return copy_status

    def rename_file(self, orig_file_name, new_file_name):
        """Rename a volume file."""
        LOG.debug("Renaming the file %(original)s to %(new)s.",
                  {'original': orig_file_name, 'new': new_file_name})

        unique_volume = self._get_volume_by_args(
            vol_name=orig_file_name.split('/')[2])

        # Get the relative path
        orig_file_name = '/'.join(orig_file_name.split('/')[3:])
        new_file_name = '/'.join(new_file_name.split('/')[3:])

        # Path requires "%2E" to represent "." and "%2F" to represent "/".
        orig_file_name = orig_file_name.replace('.', '%2E').replace('/', '%2F')
        new_file_name = new_file_name.replace('.', '%2E').replace('/', '%2F')

        body = {'path': new_file_name}

        self.send_request(
            f'/storage/volumes/{unique_volume["uuid"]}/files/{orig_file_name}',
            'patch', body=body)

    def get_namespace_list(self):
        """Gets the list of namespaces on filer.

        Gets the namespaces from cluster with vserver.
        """

        query = {
            'svm.name': self.vserver,
            'fields': 'svm.name,location.volume.name,space.size,'
                      'location.qtree.name,name,os_type,'
                      'space.guarantee.requested,uuid'
        }

        response = self.send_request(
            '/storage/namespaces/', 'get', query=query)

        namespace_list = []
        for namespace in response.get('records', []):
            namespace_info = {}
            namespace_info['Vserver'] = namespace['svm']['name']
            namespace_info['Volume'] = namespace['location']['volume']['name']
            namespace_info['Size'] = namespace['space']['size']
            namespace_info['Qtree'] = (
                namespace['location'].get('qtree', {}).get('name', ''))
            namespace_info['Path'] = namespace['name']
            namespace_info['OsType'] = namespace['os_type']
            namespace_info['SpaceReserved'] = (
                namespace['space']['guarantee']['requested'])
            namespace_info['UUID'] = namespace['uuid']

            namespace_list.append(namespace_info)

        return namespace_list

    def create_namespace(self, volume_name, namespace_name, size, metadata):
        """Issues API request for creating namespace on volume."""

        path = f'/vol/{volume_name}/{namespace_name}'
        initial_size = size

        body = {
            'name': path,
            'space.size': str(initial_size),
            'os_type': metadata['OsType'],
        }

        try:
            self.send_request('/storage/namespaces', 'post', body=body)
        except netapp_api.NaApiError as ex:
            with excutils.save_and_reraise_exception():
                LOG.error('Error provisioning volume %(namespace_name)s on '
                          '%(volume_name)s. Details: %(ex)s',
                          {
                              'namespace_name': namespace_name,
                              'volume_name': volume_name,
                              'ex': ex,
                          })

    def destroy_namespace(self, path, force=True):
        """Destroys the namespace at the path."""
        query = {
            'name': path,
            'svm': self.vserver
        }

        if force:
            query['allow_delete_while_mapped'] = 'true'

        self.send_request('/storage/namespaces', 'delete', query=query)

    def clone_namespace(self, volume, name, new_name):
        """Clones namespace on vserver."""
        LOG.debug('Cloning namespace - volume: %(volume)s, name: %(name)s, '
                  'new_name: %(new_name)s',
                  {
                      'volume': volume,
                      'name': name,
                      'new_name': new_name,
                  })

        source_path = f'/vol/{volume}/{name}'
        body = {
            'svm': {
                'name': self.vserver
            },
            'name': f'/vol/{volume}/{new_name}',
            'clone': {
                'source': {
                    'name': source_path,
                }
            }
        }
        self.send_request('/storage/namespaces', 'post', body=body)

    def get_namespace_by_args(self, **namespace_info_args):
        """Retrieves namespace with specified args."""

        query = {
            'fields': 'svm.name,location.volume.name,space.size,'
                      'location.qtree.name,name,os_type,'
                      'space.guarantee.requested,uuid,space.block_size'
        }

        if namespace_info_args:
            if 'vserver' in namespace_info_args:
                query['svm.name'] = namespace_info_args['vserver']
            if 'path' in namespace_info_args:
                query['name'] = namespace_info_args['path']
            if 'uuid' in namespace_info_args:
                query['uuid'] = namespace_info_args['uuid']

        response = self.send_request('/storage/namespaces', 'get', query=query)

        namespace_list = []
        for namespace in response.get('records', []):
            namespace_info = {}
            namespace_info['Vserver'] = namespace['svm']['name']
            namespace_info['Volume'] = namespace['location']['volume']['name']
            namespace_info['Size'] = namespace['space']['size']
            namespace_info['Qtree'] = (
                namespace['location'].get('qtree', {}).get('name', ''))
            namespace_info['Path'] = namespace['name']
            namespace_info['OsType'] = namespace['os_type']
            namespace_info['SpaceReserved'] = (
                namespace['space']['guarantee']['requested'])
            namespace_info['UUID'] = namespace['uuid']
            namespace_info['BlockSize'] = namespace['space']['block_size']

            namespace_list.append(namespace_info)

        return namespace_list

    def namespace_resize(self, path, new_size_bytes):
        """Resize the namespace."""
        seg = path.split("/")
        LOG.info('Resizing namespace %s to new size.', seg[-1])

        body = {'space.size': new_size_bytes}
        query = {'name': path}
        self.send_request('/storage/namespaces', 'patch', body=body,
                          query=query)

    def get_namespace_sizes_by_volume(self, volume_name):
        """"Gets the list of namespace and their sizes from a given volume."""

        query = {
            'location.volume.name': volume_name,
            'fields': 'space.size,name'
        }
        response = self.send_request('/storage/namespaces', 'get', query=query)

        namespaces = []
        for namespace_info in response.get('records', []):
            namespaces.append({
                'path': namespace_info.get('name', ''),
                'size': float(namespace_info.get('space', {}).get('size', 0))
            })

        return namespaces

    def get_subsystem_by_host(self, host_nqn):
        """Get subsystem exactly matching the initiator host."""
        query = {
            'svm.name': self.vserver,
            'hosts.nqn': host_nqn,
            'fields': 'name,os_type',
            'name': f'{na_utils.OPENSTACK_PREFIX}*',
        }
        response = self.send_request('/protocols/nvme/subsystems', 'get',
                                     query=query)

        records = response.get('records', [])

        return [{'name': subsystem['name'], 'os_type': subsystem['os_type']}
                for subsystem in records]

    def create_subsystem(self, subsystem_name, os_type, host_nqn):
        """Creates subsystem with specified args."""
        body = {
            'svm.name': self.vserver,
            'name': subsystem_name,
            'os_type': os_type,
            'hosts': [{'nqn': host_nqn}]
        }
        self.send_request('/protocols/nvme/subsystems', 'post', body=body)

    def get_namespace_map(self, path):
        """Gets the namespace map using its path."""
        query = {
            'namespace.name': path,
            'fields': 'subsystem.name,namespace.uuid,svm.name',
        }
        response = self.send_request('/protocols/nvme/subsystem-maps',
                                     'get',
                                     query=query)

        records = response.get('records', [])
        map_list = []
        for map in records:
            map_subsystem = {}
            map_subsystem['subsystem'] = map['subsystem']['name']
            map_subsystem['uuid'] = map['namespace']['uuid']
            map_subsystem['vserver'] = map['svm']['name']

            map_list.append(map_subsystem)

        return map_list

    def map_namespace(self, path, subsystem_name):
        """Maps namespace to the host nqn and returns namespace uuid."""

        body_post = {
            'namespace.name': path,
            'subsystem.name': subsystem_name
        }
        try:
            result = self.send_request('/protocols/nvme/subsystem-maps',
                                       'post',
                                       body=body_post,
                                       query={'return_records': 'true'})
            records = result.get('records')
            namespace_uuid = records[0]['namespace']['uuid']
            return namespace_uuid
        except netapp_api.NaApiError as e:
            code = e.code
            message = e.message
            LOG.warning('Error mapping namespace. Code :%(code)s, Message: '
                        '%(message)s', {'code': code, 'message': message})
            raise

    def get_nvme_subsystem_nqn(self, subsystem):
        """Returns target subsystem nqn."""
        query = {
            'fields': 'target_nqn',
            'name': subsystem,
            'svm.name': self.vserver
        }
        response = self.send_request(
            '/protocols/nvme/subsystems', 'get', query=query)

        records = response.get('records', [])
        if records:
            return records[0]['target_nqn']

        LOG.debug('No %(subsystem)s NVMe subsystem found for vserver '
                  '%(vserver)s',
                  {'subsystem': subsystem, 'vserver': self.vserver})
        return None

    def get_nvme_target_portals(self):
        """Gets the NVMe target portal details."""
        query = {
            'services': 'data_nvme_tcp',
            'fields': 'ip.address',
            'enabled': 'true',
        }

        response = self.send_request('/network/ip/interfaces', 'get',
                                     query=query)

        interfaces = response.get('records', [])
        return [record['ip']['address'] for record in interfaces]

    def unmap_namespace(self, path, subsystem):
        """Unmaps a namespace from given subsystem."""

        query = {
            'subsystem.name': subsystem,
            'namespace.name': path
        }
        self.send_request('/protocols/nvme/subsystem-maps', 'delete',
                          query=query)
