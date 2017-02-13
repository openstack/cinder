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
from cinder.i18n import _LE, _LI
from cinder.message import defined_messages


messages_opts = [
    cfg.IntOpt('message_ttl', default=2592000,
               help='message minimum life in seconds.')]

CONF = cfg.CONF
CONF.register_opts(messages_opts)

LOG = logging.getLogger(__name__)


class API(base.Base):
    """API for handling user messages."""

    def create(self, context, event_id, project_id, resource_type=None,
               resource_uuid=None, level="ERROR"):
        """Create a message with the specified information."""
        LOG.info(_LI("Creating message record for request_id = %s"),
                 context.request_id)
        # Ensure valid event_id
        defined_messages.get_message_text(event_id)
        # Updates expiry time for message as per message_ttl config.
        expires_at = (timeutils.utcnow() + datetime.timedelta(
                      seconds=CONF.message_ttl))

        message_record = {'project_id': project_id,
                          'request_id': context.request_id,
                          'resource_type': resource_type,
                          'resource_uuid': resource_uuid,
                          'event_id': event_id,
                          'message_level': level,
                          'expires_at': expires_at}
        try:
            self.db.message_create(context, message_record)
        except Exception:
            LOG.exception(_LE("Failed to create message record "
                              "for request_id %s"), context.request_id)

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
