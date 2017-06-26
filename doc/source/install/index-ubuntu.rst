=======================================
Cinder Installation Tutorial for Ubuntu
=======================================

This section describes how to install and configure storage nodes
for the Block Storage service. For simplicity, this configuration
references one storage node with an empty local block storage device.
The instructions use ``/dev/sdb``, but you can substitute a different
value for your particular node.

The service provisions logical volumes on this device using the
:term:`LVM <Logical Volume Manager (LVM)>` driver and provides them
to instances via :term:`iSCSI <iSCSI Qualified Name (IQN)>` transport.
You can follow these instructions with minor modifications to horizontally
scale your environment with additional storage nodes.

.. toctree::
   :maxdepth: 2

   cinder-storage-install-ubuntu.rst
   cinder-controller-install-ubuntu.rst
   cinder-backup-install-ubuntu.rst
   cinder-verify.rst
