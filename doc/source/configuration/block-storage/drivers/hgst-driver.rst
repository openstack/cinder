===================
HGST Storage driver
===================

The HGST driver enables Cinder volumes using the HGST Flash Storage Suite.

Set the following in your ``cinder.conf`` file, and use the following
options to configure it.

.. code-block:: ini

   volume_driver = cinder.volume.drivers.hgst.HGSTDriver

.. config-table::
   :config-target: HGST Storage

   cinder.volume.drivers.hgst
