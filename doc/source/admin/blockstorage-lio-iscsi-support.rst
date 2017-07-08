=====================
Use LIO iSCSI support
=====================

The default mode for the ``iscsi_helper`` tool is ``tgtadm``.
To use LIO iSCSI, install the ``python-rtslib`` package, and set
``iscsi_helper=lioadm`` in the ``cinder.conf`` file.

Once configured, you can use the :command:`cinder-rtstool` command to
manage the volumes. This command enables you to create, delete, and
verify volumes and determine targets and add iSCSI initiators to the
system.
