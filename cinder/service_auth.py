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


from keystoneauth1 import loading as ks_loading
from keystoneauth1 import service_token
from oslo_config import cfg

from cinder import exception

CONF = cfg.CONF
_SERVICE_AUTH = None

SERVICE_USER_GROUP = 'service_user'

service_user = cfg.OptGroup(
    SERVICE_USER_GROUP,
    title='Service token authentication type options',
    help="""
Configuration options for service to service authentication using a service
token. These options allow to send a service token along with the
user's token when contacting external REST APIs.
"""
)
service_user_opts = [
    cfg.BoolOpt('send_service_user_token',
                default=False,
                help="""
When True, if sending a user token to an REST API, also send a service token.
""")
]

CONF.register_group(service_user)
CONF.register_opts(service_user_opts, group=service_user)

ks_loading.register_session_conf_options(CONF, SERVICE_USER_GROUP)
ks_loading.register_auth_conf_options(CONF, SERVICE_USER_GROUP)


def reset_globals():
    """For async unit test consistency."""
    global _SERVICE_AUTH
    _SERVICE_AUTH = None


def get_auth_plugin(context, auth=None):
    if auth:
        user_auth = auth
    else:
        user_auth = context.get_auth_plugin()

    if CONF.service_user.send_service_user_token:
        global _SERVICE_AUTH
        if not _SERVICE_AUTH:
            _SERVICE_AUTH = ks_loading.load_auth_from_conf_options(
                CONF, group=SERVICE_USER_GROUP)
            if _SERVICE_AUTH is None:
                # This can happen if no auth_type is specified, which probably
                # means there's no auth information in the [service_user] group
                raise exception.ServiceUserTokenNoAuth()
        return service_token.ServiceTokenAuthWrapper(
            user_auth=user_auth, service_auth=_SERVICE_AUTH)

    return user_auth
