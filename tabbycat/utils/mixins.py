import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.urlresolvers import reverse_lazy
from django.http import HttpResponseRedirect
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.generic.base import TemplateResponseMixin, TemplateView, View
from django.views.generic.detail import SingleObjectMixin

from adjallocation.models import DebateAdjudicator
from tournaments.mixins import TournamentMixin

logger = logging.getLogger(__name__)


class PostOnlyRedirectView(View):
    """Base class for views that only accept POST requests.

    Current implementation redirects to a specified page (by default the home
    page) if a client tries to use a GET request, and shows and logs an error
    message. We might change this in the future just to return HTTP status code
    405 (HTTP method not allowed).

    Views using this class probably want to override both `post()` and
    `get_redirect_url()`. It is assumed that the same redirect will be desired
    the same whether GET or POST is used; it's just that a GET request won't
    do database edits.

    Note: The `post()` implementation of subclasses should call `super().post()`
    rather than returning the redirect directly, in case we decide to make
    `post()` smarter in the future. If there ever arises a need to distinguish
    between the redirects in the GET and POST cases, new methods should be added
    to this base class for this purpose.
    """

    redirect_url = reverse_lazy('tabbycat-index')
    not_post_message = "Whoops! You're not meant to type that URL into your browser."

    def get_redirect_url(self):
        return self.redirect_url

    def get(self, request, *args, **kwargs):
        logger.error("Tried to access a POST-only view with a GET request")
        messages.error(self.request, self.not_post_message)
        return HttpResponseRedirect(self.get_redirect_url())

    def post(self, request, *args, **kwargs):
        return HttpResponseRedirect(self.get_redirect_url())


class SuperuserRequiredMixin(UserPassesTestMixin):
    """Class-based view mixin. Requires user to be a superuser."""

    def test_func(self):
        return self.request.user.is_superuser


class SuperuserOrTabroomAssistantTemplateResponseMixin(LoginRequiredMixin, TemplateResponseMixin):
    """Mixin for views that choose either a superuser view or an assistant view,
    depending on the privileges of the user who is logged in.

    Views using this mixin must define the `superuser_template_name` and
    `assistant_template_name` class attributes."""

    superuser_template_name = None
    assistant_template_name = None

    def get_template_names(self):
        if self.request.user.is_superuser:
            return [self.superuser_template_name]
        else:
            return [self.assistant_template_name]


class PublicCacheMixin:
    """Mixin for views that cache the page."""

    cache_timeout = settings.PUBLIC_PAGE_CACHE_TIMEOUT

    @method_decorator(cache_page(cache_timeout))
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)


class SingleObjectFromTournamentMixin(SingleObjectMixin, TournamentMixin):
    """Mixin for views that relate to a single object that is part of a
    tournament. Like SingleObjectMixin, but restricts searches to the relevant
    tournament."""

    def get_queryset(self):
        return super().get_queryset().filter(tournament=self.get_tournament())


class SingleObjectByRandomisedUrlMixin(SingleObjectFromTournamentMixin):
    """Mixin for views that use URLs referencing objects by a randomised key.
    This is just a `SingleObjectMixin` with some options set.

    Views using this mixin should have both a `url_key` group in their URL's
    regular expression, and a primary key group (by default `pk`, inherited from
    `SingleObjectMixin`, but this can be overridden). They should set the
    `model` field of the class as they would for `SingleObjectMixin`. This model
    should have a slug field called `url_key`.
    """
    slug_field = 'url_key'
    slug_url_kwarg = 'url_key'


class HeadlessTemplateView(TemplateView):
    """Mixin for views that sets context data for the page and html header
    directly into the base template, obviating the need for page templates in
    many instances"""

    def get_context_data(self, **kwargs):

        kwargs["page_title"] = self.page_title
        kwargs["page_emoji"] = self.page_emoji

        return super().get_context_data(**kwargs)


class VueTableMixin:
    """Mixing that provides shortcuts for adding data when building arrays that
    will end up as rows within a Vue table. Each cell can be represented
    either as a string value or a dictionary to enable richer inline content
    (emoji, links, etc). Functions below return blocks of content (ie not just
     a team name row, but also institution/category status as needed)."""

    sort_key = ''

    def get_context_data(self, **kwargs):
        kwargs["sortKey"] = self.sort_key
        return super().get_context_data(**kwargs)

    def format_cell_number(self, value):
        if isinstance(value, float):
            return "{0:.2f}".format(value)
        else:
            return value

    def get_adj_symbol(self, adj_type):
        if adj_type == DebateAdjudicator.TYPE_CHAIR:
            return "Ⓒ"
        elif adj_type == DebateAdjudicator.TYPE_PANEL:
            return ""
        else:
            return "Ⓣ"

    def adj_cells(self, adjudicator, tournament):

        adj_info = [{
            'head': {'key': 'Name'},
            'cell': {'text': adjudicator.name}
        }]
        if tournament.pref('show_institutions'):
            if adjudicator.adj_core:
                adj_info.append({
                    'head': {'key': 'Institution'},
                    'cell': {'text': "Adj Core / " + adjudicator.institution.name}
                })
            elif adjudicator.independent:
                adj_info.append({
                    'head': {'key': 'Institution'},
                    'cell': {'text': "Independent / " + adjudicator.institution.name}
                })
            else:
                adj_info.append({
                    'head': {'key': 'Institution'},
                    'cell': {'text': adjudicator.institution.name}
                })
        return adj_info

    def adjudicators_cells(self, debate, tournament, key='Adjudicators', show_splits=False):

        adjs_text = ''
        if debate.confirmed_ballot and show_splits:
            for type, adj, split in debate.confirmed_ballot.ballot_set.adjudicator_results:
                adjs_info = adj.name + " " + self.get_adj_symbol(type) + " , "
                if split:
                    adjs_text += "<span class='text-danger'>" + adjs_info + "</span>"
                else:
                    adjs_text += adjs_info
        else:
            for type, adj in debate.adjudicators:
                adjs_text += adj.name + " " + self.get_adj_symbol(type) + " , "

        adjs_info = [{
            'head': {'key': key},
            'cell': {'text': adjs_text[:-2]} # Remove trailing comma
        }]
        return adjs_info

    def motion_cells(self, motion, key='Motion'):
        motion_info = [{
            'head': {'key': key},
            'cell': {'text': motion.reference, 'tooltip': motion.text}
        }]
        return motion_info

    def team_cells(self, team, tournament, break_categories=None, show_speakers=False, hide_institution=False, key='Team'):
        team_info = [{
            'head': {'key': key},
            'cell': {
                'text':     team.short_name,
                'emoji':    team.emoji if tournament.pref('show_emoji') else None,
                'sort':     team.short_name,
                'tooltip':  [" " + s.name for s in team.speakers] if tournament.pref('show_speakers_in_draw') or show_speakers else None
            }
        }]

        if break_categories is not None:
            team_info.append({
                'head': {'key': 'Categories'},
                'cell': {'text': break_categories}
            })
        if tournament.pref('show_institutions') and not hide_institution:
            team_info.append({
                'head': {'key': 'Institution', 'icon': "glyphicon glyphicon-home"},
                'cell': {'text': team.institution.code}
            })
        return team_info

    def speaker_cells(self, speaker, tournament, key='Name'):
        speaker_info = [{
            'head': {'key': key},
            'cell': {'text': speaker.name}
        }]
        if tournament.pref('show_novices'):
            speaker_info.append({
                'head': {'key': 'Novice'},
                'cell': {'icon': "glyphicon-ok" if speaker.novice else "glyphicon-remove"}
            })

        return speaker_info

    def venue_cells(self, debate, tournament, with_times=False):
        venue_info = []
        if tournament.pref('enable_divisions'):
            venue_info.append({
                'head': {'key': 'Division'},
                'cell': {'text': debate.division.name}
            })

        if tournament.pref('enable_venue_groups') and debate.division:
            venue_info.append({
                'head': {'key': 'Venue', 'icon': "glyphicon glyphicon-map-marker"},
                'cell': {'text': debate.division.venue_group.short_name}
            })
        elif tournament.pref('enable_venue_groups'):
            venue_info.append({
                'head': {'key': 'Venue', 'icon': "glyphicon glyphicon-map-marker"},
                'cell': {'text': debate.venue.group.short_name + debate.venue.name}
            })
        else:
            venue_info.append({
                'head': {'key': 'Venue', 'icon': "glyphicon glyphicon-map-marker"},
                'cell': {'text': debate.venue.name}
            })

        if with_times and tournament.pref('enable_debate_scheduling'):
            if debate.aff_team.type == 'B' or debate.neg_team.type == 'B':
                venue_info.append({'head': {'key': ' '}, 'cell':  {'text': ""}})
                venue_info.append({'head': {'key': ' '}, 'cell':  {'text': "Bye"}})
            elif debate.result_status == "P":
                venue_info.append({'head': {'key': ' '}, 'cell':  {'text': ""}})
                venue_info.append({'head': {'key': ' '}, 'cell':  {'text': "Postponed"}})
            elif debate.confirmed_ballot.forfeit:
                venue_info.append({'head': {'key': ' '}, 'cell':  {'text': ""}})
                venue_info.append({'head': {'key': ' '}, 'cell':  {'text': "Forfeit"}})
            else:
                venue_info.append({'head': {'key': 'status'}, 'cell': {'text': debate.time.strftime("D jS F")}})
                venue_info.append({'head': {'key': 'status'}, 'cell': {'text': debate.time.strftime('h:i A')}})

        return venue_info

    def ranking_cells(self, standing):
        ddict = []
        for key, value in standing.rankings.items():
            if value[1]:
                ddict.append({'head': {'key': key}, 'cell': {'text': str(value[0]) + '='}})
            else:
                ddict.append({'head': {'key': key}, 'cell': {'text': str(value[0])}})
        if hasattr(standing, 'break_rank'):
            ddict.append({'head': {'key': 'Break'}, 'cell': {'text': standing.break_rank}})

        return ddict

    def metric_cells(self, metrics):
        ddict = []
        for key, value in metrics.items():
            # Bit of a hack; although probably best place to have an interface
            if key is 'speaks_avg':
                key = "AVG Speaks"
            elif key is 'speaks_stddev':
                key = "STD Dev Speaks"
            elif key is 'speaks_sum':
                key = "Total Speaks"

            ddict.append({'head': {'key': key}, 'cell': {'text': self.format_cell_number(value)}})

        return ddict
