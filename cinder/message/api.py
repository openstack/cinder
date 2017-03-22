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
"""
Handles all requests related to user facing messages.
"""
import datetime

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils

from cinder.db import base
from cinder.message import message_field


messages_opts = [
    cfg.IntOpt('message_ttl', default=2592000,
               help='message minimum life in seconds.'),
    cfg.IntOpt('message_reap_interval', default=86400,
               help='interval between periodic task runs to clean expired '
                    'messages in seconds.')
]


CONF = cfg.CONF
CONF.register_opts(messages_opts)

LOG = logging.getLogger(__name__)


class API(base.Base):
    """API for handling user messages."""

    def create(self, context, action,
               resource_type=message_field.Resource.VOLUME,
               resource_uuid=None, exception=None, detail=None, level="ERROR"):
        """Create a message with the specified information."""
        LOG.info("Creating message record for request_id = %s",
                 context.request_id)
        # Updates expiry time for message as per message_ttl config.
        expires_at = (timeutils.utcnow() + datetime.timedelta(
                      seconds=CONF.message_ttl))

        detail_id = message_field.translate_detail_id(exception, detail)
        message_record = {'project_id': context.project_id,
                          'request_id': context.request_id,
                          'resource_type': resource_type,
                          'resource_uuid': resource_uuid,
                          'action_id': action[0] if action else '',
                          'message_level': level,
                          'event_id': "VOLUME_%s_%s_%s" % (resource_type,
                                                           action[0],
                                                           detail_id),
                          'detail_id': detail_id,
                          'expires_at': expires_at}
        try:
            self.db.message_create(context, message_record)
        except Exception:
            LOG.exception("Failed to create message record "
                          "for request_id %s", context.request_id)

    def get(self, context, id):
        """Return message with the specified id."""
        return self.db.message_get(context, id)

    def get_all(self, context, filters=None, marker=None,
                limit=None, offset=None, sort_keys=None,
                sort_dirs=None):
        """Return all messages for the given context."""

        filters = filters or {}

        messages = self.db.message_get_all(context, filters=filters,
                                           marker=marker, limit=limit,
                                           offset=offset, sort_keys=sort_keys,
                                           sort_dirs=sort_dirs)
        return messages

    def delete(self, context, id):
        """Delete message with the specified id."""
        ctx = context.elevated()
        return self.db.message_destroy(ctx, id)

    def cleanup_expired_messages(self, context):
        ctx = context.elevated()
        count = self.db.cleanup_expired_messages(ctx)
        LOG.info("Deleted %s expired messages.", count)
