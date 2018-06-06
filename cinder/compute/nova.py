# Copyright 2013 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
Handles all requests to Nova.
"""

from keystoneauth1 import identity
from keystoneauth1 import loading as ks_loading
from novaclient import api_versions
from novaclient import client as nova_client
from novaclient import exceptions as nova_exceptions
from oslo_config import cfg
from oslo_log import log as logging
from requests import exceptions as request_exceptions

from cinder.db import base
from cinder import exception
from cinder.message import api as message_api
from cinder.message import message_field
from cinder import service_auth

nova_opts = [
    cfg.StrOpt('region_name',
               help='Name of nova region to use. Useful if keystone manages '
                    'more than one region.'),
    cfg.StrOpt('interface',
               default='public',
               choices=['public', 'admin', 'internal'],
               help='Type of the nova endpoint to use.  This endpoint will '
                    'be looked up in the keystone catalog and should be '
                    'one of public, internal or admin.'),
    cfg.StrOpt('token_auth_url',
               help='The authentication URL for the nova connection when '
                    'using the current user''s token'),
]


NOVA_GROUP = 'nova'
CONF = cfg.CONF

nova_session_opts = ks_loading.get_session_conf_options()
nova_auth_opts = ks_loading.get_auth_common_conf_options()

CONF.register_opts(nova_opts, group=NOVA_GROUP)
CONF.register_opts(nova_session_opts, group=NOVA_GROUP)
CONF.register_opts(nova_auth_opts, group=NOVA_GROUP)

LOG = logging.getLogger(__name__)

NOVA_API_VERSION = "2.1"

nova_extensions = [ext for ext in
                   nova_client.discover_extensions(NOVA_API_VERSION)
                   if ext.name in ("assisted_volume_snapshots",
                                   "list_extensions",
                                   "server_external_events")]


def _get_identity_endpoint_from_sc(context):
    # Search for the identity endpoint in the service catalog
    for service in context.service_catalog:
        if service.get('type') != 'identity':
            continue
        for endpoint in service['endpoints']:
            if (not CONF[NOVA_GROUP].region_name or
                    endpoint.get('region') == CONF[NOVA_GROUP].region_name):
                return endpoint.get(CONF[NOVA_GROUP].interface + 'URL')
    raise nova_exceptions.EndpointNotFound()


def novaclient(context, privileged_user=False, timeout=None, api_version=None):
    """Returns a Nova client

    @param privileged_user:
        If True, use the account from configuration
        (requires 'auth_type' and the other usual Keystone authentication
        options to be set in the [nova] section)
    @param timeout:
        Number of seconds to wait for an answer before raising a
        Timeout exception (None to disable)
    @param api_version:
        api version of nova
    """

    if privileged_user and CONF[NOVA_GROUP].auth_type:
        LOG.debug('Creating Keystone auth plugin from conf')
        n_auth = ks_loading.load_auth_from_conf_options(CONF, NOVA_GROUP)
    else:
        if CONF[NOVA_GROUP].token_auth_url:
            url = CONF[NOVA_GROUP].token_auth_url
        else:
            url = _get_identity_endpoint_from_sc(context)
        LOG.debug('Creating Keystone token plugin using URL: %s', url)
        n_auth = identity.Token(auth_url=url,
                                token=context.auth_token,
                                project_name=context.project_name,
                                project_domain_id=context.project_domain_id)

    if CONF.auth_strategy == 'keystone':
        n_auth = service_auth.get_auth_plugin(context, auth=n_auth)

    keystone_session = ks_loading.load_session_from_conf_options(
        CONF,
        NOVA_GROUP,
        auth=n_auth)

    c = nova_client.Client(
        api_versions.APIVersion(api_version or NOVA_API_VERSION),
        session=keystone_session,
        insecure=CONF[NOVA_GROUP].insecure,
        timeout=timeout,
        region_name=CONF[NOVA_GROUP].region_name,
        endpoint_type=CONF[NOVA_GROUP].interface,
        cacert=CONF[NOVA_GROUP].cafile,
        global_request_id=context.global_id,
        extensions=nova_extensions)

    return c


class API(base.Base):
    """API for interacting with novaclient."""

    def __init__(self):
        self.message_api = message_api.API()

    def _get_volume_extended_event(self, server_id, volume_id):
        return {'name': 'volume-extended',
                'server_uuid': server_id,
                'tag': volume_id}

    def _send_events(self, context, events, api_version=None):
        nova = novaclient(context, privileged_user=True,
                          api_version=api_version)
        try:
            response = nova.server_external_events.create(events)
        except nova_exceptions.NotFound:
            LOG.warning('Nova returned NotFound for events: %s.', events)
            return False
        except Exception:
            LOG.exception('Failed to notify nova on events: %s.', events)
            return False
        else:
            if not isinstance(response, list):
                LOG.error('Error response returned from nova: %s.', response)
                return False
            response_error = False
            for event in response:
                code = event.get('code')
                if code is None:
                    response_error = True
                    continue
                if code != 200:
                    LOG.warning(
                        'Nova event: %s returned with failed status.', event)
                else:
                    LOG.info('Nova event response: %s.', event)
            if response_error:
                LOG.error('Error response returned from nova: %s.', response)
                return False
        return True

    def has_extension(self, context, extension, timeout=None):
        try:
            nova_exts = novaclient(context).list_extensions.show_all()
        except request_exceptions.Timeout:
            raise exception.APITimeout(service='Nova')
        return extension in [e.name for e in nova_exts]

    def update_server_volume(self, context, server_id, src_volid,
                             new_volume_id):
        nova = novaclient(context, privileged_user=True)
        nova.volumes.update_server_volume(server_id,
                                          src_volid,
                                          new_volume_id)

    def create_volume_snapshot(self, context, volume_id, create_info):
        nova = novaclient(context, privileged_user=True)

        # pylint: disable=E1101
        nova.assisted_volume_snapshots.create(
            volume_id,
            create_info=create_info)

    def delete_volume_snapshot(self, context, snapshot_id, delete_info):
        nova = novaclient(context, privileged_user=True)

        # pylint: disable=E1101
        nova.assisted_volume_snapshots.delete(
            snapshot_id,
            delete_info=delete_info)

    def get_server(self, context, server_id, privileged_user=False,
                   timeout=None):
        try:
            return novaclient(context, privileged_user=privileged_user,
                              timeout=timeout).servers.get(server_id)
        except nova_exceptions.NotFound:
            raise exception.ServerNotFound(uuid=server_id)
        except request_exceptions.Timeout:
            raise exception.APITimeout(service='Nova')

    def extend_volume(self, context, server_ids, volume_id):
        api_version = '2.51'
        events = [self._get_volume_extended_event(server_id, volume_id)
                  for server_id in server_ids]
        result = self._send_events(context, events, api_version=api_version)
        if not result:
            self.message_api.create(
                context,
                message_field.Action.EXTEND_VOLUME,
                resource_uuid=volume_id,
                detail=message_field.Detail.NOTIFY_COMPUTE_SERVICE_FAILED)
        return result
