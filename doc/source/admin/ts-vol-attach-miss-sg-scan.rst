========================================
Failed to Attach Volume, Missing sg_scan
========================================

Problem
~~~~~~~

Failed to attach volume to an instance, ``sg_scan`` file not found. This
error occurs when the sg3-utils package is not installed on the compute node.
The IDs in your message are unique to your system:

.. code-block:: console

   ERROR nova.compute.manager [req-cf2679fd-dd9e-4909-807f-48fe9bda3642 admin admin|req-cf2679fd-dd9e-4909-807f-48fe9bda3642 admin admin]
   [instance: 7d7c92e0-49fa-4a8e-87c7-73f22a9585d5|instance:  7d7c92e0-49fa-4a8e-87c7-73f22a9585d5]
   Failed to attach volume  4cc104c4-ac92-4bd6-9b95-c6686746414a at /dev/vdcTRACE nova.compute.manager
   [instance:  7d7c92e0-49fa-4a8e-87c7-73f22a9585d5|instance: 7d7c92e0-49fa-4a8e-87c7-73f22a9585d5]
   Stdout: '/usr/local/bin/nova-rootwrap: Executable not found: /usr/bin/sg_scan'


Solution
~~~~~~~~

Run this command on the compute node to install the ``sg3-utils`` package:

.. code-block:: console

   # apt-get install sg3-utils
