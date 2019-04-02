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

"""The volumes attachments API."""

from oslo_log import log as logging
import webob

from cinder.api import common
from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.schemas import attachments as attachment
from cinder.api.v3.views import attachments as attachment_views
from cinder.api import validation
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import fields
from cinder.policies import attachments as attachment_policy
from cinder import utils
from cinder.volume import api as volume_api
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)


class AttachmentsController(wsgi.Controller):
    """The Attachments API controller for the OpenStack API."""

    _view_builder_class = attachment_views.ViewBuilder

    allowed_filters = {'volume_id', 'status', 'instance_id', 'attach_status'}

    def __init__(self, ext_mgr=None):
        """Initialize controller class."""
        self.volume_api = volume_api.API()
        self.ext_mgr = ext_mgr
        super(AttachmentsController, self).__init__()

    @wsgi.Controller.api_version(mv.NEW_ATTACH)
    def show(self, req, id):
        """Return data about the given attachment."""
        context = req.environ['cinder.context']
        attachment = objects.VolumeAttachment.get_by_id(context, id)
        return attachment_views.ViewBuilder.detail(attachment)

    @wsgi.Controller.api_version(mv.NEW_ATTACH)
    def index(self, req):
        """Return a summary list of attachments."""
        attachments = self._items(req)
        return attachment_views.ViewBuilder.list(attachments)

    @wsgi.Controller.api_version(mv.NEW_ATTACH)
    def detail(self, req):
        """Return a detailed list of attachments."""
        attachments = self._items(req)
        return attachment_views.ViewBuilder.list(attachments, detail=True)

    @common.process_general_filtering('attachment')
    def _process_attachment_filtering(self, context=None, filters=None,
                                      req_version=None):
        utils.remove_invalid_filter_options(context, filters,
                                            self.allowed_filters)

    def _items(self, req):
        """Return a list of attachments, transformed through view builder."""
        context = req.environ['cinder.context']
        req_version = req.api_version_request

        # Pop out non search_opts and create local variables
        search_opts = req.GET.copy()
        sort_keys, sort_dirs = common.get_sort_params(search_opts)
        marker, limit, offset = common.get_pagination_params(search_opts)

        self._process_attachment_filtering(context=context,
                                           filters=search_opts,
                                           req_version=req_version)
        if search_opts.get('instance_id', None):
            search_opts['instance_uuid'] = search_opts.pop('instance_id', None)
        if context.is_admin and 'all_tenants' in search_opts:
            del search_opts['all_tenants']
            return objects.VolumeAttachmentList.get_all(
                context, search_opts=search_opts, marker=marker, limit=limit,
                offset=offset, sort_keys=sort_keys, sort_direction=sort_dirs)
        else:
            return objects.VolumeAttachmentList.get_all_by_project(
                context, context.project_id, search_opts=search_opts,
                marker=marker, limit=limit, offset=offset, sort_keys=sort_keys,
                sort_direction=sort_dirs)

    @wsgi.Controller.api_version(mv.NEW_ATTACH)
    @wsgi.response(200)
    @validation.schema(attachment.create)
    def create(self, req, body):
        """Create an attachment.

        This method can be used to create an empty attachment (reserve) or to
        create and initialize a volume attachment based on the provided input
        parameters.

        If the caller does not yet have the connector information but needs to
        reserve an attachment for the volume (ie Nova BootFromVolume) the
        create can be called with just the volume-uuid and the server
        identifier. This will reserve an attachment, mark the volume as
        reserved and prevent any new attachment_create calls from being made
        until the attachment is updated (completed).

        The alternative is that the connection can be reserved and initialized
        all at once with a single call if the caller has all of the required
        information (connector data) at the time of the call.

        NOTE: In Nova terms server == instance, the server_id parameter
        referenced below is the UUID of the Instance, for non-nova consumers
        this can be a server UUID or some other arbitrary unique identifier.

        Expected format of the input parameter 'body':

        .. code-block:: json

            {
                "attachment":
                {
                    "volume_uuid": "volume-uuid",
                    "instance_uuid": "nova-server-uuid",
                    "connector": "null|<connector-object>"
                }
            }

        Example connector:

        .. code-block:: json

            {
                "connector":
                {
                    "initiator": "iqn.1993-08.org.debian:01:cad181614cec",
                    "ip": "192.168.1.20",
                    "platform": "x86_64",
                    "host": "tempest-1",
                    "os_type": "linux2",
                    "multipath": false,
                    "mountpoint": "/dev/vdb",
                    "mode": "null|rw|ro"
                }
            }

        NOTE all that's required for a reserve is volume_uuid
        and an instance_uuid.

        returns: A summary view of the attachment object
        """
        context = req.environ['cinder.context']
        instance_uuid = body['attachment']['instance_uuid']
        volume_uuid = body['attachment']['volume_uuid']
        volume_ref = objects.Volume.get_by_id(
            context,
            volume_uuid)
        args = {'connector': body['attachment'].get('connector', None)}

        if req.api_version_request.matches(mv.ATTACHMENT_CREATE_MODE_ARG):
            # We check for attach_mode here and default to `null`
            # if nothing's provided.  This seems odd to not just
            # set `rw`, BUT we want to keep compatability with
            # setting the mode via the connector for now, so we
            # use `null` as an identifier to distinguish that case
            args['attach_mode'] = body['attachment'].get('mode', 'null')

        err_msg = None
        try:
            attachment_ref = (
                self.volume_api.attachment_create(context,
                                                  volume_ref,
                                                  instance_uuid,
                                                  **args))
        except (exception.NotAuthorized,
                exception.InvalidVolume):
            raise
        except exception.CinderException as ex:
            err_msg = _(
                "Unable to create attachment for volume (%s).") % ex.msg
            LOG.exception(err_msg)
        except Exception as ex:
            err_msg = _("Unable to create attachment for volume.")
            LOG.exception(err_msg)
        finally:
            if err_msg:
                raise webob.exc.HTTPInternalServerError(explanation=err_msg)
        return attachment_views.ViewBuilder.detail(attachment_ref)

    @wsgi.Controller.api_version(mv.NEW_ATTACH)
    @validation.schema(attachment.update)
    def update(self, req, id, body):
        """Update an attachment record.

        Update a reserved attachment record with connector information and set
        up the appropriate connection_info from the driver.

        Expected format of the input parameter 'body':

        .. code:: json

            {
                "attachment":
                {
                    "connector":
                    {
                        "initiator": "iqn.1993-08.org.debian:01:cad181614cec",
                        "ip": "192.168.1.20",
                        "platform": "x86_64",
                        "host": "tempest-1",
                        "os_type": "linux2",
                        "multipath": false,
                        "mountpoint": "/dev/vdb",
                        "mode": "None|rw|ro"
                    }
                }
            }

        """
        context = req.environ['cinder.context']
        attachment_ref = (
            objects.VolumeAttachment.get_by_id(context, id))
        connector = body['attachment']['connector']
        err_msg = None
        try:
            attachment_ref = (
                self.volume_api.attachment_update(context,
                                                  attachment_ref,
                                                  connector))
        except exception.NotAuthorized:
            raise
        except exception.CinderException as ex:
            err_msg = (
                _("Unable to update attachment.(%s).") % ex.msg)
            LOG.exception(err_msg)
        except Exception:
            err_msg = _("Unable to update the attachment.")
            LOG.exception(err_msg)
        finally:
            if err_msg:
                raise webob.exc.HTTPInternalServerError(explanation=err_msg)

        # TODO(jdg): Test this out some more, do we want to return and object
        # or a dict?
        return attachment_views.ViewBuilder.detail(attachment_ref)

    @wsgi.Controller.api_version(mv.NEW_ATTACH)
    def delete(self, req, id):
        """Delete an attachment.

        Disconnects/Deletes the specified attachment, returns a list of any
        known shared attachment-id's for the effected backend device.

        returns: A summary list of any attachments sharing this connection

        """
        context = req.environ['cinder.context']
        attachment = objects.VolumeAttachment.get_by_id(context, id)
        attachments = self.volume_api.attachment_delete(context, attachment)
        return attachment_views.ViewBuilder.list(attachments)

    @wsgi.response(204)
    @wsgi.Controller.api_version(mv.NEW_ATTACH_COMPLETION)
    @wsgi.action('os-complete')
    def complete(self, req, id, body):
        """Mark a volume attachment process as completed (in-use)."""
        context = req.environ['cinder.context']
        attachment_ref = (
            objects.VolumeAttachment.get_by_id(context, id))
        volume_ref = objects.Volume.get_by_id(
            context,
            attachment_ref.volume_id)
        context.authorize(attachment_policy.COMPLETE_POLICY,
                          target_obj=attachment_ref)
        attachment_ref.update(
            {'attach_status': fields.VolumeAttachStatus.ATTACHED})
        attachment_ref.save()
        volume_ref.update({'status': 'in-use', 'attach_status': 'attached'})
        volume_ref.save()
        volume_utils.notify_about_volume_usage(context, volume_ref,
                                               "attach.end")


def create_resource(ext_mgr):
    """Create the wsgi resource for this controller."""
    return wsgi.Resource(AttachmentsController(ext_mgr))
