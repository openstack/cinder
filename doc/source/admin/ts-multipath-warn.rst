==========================
Multipath call failed exit
==========================

Problem
~~~~~~~

Multipath call failed exit. This warning occurs in the Compute log
if you do not have the optional ``multipath-tools`` package installed
on the compute node. This is an optional package and the volume
attachment does work without the multipath tools installed.
If the ``multipath-tools`` package is installed on the compute node,
it is used to perform the volume attachment.
The IDs in your message are unique to your system.

.. code-block:: console

   WARNING nova.storage.linuxscsi [req-cac861e3-8b29-4143-8f1b-705d0084e571
       admin admin|req-cac861e3-8b29-4143-8f1b-705d0084e571 admin admin]
       Multipath call failed exit (96)

Solution
~~~~~~~~

Run the following command on the compute node to install the
``multipath-tools`` packages.

.. code-block:: console

   # apt-get install multipath-tools
