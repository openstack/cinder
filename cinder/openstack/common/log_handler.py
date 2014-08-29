# Copyright 2013 IBM Corp.
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
import logging

from oslo.config import cfg

from cinder import rpc


class PublishErrorsHandler(logging.Handler):
    def emit(self, record):
        # NOTE(flaper87): This will have to be changed in the
        # future. Leaving for backwar compatibility
        if ('cinder.openstack.common.notifier.log_notifier' in
                cfg.CONF.notification_driver):
            return
        msg = record.getMessage()
        rpc.get_notifier('error.publisher').error(None, 'error_notification',
                                                  dict(error=msg))
