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

"""The messages API."""


import webob

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder.api.v3.views import messages as messages_view
from cinder.message import api as message_api
from cinder.message import defined_messages
import cinder.policy


MESSAGES_BASE_MICRO_VERSION = '3.3'


def check_policy(context, action, target_obj=None):
    target = {
        'project_id': context.project_id,
        'user_id': context.user_id,
    }
    target.update(target_obj or {})

    _action = 'message:%s' % action
    cinder.policy.enforce(context, _action, target)


class MessagesController(wsgi.Controller):
    """The User Messages API controller for the OpenStack API."""

    _view_builder_class = messages_view.ViewBuilder

    def __init__(self, ext_mgr):
        self.message_api = message_api.API()
        self.ext_mgr = ext_mgr
        super(MessagesController, self).__init__()

    @wsgi.Controller.api_version(MESSAGES_BASE_MICRO_VERSION)
    def show(self, req, id):
        """Return the given message."""
        context = req.environ['cinder.context']

        # Not found exception will be handled at the wsgi level
        message = self.message_api.get(context, id)

        check_policy(context, 'get', message)

        # Fetches message text based on event id passed to it.
        message['user_message'] = defined_messages.get_message_text(
            message['event_id'])

        return self._view_builder.detail(req, message)

    @wsgi.Controller.api_version(MESSAGES_BASE_MICRO_VERSION)
    def delete(self, req, id):
        """Delete a message."""
        context = req.environ['cinder.context']

        # Not found exception will be handled at the wsgi level
        message = self.message_api.get(context, id)
        check_policy(context, 'delete', message)
        self.message_api.delete(context, message)

        return webob.Response(status_int=204)

    @wsgi.Controller.api_version(MESSAGES_BASE_MICRO_VERSION)
    def index(self, req):
        """Returns a list of messages, transformed through view builder."""
        context = req.environ['cinder.context']
        check_policy(context, 'get_all')
        filters = None
        marker = None
        limit = None
        offset = None
        sort_keys = None
        sort_dirs = None

        if (req.api_version_request.matches("3.5")):
            filters = req.params.copy()
            marker, limit, offset = common.get_pagination_params(filters)
            sort_keys, sort_dirs = common.get_sort_params(filters)

        messages = self.message_api.get_all(context, filters=filters,
                                            marker=marker, limit=limit,
                                            offset=offset,
                                            sort_keys=sort_keys,
                                            sort_dirs=sort_dirs)

        for message in messages:
            # Fetches message text based on event id passed to it.
            user_message = defined_messages.get_message_text(
                message['event_id'])
            message['user_message'] = user_message

        messages = self._view_builder.index(req, messages)
        return messages


def create_resource(ext_mgr):
    return wsgi.Resource(MessagesController(ext_mgr))
