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

from oslo_log import log as logging
import six

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


@six.add_metaclass(volume_utils.TraceWrapperMetaclass)
class RestClient(object):

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

    def _get_cluster_nodes_info(self):
        """Return a list of models of the nodes in the cluster."""
        query_args = {'fields': 'model,'
                                'name,'
                                'is_all_flash_optimized,'
                                'is_all_flash_select_optimized'}

        nodes = []
        try:
            result = self.send_request('cluster/nodes', 'get',
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
