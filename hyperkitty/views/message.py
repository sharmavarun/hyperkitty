#-*- coding: utf-8 -*-
# Copyright (C) 1998-2012 by the Free Software Foundation, Inc.
#
# This file is part of HyperKitty.
#
# HyperKitty is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# HyperKitty is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along with
# HyperKitty.  If not, see <http://www.gnu.org/licenses/>.
#
# Author: Aamir Khan <syst3m.w0rm@gmail.com>
# Author: Aurelien Bompard <abompard@fedoraproject.org>
#

import urllib
import datetime

import django.utils.simplejson as json
from django.http import HttpResponse, Http404
from django.shortcuts import redirect, render
from django.conf import settings
from django.core.urlresolvers import reverse
from django.core.mail import EmailMessage
from django.core.exceptions import SuspiciousOperation
from django.contrib.auth.decorators import login_required

from hyperkitty.lib import get_store, get_months, get_votes
from hyperkitty.models import Rating
from forms import SearchForm, ReplyForm, PostForm


def index(request, mlist_fqdn, message_id_hash):
    '''
    Displays a single message identified by its message_id_hash (derived from
    message_id)
    '''
    search_form = SearchForm(auto_id=False)
    store = get_store(request)
    message = store.get_message_by_hash_from_list(mlist_fqdn, message_id_hash)
    if message is None:
        raise Http404
    message.sender_email = message.sender_email.strip()

    # Extract all the votes for this message
    message.likes, message.dislikes = get_votes(message_id_hash)
    message.likestatus = "neutral"
    if message.likes - message.dislikes >= 10:
        message.likestatus = "likealot"
    elif message.likes - message.dislikes > 0:
        message.likestatus = "like"
    #elif message.likes - message.dislikes < 0:
    #    message.likestatus = "dislike"

    mlist = store.get_list(mlist_fqdn)

    context = {
        'mlist' : mlist,
        'message': message,
        'message_id_hash' : message_id_hash,
        'months_list': get_months(store, mlist.name),
        'reply_form': ReplyForm(),
    }
    return render(request, "message.html", context)


def attachment(request, mlist_fqdn, message_id_hash, counter, filename):
    """
    Sends the numbered attachment for download. The filename is not used for
    lookup, but validated nonetheless for security reasons.
    """
    store = get_store(request)
    message = store.get_message_by_hash_from_list(mlist_fqdn, message_id_hash)
    if message is None:
        raise Http404
    attachment = store.get_attachment_by_counter(
            mlist_fqdn, message.message_id, int(counter))
    if attachment is None or attachment.name != filename:
        raise Http404
    # http://djangosnippets.org/snippets/1710/
    response = HttpResponse(attachment.content)
    response['Content-Type'] = attachment.content_type
    response['Content-Length'] = attachment.size
    if attachment.encoding is not None:
        response['Content-Encoding'] = attachment.encoding
    # Follow RFC2231, browser support is sufficient nowadays (2012-09)
    response['Content-Disposition'] = 'attachment; filename*=UTF-8\'\'%s' \
            % urllib.quote(attachment.name.encode('utf-8'))
    return response


def vote(request, mlist_fqdn, message_id_hash):
    """ Add a rating to a given message identified by messageid. """
    if not request.user.is_authenticated():
        return HttpResponse('You must be logged in to vote',
                            content_type="text/plain", status=403)

    value = int(request.POST['vote'])

    # Checks if the user has already voted for a this message.
    try:
        v = Rating.objects.get(user=request.user, messageid=message_id_hash,
                               list_address=mlist_fqdn)
        if v.vote == value:
            return HttpResponse("You've already cast this vote",
                                content_type="text/plain", status=403)
    except Rating.DoesNotExist:
        v = Rating(list_address=mlist_fqdn, messageid=message_id_hash, vote=value)
        v.user = request.user

    v.vote = value
    v.save()

    # Extract all the votes for this message to refresh it
    status = { "like": 0, "dislike": 0 }
    for vote in Rating.objects.filter(messageid=message_id_hash):
        if vote.vote == 1:
            status["like"] += 1
        elif vote.vote == -1:
            status["dislike"] += 1

    return HttpResponse(json.dumps(status),
                        mimetype='application/javascript')


@login_required
def reply(request, mlist_fqdn, message_id_hash):
    """ Sends a reply to the list.
    TODO: unit tests
    """
    if request.method != 'POST':
        raise SuspiciousOperation
    form = ReplyForm(request.POST)
    if not form.is_valid():
        return HttpResponse(form.errors.as_text(),
                            content_type="text/plain", status=400)
    store = get_store(request)
    mlist = store.get_list(mlist_fqdn)
    message = store.get_message_by_hash_from_list(mlist.name, message_id_hash)
    subject = message.subject
    if not message.subject.lower().startswith("re:"):
        subject = "Re: %s" % subject
    _send_email(request, mlist, subject, form.cleaned_data["message"], {
                    "In-Reply-To": "<%s>" % message.message_id,
                    "References": "<%s>" % message.message_id,
                })
    return HttpResponse("The reply has been sent successfully.",
                        mimetype="text/plain")


@login_required
def new_message(request, mlist_fqdn):
    """ Sends a new thread-starting message to the list.
    TODO: unit tests
    """
    store = get_store(request)
    mlist = store.get_list(mlist_fqdn)
    if request.method == 'POST':
        form = PostForm(request.POST)
        if form.is_valid():
            _send_email(request, mlist, form.cleaned_data['subject'],
                        form.cleaned_data["message"])
            today = datetime.date.today()
            redirect_url = reverse(
                    'archives_with_month', kwargs={
                        "mlist_fqdn": mlist_fqdn,
                        'year': today.year,
                        'month': today.month})
            redirect_url += "?msg=sent-ok"
            return redirect(redirect_url)
    else:
        form = PostForm()
    context = {
        "mlist": mlist,
        "post_form": form,
        'months_list': get_months(store, mlist.name),
    }
    return render(request, "message_new.html", context)


def _send_email(request, mlist, subject, message, headers={}):
    if not mlist:
        # Make sure the list exists to avoid posting to any email addess
        raise SuspiciousOperation("I don't know this mailing-list")
    headers["User-Agent"] = "HyperKitty on %s" % request.build_absolute_uri("/")
    msg = EmailMessage(
               subject=subject,
               body=message,
               from_email='"%s %s" <%s>' %
                   (request.user.first_name, request.user.last_name,
                    request.user.email),
               to=[mlist.name],
               headers=headers,
               )
    msg.send()
