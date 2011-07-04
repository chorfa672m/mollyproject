import random
import sys
from collections import namedtuple, defaultdict
from datetime import datetime, date, time, timedelta
from logging import getLogger
from operator import itemgetter
from StringIO import StringIO
from urllib2 import urlopen
from zipfile import ZipFile

from django.http import Http404
from django.db.models import Q

from molly.apps.places import get_entity
from molly.apps.places.models import (Entity, Route, StopOnRoute, Source,
                                      Journey, ScheduledStop)
from molly.apps.places.providers import BaseMapsProvider, NaptanMapsProvider
from molly.conf.settings import batch
from molly.utils.i18n import set_name_in_language

logger = getLogger(__name__)

weekbool = namedtuple('weekbool', 'mon tue wed thu fri sat sun')

class AtcoCifTimetableProvider(BaseMapsProvider):
    """
    This provider loads ATCO-CIF dumps and parses them to extract timetable
    data. This only handles a subset of the ATCO-CIF standard, in particular,
    it deals with the TfGM released data (the only released data atm)
    """
    
    def __init__(self, url):
        """
        URL to an ATCO-CIF zip to be used
        """
        self._url = url
    
    @batch('%d 10 * * wed' % random.randint(0, 59))
    def import_data(self, metadata, output):
        
        deleted_routes = set(Route.objects.filter(external_ref__startswith=self._url).values_list('external_ref'))
        archive = ZipFile(StringIO(urlopen(self._url).read()))
        for file in archive.namelist():
            routes = self._import_cif(archive.open(file))
            self._import_routes(routes)
            deleted_routes -= set(self._url + route['number'] + route['description'] for route in routes)
        archive.close()
        
        for route in deleted_routes:
            Route.objects.filter(external_ref=route).delete()
    
    def _parse_cif_date(self, datestring):
        return date(int(datestring[0:4]), int(datestring[4:6]),
                    int(datestring[6:8]))
    
    def _parse_cif_time(self, timestring):
        return time(int(timestring[0:2]) % 24, int(timestring[2:4]))
    
    def _import_cif(self, cif):
        """
        Parse a CIF file
        """
        
        routes = []
        
        this_journey = None
        
        for line in cif:
            
            if line[:2] == 'QS':
                # Journey header
                if this_journey is not None:
                    routes[-1]['journies'].append(this_journey)
                if line[2] == 'D':
                    this_journey = None
                    continue
                this_journey = {
                    'operator-code': line[3:7],
                    'id': line[7:13],
                    'start-date': self._parse_cif_date(line[13:21]),
                    'end-date': self._parse_cif_date(line[21:29]),
                    'days': weekbool(
                        line[29] == '1', # Monday
                        line[30] == '1', # Tuesday
                        line[31] == '1', # Wednesday
                        line[32] == '1', # Thursday
                        line[33] == '1', # Friday
                        line[34] == '1', # Saturday
                        line[35] == '1', # Sunday
                    ),
                    'school-holidays': {
                        'S': 'term-time',
                        'H': 'holidays'
                    }.get(line[36], 'all'),
                    'bank-holidays': {
                        'A': 'additional',
                        'B': 'holidays',
                        'X': 'non-holidays'
                    }.get(line[37], 'all'),
                    'route': line[38:42],
                    'vehicle': line[48:56].strip(),
                    'direction': line[64],
                    'notes': [],
                    'stops': [],
                }
            
            elif line[:2] in ('QN', 'ZN'):
                # Notes
                this_journey['notes'].append(line[7:])
            
            elif line[:2] == 'QO':
                # Journey start
                try:
                    this_journey['stops'].append({
                        'entity': get_entity('atco', line[2:14].strip()),
                        'sta': None,
                        'std': self._parse_cif_time(line[14:18]),
                        'activity': 'O',
                        'estimated': line[22] == '0',
                        'fare-stage': line[24] == '1'
                    })
                except Http404:
                    pass
            
            elif line[:2] == 'QI':
                # Journey intermediate stop
                try:
                    this_journey['stops'].append({
                        'entity': get_entity('atco', line[2:14].strip()),
                        'sta': self._parse_cif_time(line[14:18]),
                        'std': self._parse_cif_time(line[18:22]),
                        'activity': line[22],
                        'estimated': line[27] == '0',
                        'fare-stage': line[29] == '1'
                    })
                except Http404:
                    pass
            
            elif line[:2] == 'QT':
                # Journey complete
                try:
                    this_journey['stops'].append({
                        'entity': get_entity('atco', line[2:14].strip()),
                        'sta': self._parse_cif_time(line[14:18]),
                        'std': None,
                        'activity': 'F',
                        'estimated': line[22] == '0',
                        'fare-stage': line[24] == '1'
                    })
                except Http404:
                    pass
            
            elif line[:2] == 'ZS':
                # Route
                
                if this_journey is not None:
                    routes[-1]['journies'].append(this_journey)
                
                routes.append({
                    'number': line[10:14].strip(),
                    'description': line[14:],
                    'stops': [],
                    'journies': []
                })
            
            elif line[:2] == 'ZA':
                
                stop_code = line[3:15].strip()
                
                try:
                    entity = get_entity('atco', stop_code)
                    if entity.source == self._get_source():
                        # Raise Http404 if this is a bus stop we came up with,
                        # so any name changes, etc, get processed
                        raise Http404()
                except Http404:
                    # Out of zone bus stops with NaPTAN codes
                    try:
                        entity = Entity.objects.get(source=self._get_source(),
                                                    _identifiers__scheme='atco',
                                                    _identifiers__value=stop_code)
                    except Entity.DoesNotExist:
                        entity = Entity(source=self._get_source())
                    identifiers = { 'atco': stop_code }
                    entity_type = self._get_entity_type()
                    entity.primary_type = entity_type
                    entity.save(identifiers=identifiers)
                    set_name_in_language(entity, 'en', title=line[15:63].strip())
                    entity.all_types = (entity_type,)
                    entity.update_all_types_completion()
                    entity.save()
                routes[-1]['stops'].append(entity)
        
        if this_journey is not None:
            routes[-1]['journies'].append(this_journey)
        
        return routes
    
    def _import_routes(self, routes):
        for r in routes:
            external_ref = self._url + r['number'] + r['description']
            route, created = Route.objects.get_or_create(
                external_ref=external_ref,
                defaults={
                    'service_id': r['number'],
                    'service_name': r['description'],
                }
            )
            if not created:
                route.service_id = r['number']
                route.service_name = r['description']
                route.save()
            route.stops.clear()
            for i, stop in enumerate(r['stops']):
                StopOnRoute.objects.create(route=route, entity=stop, order=i)
            
            route.journey_set.all().delete()
            for journey in r['journies']:
                self._add_journey(route, journey)
    
    def _add_journey(self, route, journey):
        j = Journey.objects.create(
            route=route,
            external_ref=self._url + journey['id'],
            notes='\n'.join(journey['notes']),
            runs_on_monday=journey['days'].mon,
            runs_on_tuesday=journey['days'].tue,
            runs_on_wednesday=journey['days'].wed,
            runs_on_thursday=journey['days'].thu,
            runs_on_friday=journey['days'].fri,
            runs_on_saturday=journey['days'].sat,
            runs_on_sunday=journey['days'].sun,
            runs_in_termtime=journey['school-holidays'] in ('all', 'term-time'),
            runs_in_school_holidays=journey['school-holidays'] in ('all', 'holidays'),
            runs_on_bank_holidays=journey['bank-holidays'] in ('all', 'holidays', 'additional'),
            runs_on_non_bank_holidays=journey['bank-holidays'] in ('all', 'non-holidays'),
            runs_from=journey['start-date'],
            runs_until=journey['end-date'],
            vehicle=journey['vehicle'])
        
        for i, stop in enumerate(journey['stops']):
            ScheduledStop.objects.create(
                journey=j,
                entity=stop['entity'],
                order=i,
                sta=stop['sta'],
                std=stop['std'],
                times_estimated=stop['estimated'],
                fare_stage=stop['fare-stage'],
                activity=stop['activity']
            )
    
    def _get_source(self):
        source, created = Source.objects.get_or_create(module_name=__name__,
                                                       name='ATCO-CIF Importer')
        return source
    
    def _get_entity_type(self):
        return NaptanMapsProvider(None)._get_entity_types()['BCT']
    
    def augment_metadata(self, entities, **kwargs):
        
        # Some routes finish the day after they start on, but for the
        # "does this service run today" question, they consider the day
        # before, e.g., Metrolink saturday timetable finishes early
        # Sunday morning. We're going to assume a break of 4am - but
        # this might not be accurate!
        
        today = datetime.now()
        if today.time() < time(4):
            today -= timedelta(days=1)
        
        def midnight_4am(left, right):
            """
            Search comparison function where before 4 am is later than midnight
            """
            return cmp(left.hour if left.hour >= 4 else left.hour + 24,
                       right.hour if right.hour >= 4 else right.hour + 24)
        
        for entity in entities:
            
            # Skip stops we have no schedules for
            if entity.scheduledstop_set.all().count() == 0:
                continue
            
            services = defaultdict(list)
            for stop in entity.scheduledstop_set.filter(
                Q(sta__gte=today.time()) | Q(sta__lt=time(4))):
                
                if not stop.journey.runs_on(today.date()):
                    continue
                
                services[stop.journey.route].append((stop.journey, stop.std if stop.std else stop.sta))
            
            services = ((route, sorted(ss, key=itemgetter(1), cmp=midnight_4am))
                for route, ss in services.items())
            
            services = [{
                'service': route.service_id,
                'destination': route.service_name,
                'next': ss[0][1].strftime('%H:%M'),
                'following': map(lambda t: t[1].strftime('%H:%M'), ss[1:4]),
                'journey': ss[0][0]
            } for route, ss in sorted(services, key=lambda x: x[1][0][1])]
            
            entity.metadata['real_time_information'] = {
                'services': services,
                'pip_info': [],
            }
            entity.metadata['meta_refresh'] = 60
