class BaseMapsProvider(object):
    def import_data(self):
        pass
        
    def real_time_information(self, entity):
        return None
    
    def augment_metadata(self, entities):
        pass

from naptan import NaptanMapsProvider
from acislive import ACISLiveMapsProvider
from osm import OSMMapsProvider
from postcodes import PostcodesMapsProvider
from ldb import LiveDepartureBoardPlacesProvider
from bbc_tpeg import BBCTPEGPlacesProvider