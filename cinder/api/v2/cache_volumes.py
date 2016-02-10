from oslo_log import log as logging
from oslo_config import cfg
import eventlet
from eventlet import greenthread
from oslo_concurrency import lockutils
from cinder import exception
from cinder.i18n import _, _LI
from cinder import volume as cinder_volume
from cinder.api.v2 import snapshots
from cinder import utils
service_credential_opts = [ 
 cfg.StrOpt('cinder_project_name',
             default="None",
             help="cinder project name for caching volumes in service tenant by cinder user"),
 cfg.StrOpt('cinder_project_id',default="None",help="cinder project id"),
 cfg.StrOpt('cinder_user_name',default="None",help="cinder user name"),
 cfg.StrOpt('cinder_user_id',default="None",help="cinder user id"),
]

timeout_opts = [
  cfg.IntOpt('cache_waiting_time',default=60,help="time thread should wait for a volume or snap creation"),
]

CONF = cfg.CONF
CONF.register_opts(service_credential_opts)
CONF.register_opts(timeout_opts)

LOG = logging.getLogger(__name__)
Timeout = eventlet.timeout.Timeout

class VolumeCache:

    def __init__(self):
        self.service_project_name=None
        self.service_project_id=None
        self.service_user_name=None
        self.service_user_id=None
        self.volume_api = cinder_volume.API()
        self.context=None
        self.cache_snap_name=None
        self.cache_vol_name=None
        self.req=None
        self.body=None


    def get_snap_cache(self):
        snap_found=False
        while not snap_found:
            snap=self.volume_api.get_snapshot_by_name(self.context,self.cache_snap_name)
            if 'status' in snap and snap['status']=="available":
                break

            elif 'status' in snap and snap['status']=="error":
                snap=None
                break
            elif 'status' not in snap:
                break
            greenthread.sleep(1)
        return snap

    def get_volume_cache(self):
        vol = self.volume_api.get_volume_by_name(self.context,self.cache_vol_name)
        return vol

    def create_cache_volume(self):
	self.req.environ['cinder.context']=self.context
	self.body['volume']['display_name']=self.cache_vol_name
	vol = self.volumeController.create(self.req,self.body)
        return vol

    def create_cache_snapshot(self):
        snap = None
        waiting_time=CONF.cache_waiting_time
        try:
            vol = self.get_volume_cache()
        except exception.NotFound:
            vol = self.create_cache_volume()
        if vol is not None:
            if 'id' in vol:
                vol_id=vol['id']
            else:
                vol_id=vol['volume']['id']
            with Timeout(waiting_time,exception=exception.TimeoutWaiting):
                try:
                    while True:
                        try:
                            vol=self.volume_api.get_volume(self.context,vol_id)
	                    if vol['status']=="available":
                                break
                        except exception.NotFound:
                            break
                except exception.CinderException:
                    LOG.debug("\ntimeout occured while waiting for volume")
                    vol=None

        if vol is not None:
           
            snap_body={'snapshot': 
                             {
                              'volume_id': vol_id, 
                              'force': False, 
                              'description': None, 
                              'name': self.cache_snap_name
                             }
                      }

            snap_controller=snapshots.SnapshotsController()
            self.req.environ['cinder.context']=self.context
            snap=snap_controller.create(self.req,snap_body)
            snap_id=snap['snapshot']['id']
            error_while_creating_snap=False
	    with Timeout(waiting_time, exception=exception.TimeoutWaiting):
                try:
                    while True:
                        try:
                            snap=self.volume_api.get_snapshot(self.context,snap_id)
                            if snap['status']=="available":
                                break
                            elif snap['status']=="error":
                                error_while_creating_snap=True
                                break
                        except exception.NotFound:
                            break
                except exception.CinderException:
                    LOG.debug("\ntimeout occured while waiting for snapshot" )
        if error_while_creating_snap:
            LOG.debug("\nError occured while creating cache snapshot")
            return None
        return snap


    def update_context(self,context):
	context_cache=context.deepcopy()
        context_cache.project_name=CONF.cinder_project_name
        context_cache.project_id=CONF.cinder_project_id
        context_cache.user_name=CONF.cinder_user_name
        context_cache.user_id=CONF.cinder_user_id
        self.context=context_cache
        LOG.debug("\n++ context is %s"%(context_cache))

    def update_cache_names(self,image_name):
        self.image_name = image_name
        self.cache_vol_name = image_name + "_cache_volume"
        self.cache_snap_name = image_name + "_snap_volume"

    def update_req_and_body(self,req,body):
        self.req=req
        self.body=body

    def revert_req_and_body(self,context,original_vol_name):
        self.req.environ['cinder.context']=context
	self.body['volume']['display_name'] = original_vol_name

    def get_cache_snapshot(self,req,body,volumeController):
        self.volumeController = volumeController
        volume=body['volume']

        context=req.environ['cinder.context']
        original_vol_name=volume['display_name']
        self.update_context(context)
        self.update_req_and_body(req,body)
        snap=None
        if 'imageRef' in volume and volume['imageRef'] is not None and  \
                  volume['imageRef']+"_cache_volume"!=volume['display_name'] :
	    image_name=volume['imageRef']
            self.update_cache_names(image_name)
            try:
                locked_action="%s-%s"%(self.cache_snap_name,"create")
                snap=self.get_snap_cache()
 
            except exception.NotFound:
                LOG.debug("\n going to create snapshot %s"%(self.cache_snap_name))
                @utils.synchronized(locked_action,external=True)
                def run_create_cache():
                    try:
                        snap=self.get_snap_cache()           
                    except exception.NotFound:
                        snap = self.create_cache_snapshot()
                    return snap

                snap = run_create_cache()

        self.revert_req_and_body(context,original_vol_name)
        LOG.debug("while returning body is %s"%(self.body))
        if snap == None:
            return None
        else:
            del volume['imageRef']
        return snap['id']
