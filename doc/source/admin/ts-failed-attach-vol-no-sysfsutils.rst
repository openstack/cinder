=================================================
Failed to attach volume, systool is not installed
=================================================

Problem
~~~~~~~

This warning and error occurs if you do not have the required
``sysfsutils`` package installed on the compute node:

.. code-block:: console

   WARNING nova.virt.libvirt.utils [req-1200f887-c82b-4e7c-a891-fac2e3735dbb\
   admin admin|req-1200f887-c82b-4e7c-a891-fac2e3735dbb admin admin] systool\
   is not installed
   ERROR nova.compute.manager [req-1200f887-c82b-4e7c-a891-fac2e3735dbb admin\
   admin|req-1200f887-c82b-4e7c-a891-fac2e3735dbb admin admin]
   [instance: df834b5a-8c3f-477a-be9b-47c97626555c|instance: df834b5a-8c3f-47\
   7a-be9b-47c97626555c]
   Failed to attach volume 13d5c633-903a-4764-a5a0-3336945b1db1 at /dev/vdk.

Solution
~~~~~~~~

Run the following command on the compute node to install the
``sysfsutils`` packages:

.. code-block:: console

   # apt-get install sysfsutils
