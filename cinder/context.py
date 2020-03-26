# Copyright 2011 OpenStack Foundation
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""RequestContext: context for requests that persist through all of cinder."""

import copy

from keystoneauth1.access import service_catalog as ksa_service_catalog
from keystoneauth1 import plugin
from oslo_config import cfg
from oslo_context import context
from oslo_db.sqlalchemy import enginefacade
from oslo_log import log as logging
from oslo_utils import timeutils
import six

from cinder import exception
from cinder.i18n import _
from cinder.objects import base as objects_base
from cinder import policy

context_opts = [
    cfg.StrOpt('cinder_internal_tenant_project_id',
               help='ID of the project which will be used as the Cinder '
                    'internal tenant.'),
    cfg.StrOpt('cinder_internal_tenant_user_id',
               help='ID of the user to be used in volume operations as the '
                    'Cinder internal tenant.'),
]

CONF = cfg.CONF
CONF.register_opts(context_opts)

LOG = logging.getLogger(__name__)


class _ContextAuthPlugin(plugin.BaseAuthPlugin):
    """A keystoneauth auth plugin that uses the values from the Context.

    Ideally we would use the plugin provided by auth_token middleware however
    this plugin isn't serialized yet so we construct one from the serialized
    auth data.
    """

    def __init__(self, auth_token, sc):
        super(_ContextAuthPlugin, self).__init__()

        self.auth_token = auth_token
        self.service_catalog = ksa_service_catalog.ServiceCatalogV2(sc)

    def get_token(self, *args, **kwargs):
        return self.auth_token

    def get_endpoint(self, session, service_type=None, interface=None,
                     region_name=None, service_name=None, **kwargs):
        return self.service_catalog.url_for(service_type=service_type,
                                            service_name=service_name,
                                            interface=interface,
                                            region_name=region_name)


@enginefacade.transaction_context_provider
class RequestContext(context.RequestContext):
    """Security context and request information.

    Represents the user taking a given action within the system.

    """
    def __init__(self, user_id=None, project_id=None, is_admin=None,
                 read_deleted="no", project_name=None, remote_address=None,
                 timestamp=None, quota_class=None, service_catalog=None,
                 user_auth_plugin=None, **kwargs):
        """Initialize RequestContext.

        :param read_deleted: 'no' indicates deleted records are hidden, 'yes'
            indicates deleted records are visible, 'only' indicates that
            *only* deleted records are visible.

        :param overwrite: Set to False to ensure that the greenthread local
            copy of the index is not overwritten.
        """
        # NOTE(smcginnis): To keep it compatible for code using positional
        # args, explicityly set user_id and project_id in kwargs.
        kwargs.setdefault('user_id', user_id)
        kwargs.setdefault('project_id', project_id)

        super(RequestContext, self).__init__(is_admin=is_admin, **kwargs)

        self.project_name = project_name
        self.read_deleted = read_deleted
        self.remote_address = remote_address
        if not timestamp:
            timestamp = timeutils.utcnow()
        elif isinstance(timestamp, six.string_types):
            timestamp = timeutils.parse_isotime(timestamp)
        self.timestamp = timestamp
        self.quota_class = quota_class

        if service_catalog:
            # Only include required parts of service_catalog
            self.service_catalog = [s for s in service_catalog
                                    if s.get('type') in
                                    ('identity', 'compute', 'object-store',
                                     'image')]
        else:
            # if list is empty or none
            self.service_catalog = []

        # We need to have RequestContext attributes defined
        # when policy.check_is_admin invokes request logging
        # to make it loggable.
        if self.is_admin is None:
            self.is_admin = policy.check_is_admin(self)
        elif self.is_admin and 'admin' not in self.roles:
            self.roles.append('admin')
        self.user_auth_plugin = user_auth_plugin

    def get_auth_plugin(self):
        if self.user_auth_plugin:
            return self.user_auth_plugin
        else:
            return _ContextAuthPlugin(self.auth_token, self.service_catalog)

    def _get_read_deleted(self):
        return self._read_deleted

    def _set_read_deleted(self, read_deleted):
        if read_deleted not in ('no', 'yes', 'only'):
            raise ValueError(_("read_deleted can only be one of 'no', "
                               "'yes' or 'only', not %r") % read_deleted)
        self._read_deleted = read_deleted

    def _del_read_deleted(self):
        del self._read_deleted

    read_deleted = property(_get_read_deleted, _set_read_deleted,
                            _del_read_deleted)

    def to_dict(self):
        result = super(RequestContext, self).to_dict()
        result['user_id'] = self.user_id
        result['project_id'] = self.project_id
        result['project_name'] = self.project_name
        result['domain_id'] = self.domain_id
        result['read_deleted'] = self.read_deleted
        result['remote_address'] = self.remote_address
        result['timestamp'] = self.timestamp.isoformat()
        result['quota_class'] = self.quota_class
        result['service_catalog'] = self.service_catalog
        result['request_id'] = self.request_id
        return result

    @classmethod
    def from_dict(cls, values):
        return cls(user_id=values.get('user_id'),
                   project_id=values.get('project_id'),
                   project_name=values.get('project_name'),
                   domain_id=values.get('domain_id'),
                   read_deleted=values.get('read_deleted'),
                   remote_address=values.get('remote_address'),
                   timestamp=values.get('timestamp'),
                   quota_class=values.get('quota_class'),
                   service_catalog=values.get('service_catalog'),
                   request_id=values.get('request_id'),
                   global_request_id=values.get('global_request_id'),
                   is_admin=values.get('is_admin'),
                   roles=values.get('roles'),
                   auth_token=values.get('auth_token'),
                   user_domain_id=values.get('user_domain'),
                   project_domain_id=values.get('project_domain'),
                   user_domain=values.get('user_domain'),
                   project_domain=values.get('project_domain'),
                   )

    def authorize(self, action, target=None, target_obj=None, fatal=True):
        """Verifies that the given action is valid on the target in this context.

        :param action: string representing the action to be checked.
        :param target: dictionary representing the object of the action
            for object creation this should be a dictionary representing the
            location of the object e.g. ``{'project_id': context.project_id}``.
            If None, then this default target will be considered:
            {'project_id': self.project_id, 'user_id': self.user_id}
        :param: target_obj: dictionary representing the object which will be
            used to update target.
        :param fatal: if False, will return False when an
            exception.PolicyNotAuthorized occurs.

        :raises cinder.exception.NotAuthorized: if verification fails and fatal
            is True.

        :return: returns a non-False value (not necessarily "True") if
            authorized and False if not authorized and fatal is False.
        """
        if target is None:
            target = {'project_id': self.project_id,
                      'user_id': self.user_id}
        if isinstance(target_obj, objects_base.CinderObject):
            # Turn object into dict so target.update can work
            target.update(
                target_obj.obj_to_primitive()['versioned_object.data'] or {})
        else:
            target.update(target_obj or {})

        return policy.authorize(self, action, target, do_raise=fatal,
                                exc=exception.PolicyNotAuthorized)

    def to_policy_values(self):
        policy = super(RequestContext, self).to_policy_values()

        policy['is_admin'] = self.is_admin

        return policy

    def elevated(self, read_deleted=None, overwrite=False):
        """Return a version of this context with admin flag set."""
        context = self.deepcopy()
        context.is_admin = True

        if 'admin' not in context.roles:
            context.roles.append('admin')

        if read_deleted is not None:
            context.read_deleted = read_deleted

        return context

    def deepcopy(self):
        return copy.deepcopy(self)


def get_admin_context(read_deleted="no"):
    return RequestContext(user_id=None,
                          project_id=None,
                          is_admin=True,
                          read_deleted=read_deleted,
                          overwrite=False)


def get_internal_tenant_context():
    """Build and return the Cinder internal tenant context object

    This request context will only work for internal Cinder operations. It will
    not be able to make requests to remote services. To do so it will need to
    use the keystone client to get an auth_token.
    """
    project_id = CONF.cinder_internal_tenant_project_id
    user_id = CONF.cinder_internal_tenant_user_id

    if project_id and user_id:
        return RequestContext(user_id=user_id,
                              project_id=project_id,
                              is_admin=True,
                              overwrite=False)
    else:
        LOG.warning('Unable to get internal tenant context: Missing '
                    'required config parameters.')
        return None
