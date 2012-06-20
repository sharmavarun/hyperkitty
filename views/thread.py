import logging
import django.utils.simplejson as simplejson

from django import forms
from django.http import HttpResponse, HttpResponseRedirect
from django.template import RequestContext, loader
from django.conf import settings
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger, InvalidPage
from django.contrib.auth.decorators import (login_required,
                                            permission_required,
                                            user_passes_test)
from gsoc.models import Rating

logger = logging.getLogger(__name__)


@login_required
def add_tag(request, mlist_fqdn, email_id):
    """ Add a tag to a given message. """
    t = loader.get_template('simple_form.html')
    if request.method == 'POST':
        form = AddTagForm(request.POST)
        if form.is_valid():
            print "THERE WE ARE"
            # TODO: Add the logic to add the tag
            if form.data['from_url']:
                return HttpResponseRedirect(form.data['from_url'])
            else:
                return HttpResponseRedirect('/')
    else:
        form = AddTagForm()
    c = RequestContext(request, {
        'app_name': settings.APP_NAME,
        'list_address': mlist_fqdn,
        'email_id': email_id,
        'addtag_form': form,
        })
    return HttpResponse(t.render(c))

