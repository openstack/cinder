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


from cinder.api import common


class ViewBuilder(common.ViewBuilder):
    """Model a server API response as a python dictionary."""

    _collection_name = "messages"

    def index(self, request, messages, message_count=None):
        """Show a list of messages."""
        return self._list_view(self.detail, request, messages, message_count)

    def detail(self, request, message):
        """Detailed view of a single message."""
        message_ref = {
            'id': message.get('id'),
            'event_id': message.get('event_id'),
            'user_message': message.get('user_message'),
            'message_level': message.get('message_level'),
            'created_at': message.get('created_at'),
            'guaranteed_until': message.get('expires_at'),
            'request_id': message.get('request_id'),
            'links': self._get_links(request, message['id']),
        }

        if message.get('resource_type'):
            message_ref['resource_type'] = message.get('resource_type')
        if message.get('resource_uuid'):
            message_ref['resource_uuid'] = message.get('resource_uuid')

        return {'message': message_ref}

    def _list_view(self, func, request, messages, message_count=None,
                   coll_name=_collection_name):
        """Provide a view for a list of messages.

        :param func: Function used to format the message data
        :param request: API request
        :param messages: List of messages in dictionary format
        :param message_count: Length of the original list of messages
        :param coll_name: Name of collection, used to generate the next link
                          for a pagination query
        :returns: message data in dictionary format
        """
        messages_list = [func(request, message)['message']
                         for message in messages]
        messages_links = self._get_collection_links(request,
                                                    messages,
                                                    coll_name,
                                                    message_count)
        messages_dict = dict(messages=messages_list)

        if messages_links:
            messages_dict['messages_links'] = messages_links

        return messages_dict
