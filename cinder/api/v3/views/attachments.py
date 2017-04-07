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

from oslo_utils import timeutils


class ViewBuilder(object):
    """Model an attachment API response as a python dictionary."""

    _collection_name = "attachments"

    @staticmethod
    def _normalize(date):
        if date:
            return timeutils.normalize_time(date)
        return ''

    @classmethod
    def detail(cls, attachment, flat=False):
        """Detailed view of an attachment."""
        result = cls.summary(attachment, flat=True)
        result.update(
            attached_at=cls._normalize(attachment.attach_time),
            detached_at=cls._normalize(attachment.detach_time),
            attach_mode=attachment.attach_mode,
            connection_info=attachment.connection_info)
        if flat:
            return result
        return {'attachment': result}

    @staticmethod
    def summary(attachment, flat=False):
        """Non detailed view of an attachment."""
        result = {
            'id': attachment.id,
            'status': attachment.attach_status,
            'instance': attachment.instance_uuid,
            'volume_id': attachment.volume_id, }
        if flat:
            return result
        return {'attachment': result}

    @classmethod
    def list(cls, attachments, detail=False):
        """Build a view of a list of attachments."""
        func = cls.detail if detail else cls.summary
        return {'attachments': [func(attachment, flat=True) for attachment in
                                attachments]}
