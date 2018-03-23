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


from six.moves import http_client
import webob

from cinder.api import common
from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.v3.views import messages as messages_view
from cinder.message import api as message_api
from cinder.message import defined_messages
from cinder.message import message_field
from cinder.policies import messages as policy


class MessagesController(wsgi.Controller):
    """The User Messages API controller for the OpenStack API."""

    _view_builder_class = messages_view.ViewBuilder

    def __init__(self, ext_mgr):
        self.message_api = message_api.API()
        self.ext_mgr = ext_mgr
        super(MessagesController, self).__init__()

    def _build_user_message(self, message):
        # NOTE(tommylikehu): if the `action_id` is empty, we use 'event_id'
        # to translate the user message.
        if message is None:
            return
        if message['action_id'] is None and message['event_id'] is not None:
            message['user_message'] = defined_messages.get_message_text(
                message['event_id'])
        else:
            message['user_message'] = "%s:%s" % (
                message_field.translate_action(message['action_id']),
                message_field.translate_detail(message['detail_id']))

    @wsgi.Controller.api_version(mv.MESSAGES)
    def show(self, req, id):
        """Return the given message."""
        context = req.environ['cinder.context']

        # Not found exception will be handled at the wsgi level
        message = self.message_api.get(context, id)

        context.authorize(policy.GET_POLICY, target_obj=message)

        self._build_user_message(message)
        return self._view_builder.detail(req, message)

    @wsgi.Controller.api_version(mv.MESSAGES)
    def delete(self, req, id):
        """Delete a message."""
        context = req.environ['cinder.context']

        # Not found exception will be handled at the wsgi level
        message = self.message_api.get(context, id)
        context.authorize(policy.DELETE_POLICY, target_obj=message)
        self.message_api.delete(context, message)

        return webob.Response(status_int=http_client.NO_CONTENT)

    @wsgi.Controller.api_version(mv.MESSAGES)
    def index(self, req):
        """Returns a list of messages, transformed through view builder."""
        context = req.environ['cinder.context']
        api_version = req.api_version_request
        context.authorize(policy.GET_ALL_POLICY)
        filters = None
        marker = None
        limit = None
        offset = None
        sort_keys = None
        sort_dirs = None

        if api_version.matches(mv.MESSAGES_PAGINATION):
            filters = req.params.copy()
            marker, limit, offset = common.get_pagination_params(filters)
            sort_keys, sort_dirs = common.get_sort_params(filters)

        if api_version.matches(mv.RESOURCE_FILTER):
            support_like = (True if api_version.matches(
                mv.LIKE_FILTER) else False)
            common.reject_invalid_filters(context, filters, 'message',
                                          support_like)

        messages = self.message_api.get_all(context, filters=filters,
                                            marker=marker, limit=limit,
                                            offset=offset,
                                            sort_keys=sort_keys,
                                            sort_dirs=sort_dirs)

        for message in messages:
            self._build_user_message(message)
        messages = self._view_builder.index(req, messages)
        return messages


def create_resource(ext_mgr):
    return wsgi.Resource(MessagesController(ext_mgr))
