# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 VMware, Inc.
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
Utility functions for Image transfer.
"""

from eventlet import timeout

from cinder import exception
from cinder.openstack.common import log as logging
from cinder.volume.drivers.vmware import io_util
from cinder.volume.drivers.vmware import read_write_util as rw_util

LOG = logging.getLogger(__name__)

QUEUE_BUFFER_SIZE = 10


def start_transfer(context, timeout_secs, read_file_handle, data_size,
                   write_file_handle=None, image_service=None, image_id=None,
                   image_meta=None):
    """Start the data transfer from the reader to the writer.

    Reader writes to the pipe and the writer reads from the pipe. This means
    that the total transfer time boils down to the slower of the read/write
    and not the addition of the two times.
    """

    if not image_meta:
        image_meta = {}

    # The pipe that acts as an intermediate store of data for reader to write
    # to and writer to grab from.
    thread_safe_pipe = io_util.ThreadSafePipe(QUEUE_BUFFER_SIZE, data_size)
    # The read thread. In case of glance it is the instance of the
    # GlanceFileRead class. The glance client read returns an iterator
    # and this class wraps that iterator to provide datachunks in calls
    # to read.
    read_thread = io_util.IOThread(read_file_handle, thread_safe_pipe)

    # In case of Glance - VMware transfer, we just need a handle to the
    # HTTP Connection that is to send transfer data to the VMware datastore.
    if write_file_handle:
        write_thread = io_util.IOThread(thread_safe_pipe, write_file_handle)
    # In case of VMware - Glance transfer, we relinquish VMware HTTP file read
    # handle to Glance Client instance, but to be sure of the transfer we need
    # to be sure of the status of the image on glance changing to active.
    # The GlanceWriteThread handles the same for us.
    elif image_service and image_id:
        write_thread = io_util.GlanceWriteThread(context, thread_safe_pipe,
                                                 image_service, image_id,
                                                 image_meta)
    # Start the read and write threads.
    read_event = read_thread.start()
    write_event = write_thread.start()
    timer = timeout.Timeout(timeout_secs)
    try:
        # Wait on the read and write events to signal their end
        read_event.wait()
        write_event.wait()
    except (timeout.Timeout, Exception) as exc:
        # In case of any of the reads or writes raising an exception,
        # stop the threads so that we un-necessarily don't keep the other one
        # waiting.
        read_thread.stop()
        write_thread.stop()

        # Log and raise the exception.
        LOG.exception(exc)
        raise exception.CinderException(exc)
    finally:
        timer.cancel()
        # No matter what, try closing the read and write handles, if it so
        # applies.
        read_file_handle.close()
        if write_file_handle:
            write_file_handle.close()


def fetch_image(context, timeout_secs, image_service, image_id, **kwargs):
    """Download image from the glance image server."""
    LOG.debug(_("Downloading image: %s from glance image server.") % image_id)
    metadata = image_service.show(context, image_id)
    file_size = int(metadata['size'])
    read_iter = image_service.download(context, image_id)
    read_handle = rw_util.GlanceFileRead(read_iter)
    write_handle = rw_util.VMwareHTTPWriteFile(kwargs.get('host'),
                                               kwargs.get('data_center_name'),
                                               kwargs.get('datastore_name'),
                                               kwargs.get('cookies'),
                                               kwargs.get('file_path'),
                                               file_size)
    start_transfer(context, timeout_secs, read_handle, file_size,
                   write_file_handle=write_handle)
    LOG.info(_("Downloaded image: %s from glance image server.") % image_id)


def upload_image(context, timeout_secs, image_service, image_id, owner_id,
                 **kwargs):
    """Upload the snapshot vm disk file to Glance image server."""
    LOG.debug(_("Uploading image: %s to the Glance image server.") % image_id)
    read_handle = rw_util.VMwareHTTPReadFile(kwargs.get('host'),
                                             kwargs.get('data_center_name'),
                                             kwargs.get('datastore_name'),
                                             kwargs.get('cookies'),
                                             kwargs.get('file_path'))
    file_size = read_handle.get_size()
    # The properties and other fields that we need to set for the image.
    image_metadata = {'disk_format': 'vmdk',
                      'is_public': 'false',
                      'name': kwargs.get('snapshot_name'),
                      'status': 'active',
                      'container_format': 'bare',
                      'size': file_size,
                      'properties': {'vmware_image_version':
                                     kwargs.get('image_version'),
                                     'owner_id': owner_id}}
    start_transfer(context, timeout_secs, read_handle, file_size,
                   image_service=image_service, image_id=image_id,
                   image_meta=image_metadata)
    LOG.info(_("Uploaded image: %s to the Glance image server.") % image_id)
