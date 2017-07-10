=======================================
Failed to attach volume after detaching
=======================================

Problem
~~~~~~~

Failed to attach a volume after detaching the same volume.

Solution
~~~~~~~~

You must change the device name on the :command:`nova-attach` command. The VM
might not clean up after a :command:`nova-detach` command runs. This example
shows how the :command:`nova-attach` command fails when you use the ``vdb``,
``vdc``, or ``vdd`` device names:

.. code-block:: console

   # ls -al /dev/disk/by-path/
   total 0
   drwxr-xr-x 2 root root 200 2012-08-29 17:33 .
   drwxr-xr-x 5 root root 100 2012-08-29 17:33 ..
   lrwxrwxrwx 1 root root 9 2012-08-29 17:33 pci-0000:00:04.0-virtio-pci-virtio0 -> ../../vda
   lrwxrwxrwx 1 root root 10 2012-08-29 17:33 pci-0000:00:04.0-virtio-pci-virtio0-part1 -> ../../vda1
   lrwxrwxrwx 1 root root 10 2012-08-29 17:33 pci-0000:00:04.0-virtio-pci-virtio0-part2 -> ../../vda2
   lrwxrwxrwx 1 root root 10 2012-08-29 17:33 pci-0000:00:04.0-virtio-pci-virtio0-part5 -> ../../vda5
   lrwxrwxrwx 1 root root 9 2012-08-29 17:33 pci-0000:00:06.0-virtio-pci-virtio2 -> ../../vdb
   lrwxrwxrwx 1 root root 9 2012-08-29 17:33 pci-0000:00:08.0-virtio-pci-virtio3 -> ../../vdc
   lrwxrwxrwx 1 root root 9 2012-08-29 17:33 pci-0000:00:09.0-virtio-pci-virtio4 -> ../../vdd
   lrwxrwxrwx 1 root root 10 2012-08-29 17:33 pci-0000:00:09.0-virtio-pci-virtio4-part1 -> ../../vdd1

You might also have this problem after attaching and detaching the same
volume from the same VM with the same mount point multiple times. In
this case, restart the KVM host.
