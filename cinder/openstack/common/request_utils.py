# Copyright 2014 Rackspace Hosting
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

"""
Utilities for linking request ID's across service calls.
"""

import logging

from openstack.common.gettextutils import _  # noqa


LOG = logging.getLogger(__name__)


def link_request_ids(context, source_id, target_id=None, stage=None,
                     target_name=None, notifier=None):
    """Links the Request ID from the Source service to
       the Request ID returned from the Target service.

       Linkages are logged and emitted as INFO notifications.

       :params context: context object
       :params source_id: the Request ID of the source
       :params target_id: the Request ID of the target
       :params stage: optional event name extension to
                      indicate which part of the linkage
                      this is.
       :params target_name: human readable name of the
                            target system you are talking to.
       :params notifier: notifier object

       A typical use case is: System A asking System B
       to perform some action. The linkages might look
       like this:

       link_request_ids(sys_A.request_ID, stage="start")
       # send request to System B and get request ID
       link_request_ids(sys_A.request_ID, target_id=sys_B.request.ID)
       # optionally wait for System B to complete
       link_request_ids(sys_A.request_ID, target_id=sys_B.request.ID,
                        stage="end")

       But, it could be as simple as:
       link_request_ids(sys_A.request_ID, target_id=sys_B.request.ID)
       """

    event_name = "request.link"
    if stage:
        event_name += ".%s" % stage

    rtarget_id = ""
    if target_id:
        rtarget_id = _("TargetId=%(id)s ") % {'id': target_id}

    rtarget_name = ""
    if target_name:
        rtarget_name = _("Target='%(name)s' ") % {'name': target_name}

    arrow = ""
    if target_name or target_id:
        arrow = " -> "

    LOG.info(_("Request ID Link: %(event_name)s '%(source_id)s'%(arrow)s"
               "%(target_name)s%(target_id)s") % {"event_name": event_name,
                                                  "source_id": source_id,
                                                  "target_name": rtarget_name,
                                                  "arrow": arrow,
                                                  "target_id": rtarget_id})

    if notifier:
        payload = {"source_request_id": source_id,
                   "target_request_id": target_id,
                   "target_name": target_name,
                   "stage": stage}
        notifier.info(context, event_name, payload)
