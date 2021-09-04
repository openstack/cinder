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
    """API for handling user messages.

    Cinder Messages describe the outcome of a user action using predefined
    fields that are members of objects defined in the
    cinder.message.message_field package.  They are intended to be exposed to
    end users.  Their primary purpose is to provide end users with a means of
    discovering what went wrong when an asynchronous action in the Volume REST
    API (for which they've already received a 2xx response) fails.

    Messages contain an 'expires_at' field based on the creation time plus the
    value of the 'message_ttl' configuration option.  They are periodically
    reaped by a task of the SchedulerManager class whose periodicity is given
    by the 'message_reap_interval' configuration option.

    """

    def create(self, context, action,
               resource_type=message_field.Resource.VOLUME,
               resource_uuid=None, exception=None, detail=None, level="ERROR"):
        """Create a message record with the specified information.

        :param context: current context object
        :param action:
            a message_field.Action field describing what was taking place
            when this message was created
        :param resource_type:
            a message_field.Resource field describing the resource this
            message applies to.  Default is message_field.Resource.VOLUME
        :param resource_uuid:
            the resource ID if this message applies to an existing resource.
            Default is None
        :param exception:
            if an exception has occurred, you can pass it in and it will be
            translated into an appropriate message detail ID (possibly
            message_field.Detail.UNKNOWN_ERROR).  The message
            in the exception itself is ignored in order not to expose
            sensitive information to end users.  Default is None
        :param detail:
            a message_field.Detail field describing the event the message
            is about.  Default is None, in which case
            message_field.Detail.UNKNOWN_ERROR will be used for the message
            unless an exception in the message_field.EXCEPTION_DETAIL_MAPPINGS
            is passed; in that case the message_field.Detail field that's
            mapped to the exception is used.
        :param level:
            a string describing the severity of the message.  Suggested
            values are 'INFO', 'ERROR', 'WARNING'.  Default is 'ERROR'.
        """

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

    def create_from_request_context(self, context, exception=None,
                                    detail=None, level="ERROR"):
        """Create a message record with the specified information.

        :param context:
            current context object which we must have populated with the
            message_action, message_resource_type and message_resource_id
            fields
        :param exception:
            if an exception has occurred, you can pass it in and it will be
            translated into an appropriate message detail ID (possibly
            message_field.Detail.UNKNOWN_ERROR).  The message
            in the exception itself is ignored in order not to expose
            sensitive information to end users.  Default is None
        :param detail:
            a message_field.Detail field describing the event the message
            is about.  Default is None, in which case
            message_field.Detail.UNKNOWN_ERROR will be used for the message
            unless an exception in the message_field.EXCEPTION_DETAIL_MAPPINGS
            is passed; in that case the message_field.Detail field that's
            mapped to the exception is used.
        :param level:
            a string describing the severity of the message.  Suggested
            values are 'INFO', 'ERROR', 'WARNING'.  Default is 'ERROR'.
        """

        self.create(context=context,
                    action=context.message_action,
                    resource_type=context.message_resource_type,
                    resource_uuid=context.message_resource_id,
                    exception=exception,
                    detail=detail,
                    level=level)

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
