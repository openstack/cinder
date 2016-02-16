'''
Created on Jan 29, 2016

@author: souvik
'''
from metrics.ThreadLocalMetrics import ThreadLocalMetrics, ThreadLocalMetricsFactory
from oslo_log import log as logging
LOG = logging.getLogger(__name__)

class MetricUtil(object):
    '''
    Metric Utility class to put and fetch request scoped metrics in cinder api
    '''
    METRICS_OBJECT = "metrics_object"
    def __init__(self):
        '''
        Constructor for Metric Utils. 
        '''
        
    def initialize_thread_local_metrics(self, request):
        
        try:
            metrics = self.fetch_thread_local_metrics()
        except AttributeError:
            service_log_path = self.__get_service_log_path()
            marketplace_id = self.__get_marketplace_id()
            prognam_name = self.__get_prognam_name()
            # TODO: Thread local metrics should be application context object or a singleton
            metrics = ThreadLocalMetricsFactory(service_log_path).with_marketplace_id(marketplace_id)\
                            .with_program_name(prognam_name).create_metrics()
            self.__add_details_from_request(request, metrics)
        return metrics
    
    def __add_details_from_request(self, request, metrics):
        context = request.environ.get('cinder.context')
        metrics.add_property("TenantId", context.project_id)
        metrics.add_property("RemoteAddress", context.remote_address)
        metrics.add_property("RequestId", context.request_id)
        metrics.add_property("PathInfo", request.environ.get('PATH_INFO'))
        # Project id is not provided to protect the identity of the user
        # Domain is not provided is it is not used
        #metrics.add_property("UserId", context.user_id)
             
    def fetch_thread_local_metrics(self):
        return ThreadLocalMetrics.get()
        
    def __get_service_log_path(self):
        # TODO: Get this from config where the rest of the logging is defined
        return "/var/log/cinder/service_log"
    
    def __get_marketplace_id(self):
        # TODO:Get this from from config/keystone
        return "IDC1"
    
    def __get_prognam_name(self):
        # TODO: Get this from Config
        return "CinderAPI"
    
    def closeMetrics(self, request):
        metrics = self.fetch_thread_local_metrics()
        metrics.close()

