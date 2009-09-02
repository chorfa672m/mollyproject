from django.core.paginator import Paginator, EmptyPage, InvalidPage
from django.http import HttpResponse, HttpResponseRedirect

from mobile_portal.core.ldap_queries import get_person_units
from mobile_portal.core.renderers import mobile_render

from models import RSSFeed, RSSItem

def get_user_data(request):
    if False and request.user.is_authenticated():
        units = get_person_units(request.user.get_profile().webauth_username)

    else:
        units = []
        
    return {
        'authenticated': request.user.is_authenticated(),
        'units': units
    }
    
def get_feed_displayed(request, feed, user_data):
    if feed.slug in request.preferences['rss']['extra_feeds']:
        return True
    if feed.slug in request.preferences['rss']['hidden_feeds']:
        return False
    if not feed.show_predicate or eval(feed.show_predicate.predicate, user_data):
        return True

def index(request):
    user_data = get_user_data(request)
    
    feeds = (feed for feed in RSSFeed.objects.all() if get_feed_displayed(request, feed, user_data))
    
    items = RSSItem.objects.filter(feed__in = feeds).order_by('-last_modified')
    items = [item for item in items if not (item.feed.slug, item.guid) in request.preferences['rss']['hidden_items']]
    
    feed_count = {}
    for i, item in enumerate(items):
        feed_count[item.feed.slug] = feed_count.get(item.feed.slug, 0) + 1
        item.page_without_feed = (1 + i - feed_count[item.feed.slug]) // 10 + 1
    
    paginator = Paginator(items, 10)
    try:
        page_index = int(request.GET['page'])
    except:
        page_index = 1
    try:
        page = paginator.page(page_index)
    except (EmptyPage, InvalidPage):
        page = paginator.page(paginator.num_pages)

    context = {
        'page': page,
    }    
    
    return mobile_render(request, context, 'rss/index')

def set_feed_displayed(request, feed, displayed):
    extra_feeds = request.preferences['rss']['extra_feeds']
    hidden_feeds = request.preferences['rss']['hidden_feeds']
    
    if displayed:
        hidden_feeds.discard(feed.slug)
        extra_feeds.add(feed.slug)
    else:
        hidden_feeds.add(feed.slug)
        extra_feeds.discard(feed.slug)

def manage(request):
    user_data = get_user_data(request)
    
    feeds = RSSFeed.objects.all()
    
    feed_displayed = {}
    for feed in feeds:
        feed.displayed = get_feed_displayed(request, feed, user_data)
        feed_displayed[feed.slug] = feed.displayed
        
    if request.method == 'POST':
        #raise Exception(request.POST)
        for feed in feeds:
            new_displayed = ('display_%s' % feed.slug) in request.POST
            if new_displayed != feed_displayed[feed.slug]:
                set_feed_displayed(request, feed, new_displayed)
        return HttpResponseRedirect('.')
    
    context = {
        'feeds': feeds,
    }
    
    return mobile_render(request, context, 'rss/manage')    
    
def feed_display(request):
    """
    """
    if request.method != 'POST':
        return HttpResponse(feed_display.__doc__.replace('\n    ', '\n')[1:], status=405, mimetype="text/plain")
        
    errors = []
    
    try:
        feed = RSSFeed.objects.get(slug=request.POST['feed'])
    except KeyError:
        errors.append("You must supply a 'feed' parameter")
    except RSSFeed.DoesNotExist:
        errors.append("The feed with identifier '%s' does not exist." % request.POST['feed'])

    displayed = request.POST.get('displayed')
    if not displayed in ('true', 'false',):
        errors.append("You must provide a 'displayed' parameter of either 'true' or 'false' (not '%s')" % displayed)
    
    if errors:
        return HttpResponse("""\
Your request failed as a result of the following:

  * %s
  
Perform a GET of this resource for more guidance.
""" % "\n  * ".join(errors), status=400, mimetype="text/plain")

    set_feed_displayed(request, feed, displayed == 'true')
   
    if 'location' in request.POST:
        return HttpResponseRedirect(request.POST['location'])
    else:
        return HttpResponse('', mimetype="text/plain")