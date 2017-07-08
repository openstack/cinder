=====================================
HTTP bad request in cinder volume log
=====================================

Problem
~~~~~~~

These errors appear in the ``cinder-volume.log`` file:

.. code-block:: console

    2013-05-03 15:16:33 INFO [cinder.volume.manager] Updating volume status
    2013-05-03 15:16:33 DEBUG [hp3parclient.http]
    REQ: curl -i https://10.10.22.241:8080/api/v1/cpgs -X GET -H "X-Hp3Par-Wsapi-Sessionkey: 48dc-b69ed2e5
    f259c58e26df9a4c85df110c-8d1e8451" -H "Accept: application/json" -H "User-Agent: python-3parclient"

    2013-05-03 15:16:33 DEBUG [hp3parclient.http] RESP:{'content-length': 311, 'content-type': 'text/plain',
    'status': '400'}

    2013-05-03 15:16:33 DEBUG [hp3parclient.http] RESP BODY:Second simultaneous read on fileno 13 detected.
    Unless you really know what you're doing, make sure that only one greenthread can read any particular socket.
    Consider using a pools.Pool. If you do know what you're doing and want to disable this error,
    call eventlet.debug.hub_multiple_reader_prevention(False)

    2013-05-03 15:16:33 ERROR [cinder.manager] Error during VolumeManager._report_driver_status: Bad request (HTTP 400)
    Traceback (most recent call last):
    File "/usr/lib/python2.7/dist-packages/cinder/manager.py", line 167, in periodic_tasks task(self, context)
    File "/usr/lib/python2.7/dist-packages/cinder/volume/manager.py", line 690, in _report_driver_status volume_stats =
    self.driver.get_volume_stats(refresh=True)
    File "/usr/lib/python2.7/dist-packages/cinder/volume/drivers/san/hp/hp_3par_fc.py", line 77, in get_volume_stats stats =
    self.common.get_volume_stats(refresh, self.client)
    File "/usr/lib/python2.7/dist-packages/cinder/volume/drivers/san/hp/hp_3par_common.py", line 421, in get_volume_stats cpg =
    client.getCPG(self.config.hp3par_cpg)
    File "/usr/lib/python2.7/dist-packages/hp3parclient/client.py", line 231, in getCPG cpgs = self.getCPGs()
    File "/usr/lib/python2.7/dist-packages/hp3parclient/client.py", line 217, in getCPGs response, body = self.http.get('/cpgs')
    File "/usr/lib/python2.7/dist-packages/hp3parclient/http.py", line 255, in get return self._cs_request(url, 'GET', **kwargs)
    File "/usr/lib/python2.7/dist-packages/hp3parclient/http.py", line 224, in _cs_request **kwargs)
    File "/usr/lib/python2.7/dist-packages/hp3parclient/http.py", line 198, in _time_request resp, body = self.request(url, method, **kwargs)
    File "/usr/lib/python2.7/dist-packages/hp3parclient/http.py", line 192, in request raise exceptions.from_response(resp, body)
    HTTPBadRequest: Bad request (HTTP 400)

Solution
~~~~~~~~

You need to update your copy of the ``hp_3par_fc.py`` driver which
contains the synchronization code.
