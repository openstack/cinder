.. _glusterfs_removal:

===============================================
Gracefully remove a GlusterFS volume from usage
===============================================

Configuring the ``cinder`` volume service to use GlusterFS involves creating a
shares file (for example, ``/etc/cinder/glusterfs``). This shares file
lists each GlusterFS volume (with its corresponding storage server) that
the ``cinder`` volume service can use for back end storage.

To remove a GlusterFS volume from usage as a back end, delete the volume's
corresponding entry from the shares file. After doing so, restart the Block
Storage services.

Restarting the Block Storage services will prevent the ``cinder`` volume
service from exporting the deleted GlusterFS volume. This will prevent any
instances from mounting the volume from that point onwards.

However, the removed GlusterFS volume might still be mounted on an instance
at this point. Typically, this is the case when the volume was already
mounted while its entry was deleted from the shares file.
Whenever this occurs, you will have to unmount the volume as normal after
the Block Storage services are restarted.
