# Copyright (c) 2017 Veritas Technologies LLC.  All rights reserved.
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

import json
import uuid

from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import exception
from cinder.privsep import hscli
from cinder.volume.drivers.veritas import hs_constants as constants

LOG = logging.getLogger(__name__)


def _populate_message_body(kwargs):
    message_body = {}
    # Build message body from kwargs
    for key, value in kwargs.items():
        if value is not None:
            message_body[key] = value

    return message_body


def generate_routingkey():
    return six.text_type(uuid.uuid1())


def get_guid_with_curly_brackets(guid):
    return "{%s}" % guid if guid else guid


def get_hyperscale_image_id():
    return "{%s}" % uuid.uuid1()


def get_hyperscale_version():

    version = None
    cmd_err = None
    try:
        cmd_arg = {'operation': 'version'}
        # create a json for cmd argument
        cmdarg_json = json.dumps(cmd_arg)

        # call hscli for version
        (cmd_out, cmd_err) = hscli.hsexecute(cmdarg_json)

        # cmd_err should be None in case of successful execution of cmd
        if not cmd_err:
            processed_output = process_cmd_out(cmd_out)
            version = processed_output.get('payload')
        else:
            LOG.error("Error %s in getting hyperscale version",
                      cmd_err)
            raise exception.ErrorInHyperScaleVersion(cmd_err=cmd_err)
    except (exception.UnableToExecuteHyperScaleCmd,
            exception.UnableToProcessHyperScaleCmdOutput):
        LOG.error("Exception in running the command for version",
                  exc_info=True)
        raise exception.UnableToExecuteHyperScaleCmd(command="version")

    return version


def get_datanode_id():

    dnid = None
    cmd_out = None
    cmd_err = None
    try:
        cmd_arg = {'operation': 'get_datanode_id'}
        # create a json for cmd argument
        cmdarg_json = json.dumps(cmd_arg)

        # call hscli for get_datanode_id
        (cmd_out, cmd_err) = hscli.hsexecute(cmdarg_json)

        # cmd_err should be None in case of successful execution of cmd
        if not cmd_err:
            processed_output = process_cmd_out(cmd_out)
            dnid = processed_output.get('payload')
        else:
            LOG.error("Error %s in getting datanode hypervisor id",
                      cmd_err)
            raise exception.UnableToExecuteHyperScaleCmd(
                command=cmdarg_json)
    except exception.UnableToExecuteHyperScaleCmd:
        with excutils.save_and_reraise_exception():
            LOG.debug("Unable to execute get_datanode_id", exc_info=True)

    except exception.UnableToProcessHyperScaleCmdOutput:
        with excutils.save_and_reraise_exception():
            LOG.debug("Unable to process get_datanode_id output",
                      exc_info=True)
    return dnid


def episodic_snap(meta):

    cmd_out = None
    cmd_err = None
    out_meta = None
    try:
        cmd_arg = {}
        cmd_arg['operation'] = 'episodic_snap'
        cmd_arg['metadata'] = meta
        # create a json for cmd argument
        cmdarg_json = json.dumps(cmd_arg)

        # call hscli for episodic_snap
        (cmd_out, cmd_err) = hscli.hsexecute(cmdarg_json)

        # cmd_err should be None in case of successful execution of cmd
        if not cmd_err:
            processed_output = process_cmd_out(cmd_out)
            out_meta = processed_output.get('payload')
        else:
            LOG.error("Error %s in processing episodic_snap",
                      cmd_err)
            raise exception.UnableToExecuteHyperScaleCmd(
                command=cmdarg_json)
    except exception.UnableToExecuteHyperScaleCmd:
        with excutils.save_and_reraise_exception():
            LOG.debug("Unable to execute episodic_snap", exc_info=True)

    except exception.UnableToProcessHyperScaleCmdOutput:
        with excutils.save_and_reraise_exception():
            LOG.debug("Unable to process episodic_snap output",
                      exc_info=True)
    return out_meta


def get_image_path(image_id, op_type='image'):

    cmd_out = None
    cmd_err = None
    image_path = None
    try:
        cmd_arg = {}
        if op_type == 'image':
            cmd_arg['operation'] = 'get_image_path'
        elif op_type == 'volume':
            cmd_arg['operation'] = 'get_volume_path'
        cmd_arg['image_id'] = image_id
        # create a json for cmd argument
        cmdarg_json = json.dumps(cmd_arg)

        # call hscli for get_image_path
        (cmd_out, cmd_err) = hscli.hsexecute(cmdarg_json)

        # cmd_err should be None in case of successful execution of cmd
        if not cmd_err:
            processed_output = process_cmd_out(cmd_out)
            image_path = processed_output.get('payload')
        else:
            LOG.error("Error %s in processing get_image_path",
                      cmd_err)
            raise exception.UnableToExecuteHyperScaleCmd(
                command=cmdarg_json)
    except exception.UnableToExecuteHyperScaleCmd:
        with excutils.save_and_reraise_exception():
            LOG.debug("Unable to execute get_image_path", exc_info=True)

    except exception.UnableToProcessHyperScaleCmdOutput:
        with excutils.save_and_reraise_exception():
            LOG.debug("Unable to process get_image_path output",
                      exc_info=True)
    return image_path


def update_image(image_path, volume_id, hs_img_id):
    cmd_out = None
    cmd_err = None
    output = None
    try:
        cmd_arg = {}
        cmd_arg['operation'] = 'update_image'
        cmd_arg['image_path'] = image_path
        cmd_arg['volume_id'] = volume_id
        cmd_arg['hs_image_id'] = hs_img_id
        # create a json for cmd argument
        cmdarg_json = json.dumps(cmd_arg)

        (cmd_out, cmd_err) = hscli.hsexecute(cmdarg_json)

        # cmd_err should be None in case of successful execution of cmd
        if not cmd_err:
            output = process_cmd_out(cmd_out)
        else:
            LOG.error("Error %s in execution of update_image",
                      cmd_err)
            raise exception.UnableToExecuteHyperScaleCmd(
                command=cmdarg_json)
    except exception.UnableToExecuteHyperScaleCmd:
        with excutils.save_and_reraise_exception():
            LOG.debug("Unable to execute update_image", exc_info=True)

    except exception.UnableToProcessHyperScaleCmdOutput:
        with excutils.save_and_reraise_exception():
            LOG.debug("Unable to process update_image output",
                      exc_info=True)
    return output


def process_cmd_out(cmd_out):
    """Process the cmd output."""

    output = None

    try:
        # get the python object from the cmd_out
        output = json.loads(cmd_out)
        error_code = output.get('err_code')
        if error_code:
            error_message = output.get('err_msg')
            operation = output.get('token')
            LOG.error("Failed to perform %(operation)s with error code"
                      " %(err_code)s, error message is %(err_msg)s",
                      {"operation": operation,
                       "err_code": error_code,
                       "err_msg": error_message})
    except ValueError:
        raise exception.UnableToProcessHyperScaleCmdOutput(cmd_out=cmd_out)

    return output


def check_for_setup_error():
    return True


def get_configuration(persona):
    """Get required configuration from controller."""

    msg_body = {'persona': persona}
    configuration = None
    try:
        cmd_out, cmd_error = message_controller(
            constants.HS_CONTROLLER_EXCH,
            'hyperscale.controller.get.configuration',
            **msg_body)
        LOG.debug("Response Message from Controller: %s", cmd_out)
        payload = cmd_out.get('payload')
        configuration = payload.get('config_data')

    except (exception.ErrorInSendingMsg,
            exception.UnableToExecuteHyperScaleCmd,
            exception.UnableToProcessHyperScaleCmdOutput):
            LOG.exception("Failed to get configuration from controller")
            raise exception.ErrorInFetchingConfiguration(persona=persona)

    return configuration


def _send_message(exchange, routing_key, message_token, **kwargs):
    """Send message to specified node."""

    cmd_out = None
    cmd_err = None
    processed_output = None
    msg = None
    try:
        LOG.debug("Sending message: %s", message_token)

        # Build message from kwargs
        message_body = _populate_message_body(kwargs)
        cmd_arg = {}
        cmd_arg["operation"] = "message"
        cmd_arg["msg_body"] = message_body
        cmd_arg["msg_token"] = message_token
        # exchange name
        cmd_arg["exchange_name"] = exchange
        # routing key
        cmd_arg["routing_key"] = routing_key
        # create a json for cmd argument
        cmdarg_json = json.dumps(cmd_arg)

        (cmd_out, cmd_err) = hscli.hsexecute(cmdarg_json)

        # cmd_err should be none in case of successful execution of cmd
        if cmd_err:
            LOG.debug("Sending message failed. Error %s", cmd_err)
            raise exception.ErrorInSendingMsg(cmd_err=cmd_err)
        else:
            processed_output = process_cmd_out(cmd_out)

    except exception.UnableToExecuteHyperScaleCmd:
        with excutils.save_and_reraise_exception():
            msg = ("Unable to execute HyperScale command for %(cmd)s"
                   " to exchange %(exch)s with key %(rt_key)s")
            LOG.debug(msg, {"cmd": message_token,
                            "exch": exchange,
                            "rt_key": routing_key},
                      exc_info=True)

    except exception.UnableToProcessHyperScaleCmdOutput:
        with excutils.save_and_reraise_exception():
            msg = ("Unable to process msg %(message)s"
                   " to exchange %(exch)s with key %(rt_key)s")
            LOG.debug(msg, {"message": message_token,
                            "exch": exchange,
                            "rt_key": routing_key})

    return (processed_output, cmd_err)


def message_compute_plane(routing_key, message_token, **kwargs):
    """Send message to compute plane."""

    LOG.debug("Sending message to compute plane")

    return _send_message(constants.HS_COMPUTE_EXCH,
                         routing_key,
                         message_token,
                         **kwargs)


def message_data_plane(routing_key, message_token, **kwargs):
    """Send message to data node."""

    LOG.debug("Sending message to data plane")

    return _send_message(constants.HS_DATANODE_EXCH,
                         routing_key,
                         message_token,
                         **kwargs)


def message_controller(routing_key, message_token, **kwargs):
    """Send message to controller."""

    LOG.debug("Sending message to controller")

    return _send_message(constants.HS_CONTROLLER_EXCH,
                         routing_key,
                         message_token,
                         **kwargs)
