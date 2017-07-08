==================================
Failed to connect volume in FC SAN
==================================

Problem
~~~~~~~

The compute node failed to connect to a volume in a Fibre Channel (FC) SAN
configuration. The WWN may not be zoned correctly in your FC SAN that
links the compute host to the storage array:

.. code-block:: console

   ERROR nova.compute.manager [req-2ddd5297-e405-44ab-aed3-152cd2cfb8c2 admin\
   demo|req-2ddd5297-e405-44ab-aed3-152cd2cfb8c2 admin demo] [instance: 60ebd\
   6c7-c1e3-4bf0-8ef0-f07aa4c3d5f3|instance: 60ebd6c7-c1e3-4bf0-8ef0-f07aa4c3\
   d5f3]
   Failed to connect to volume 6f6a6a9c-dfcf-4c8d-b1a8-4445ff883200 while\
   attaching at /dev/vdjTRACE nova.compute.manager [instance: 60ebd6c7-c1e3-4\
   bf0-8ef0-f07aa4c3d5f3|instance: 60ebd6c7-c1e3-4bf0-8ef0-f07aa4c3d5f3]
   Traceback (most recent call last):…f07aa4c3d5f3\] ClientException: The\
   server has either erred or is incapable of performing the requested\
   operation.(HTTP 500)(Request-ID: req-71e5132b-21aa-46ee-b3cc-19b5b4ab2f00)

Solution
~~~~~~~~

The network administrator must configure the FC SAN fabric by correctly
zoning the WWN (port names) from your compute node HBAs.
