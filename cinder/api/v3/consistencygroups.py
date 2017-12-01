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

"""The consistencygroups V3 API."""

from oslo_log import log as logging
from six.moves import http_client
import webob
from webob import exc

from cinder.api.contrib import consistencygroups as cg_v2
from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.i18n import _
from cinder.policies import groups as group_policy

LOG = logging.getLogger(__name__)


class ConsistencyGroupsController(cg_v2.ConsistencyGroupsController):
    """The ConsistencyGroups API controller for the OpenStack API V3."""

    def _check_update_parameters_v3(self, req, name, description, add_volumes,
                                    remove_volumes):
        allow_empty = req.api_version_request.matches(
            mv.CG_UPDATE_BLANK_PROPERTIES, None)
        if allow_empty:
            if (name is None and description is None
                    and not add_volumes and not remove_volumes):
                msg = _("Must specify one or more of the following keys to "
                        "update: name, description, "
                        "add_volumes, remove_volumes.")
                raise exc.HTTPBadRequest(explanation=msg)
        else:
            if not (name or description or add_volumes or remove_volumes):
                msg = _("Name, description, add_volumes, and remove_volumes "
                        "can not be all empty in the request body.")
                raise exc.HTTPBadRequest(explanation=msg)
        return allow_empty

    def update(self, req, id, body):
        """Update the consistency group.

        Expected format of the input parameter 'body':

        .. code-block:: json

            {
                "consistencygroup":
                {
                    "name": "my_cg",
                    "description": "My consistency group",
                    "add_volumes": "volume-uuid-1,volume-uuid-2,...",
                    "remove_volumes": "volume-uuid-8,volume-uuid-9,..."
                }
            }

        """
        LOG.debug('Update called for consistency group %s.', id)
        if not body:
            msg = _("Missing request body.")
            raise exc.HTTPBadRequest(explanation=msg)

        self.assert_valid_body(body, 'consistencygroup')
        context = req.environ['cinder.context']
        group = self._get(context, id)
        context.authorize(group_policy.UPDATE_POLICY, target_obj=group)
        consistencygroup = body.get('consistencygroup', None)
        self.validate_name_and_description(consistencygroup)
        name = consistencygroup.get('name', None)
        description = consistencygroup.get('description', None)
        add_volumes = consistencygroup.get('add_volumes', None)
        remove_volumes = consistencygroup.get('remove_volumes', None)

        allow_empty = self._check_update_parameters_v3(req, name,
                                                       description,
                                                       add_volumes,
                                                       remove_volumes)
        self._update(context, group, name, description, add_volumes,
                     remove_volumes, allow_empty)
        return webob.Response(status_int=http_client.ACCEPTED)


def create_resource():
    return wsgi.Resource(ConsistencyGroupsController())
