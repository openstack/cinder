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

from keystoneauth1 import exceptions as ks_exc
from keystoneauth1 import identity
from keystoneauth1 import loading as ka_loading
from keystoneclient import client
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import strutils
import webob
from webob import exc

from cinder import exception
from cinder.i18n import _

CONF = cfg.CONF
CONF.import_group('keystone_authtoken',
                  'keystonemiddleware.auth_token.__init__')

LOG = logging.getLogger(__name__)


def _parse_is_public(is_public):
    """Parse is_public into something usable.

    * True: List public volume types only
    * False: List private volume types only
    * None: List both public and private volume types
    """

    if is_public is None:
        # preserve default value of showing only public types
        return True
    elif is_none_string(is_public):
        return None
    else:
        try:
            return strutils.bool_from_string(is_public, strict=True)
        except ValueError:
            msg = _('Invalid is_public filter [%s]') % is_public
            raise exc.HTTPBadRequest(explanation=msg)


def is_none_string(val):
    """Check if a string represents a None value."""
    if not isinstance(val, str):
        return False

    return val.lower() == 'none'


def remove_invalid_filter_options(context, filters,
                                  allowed_search_options):
    """Remove search options that are not valid for non-admin API/context."""

    if context.is_admin:
        # Allow all options
        return
    # Otherwise, strip out all unknown options
    unknown_options = [opt for opt in filters
                       if opt not in allowed_search_options]
    bad_options = ", ".join(unknown_options)
    LOG.debug("Removing options '%s' from query.", bad_options)
    for opt in unknown_options:
        del filters[opt]


_visible_admin_metadata_keys = ['readonly', 'attached_mode']


def add_visible_admin_metadata(volume):
    """Add user-visible admin metadata to regular metadata.

    Extracts the admin metadata keys that are to be made visible to
    non-administrators, and adds them to the regular metadata structure for the
    passed-in volume.
    """
    visible_admin_meta = {}

    if volume.get('volume_admin_metadata'):
        if isinstance(volume['volume_admin_metadata'], dict):
            volume_admin_metadata = volume['volume_admin_metadata']
            for key in volume_admin_metadata:
                if key in _visible_admin_metadata_keys:
                    visible_admin_meta[key] = volume_admin_metadata[key]
        else:
            for item in volume['volume_admin_metadata']:
                if item['key'] in _visible_admin_metadata_keys:
                    visible_admin_meta[item['key']] = item['value']
    # avoid circular ref when volume is a Volume instance
    elif (volume.get('admin_metadata') and
            isinstance(volume.get('admin_metadata'), dict)):
        for key in _visible_admin_metadata_keys:
            if key in volume['admin_metadata'].keys():
                visible_admin_meta[key] = volume['admin_metadata'][key]

    if not visible_admin_meta:
        return

    # NOTE(zhiyan): update visible administration metadata to
    # volume metadata, administration metadata will rewrite existing key.
    if volume.get('volume_metadata'):
        orig_meta = list(volume.get('volume_metadata'))
        for item in orig_meta:
            if item['key'] in visible_admin_meta.keys():
                item['value'] = visible_admin_meta.pop(item['key'])
        for key, value in visible_admin_meta.items():
            orig_meta.append({'key': key, 'value': value})
        volume['volume_metadata'] = orig_meta
    # avoid circular ref when vol is a Volume instance
    elif (volume.get('metadata') and
            isinstance(volume.get('metadata'), dict)):
        volume['metadata'].update(visible_admin_meta)
    else:
        volume['metadata'] = visible_admin_meta


def validate_integer(value, name, min_value=None, max_value=None):
    """Make sure that value is a valid integer, potentially within range.

    :param value: the value of the integer
    :param name: the name of the integer
    :param min_length: the min_length of the integer
    :param max_length: the max_length of the integer
    :returns: integer
    """
    try:
        value = strutils.validate_integer(value, name, min_value, max_value)
        return value
    except ValueError as e:
        raise webob.exc.HTTPBadRequest(explanation=str(e))


def walk_class_hierarchy(clazz, encountered=None):
    """Walk class hierarchy, yielding most derived classes first."""
    if not encountered:
        encountered = []
    for subclass in clazz.__subclasses__():
        if subclass not in encountered:
            encountered.append(subclass)
            # drill down to leaves first
            for subsubclass in walk_class_hierarchy(subclass, encountered):
                yield subsubclass
            yield subclass


def _keystone_client(context, version=(3, 0)):
    """Creates and returns an instance of a generic keystone client.

    :param context: The request context
    :param version: version of Keystone to request
    :return: keystoneclient.client.Client object
    """
    if context.system_scope is not None:
        auth_plugin = identity.Token(
            auth_url=CONF.keystone_authtoken.auth_url,
            token=context.auth_token,
            system_scope=context.system_scope
        )
    elif context.domain_id is not None:
        auth_plugin = identity.Token(
            auth_url=CONF.keystone_authtoken.auth_url,
            token=context.auth_token,
            domain_id=context.domain_id
        )
    elif context.project_id is not None:
        auth_plugin = identity.Token(
            auth_url=CONF.keystone_authtoken.auth_url,
            token=context.auth_token,
            project_id=context.project_id
        )
    else:
        # We're dealing with an unscoped token from keystone that doesn't
        # carry any authoritative power outside of the user simplify proving
        # they know their own password. This token isn't associated with any
        # authorization target (e.g., system, domain, or project).
        auth_plugin = context.get_auth_plugin()

    client_session = ka_loading.session.Session().load_from_options(
        auth=auth_plugin,
        insecure=CONF.keystone_authtoken.insecure,
        cacert=CONF.keystone_authtoken.cafile,
        key=CONF.keystone_authtoken.keyfile,
        cert=CONF.keystone_authtoken.certfile,
        split_loggers=CONF.service_user.split_loggers)
    return client.Client(auth_url=CONF.keystone_authtoken.auth_url,
                         session=client_session, version=version)


class GenericProjectInfo(object):
    """Abstraction layer for Keystone V2 and V3 project objects"""
    def __init__(self, project_id, project_keystone_api_version,
                 domain_id=None, name=None, description=None):
        self.id = project_id
        self.keystone_api_version = project_keystone_api_version
        self.domain_id = domain_id
        self.name = name
        self.description = description


def get_project(context, project_id):
    """Method to verify project exists in keystone"""
    keystone = _keystone_client(context)
    generic_project = GenericProjectInfo(project_id, keystone.version)
    project = keystone.projects.get(project_id)
    generic_project.domain_id = project.domain_id
    generic_project.name = project.name
    generic_project.description = project.description
    return generic_project


def validate_project_and_authorize(context, project_id, policy_check=None,
                                   validate_only=False):
    try:
        target_project = get_project(context, project_id)
        if not validate_only:
            target_project = {'project_id': target_project.id}
            context.authorize(policy_check, target=target_project)
    except ks_exc.http.NotFound:
        explanation = _("Project with id %s not found." % project_id)
        raise exc.HTTPNotFound(explanation=explanation)
    except exception.NotAuthorized:
        explanation = _("You are not authorized to perform this "
                        "operation.")
        raise exc.HTTPForbidden(explanation=explanation)
