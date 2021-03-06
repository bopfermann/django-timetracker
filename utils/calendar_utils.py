# pylint: disable=E1101,W0142,W0141,F0401,E0611
"""
Module for collecting the utility functions dealing with mostly calendar
tasks, processing dates and creating time-based code.

Module Functions
++++++++++++++++


=========================  ========================
..                         ..
=========================  ========================
:func:`get_request_data`   :func:`calendar_wrapper`
:func:`validate_time`      :func:`gen_holiday_list`
:func:`parse_time`         :func:`ajax_add_entry`
:func:`ajax_delete_entry`  :func:`ajax_error`
:func:`ajax_change_entry`  :func:`get_user_data`
:func:`delete_user`        :func:`useredit`
:func:`mass_holidays`      :func:`profile_edit`
:func:`gen_datetime_cal`
=========================  ========================
"""

import random
import datetime
import calendar as cdr
from functools import wraps

from django.core.handlers.wsgi import WSGIRequest
from django.core.mail import send_mail
from django.template.loader import get_template
from django.conf import settings
from django.template import Context
from django.http import Http404, HttpResponse
from django.db import IntegrityError
from django.forms import ValidationError
from django.core.cache import cache

try:
    from django.settings import SUSPICIOUS_DATE_DIFF
except ImportError:
    SUSPICIOUS_DATE_DIFF = 60 # days

import simplejson

from timetracker.loggers import (debug_log, database_log,
                                 error_log, suspicious_log)
from timetracker.tracker.models import TrackingEntry, Tbluser
from timetracker.tracker.models import Tblauthorization as Tblauth
from timetracker.utils.error_codes import DUPLICATE_ENTRY
from timetracker.utils.datemaps import (MONTH_MAP, WEEK_MAP_SHORT,
                                        PROCESS_CHOICES,
                                        generate_select,
                                        generate_year_box, pad,
                                        round_down)
from timetracker.utils.decorators import (admin_check, json_response,
                                          request_check)
from timetracker.utils.error_codes import CONNECTION_REFUSED
from timetracker.utils.crypto import get_random_string


def get_request_data(form, request):

    """
    Given a form and a request object we pull out
    from the request what the form defines.

    i.e.::

       form = {
            'data1': None
       }

    get_request_data(form, request) will then fill that data with what's in
    the request object.

    :param form: A dictionary of items which should be filled from
    :param request: The request object where the data should be taken from.
    :returns: A dictionary which contains the actual data from the request.
    :rtype: :class:`dict`
    :raises: KeyError
    """

    data = dict()

    # get our form data
    for key in form:
        data[key] = request.POST.get(key, None)

    # get the user id from the session
    data['user_id'] = request.session['user_id']

    return data


def validate_time(start, end):

    """
    Validates that the start time is before the end time

    :param start: String time such as "09:45"
    :param end: String time such as "17:00"
    :rtype: :class:`boolean`
    """

    shour, sminute = parse_time(start)
    ehour, eminute = parse_time(end)

    return (datetime.time(shour, sminute)
            < datetime.time(ehour, eminute))


def parse_time(timestring, type_of=int):

    """
    Given a time string will return a tuple of ints,
    i.e. "09:44" returns [9, 44] with the default args,
    you can pass any function to the type argument.

    :param timestring: String such as '09:44'
    :param type_of: A type which the split string should be converted to,
                    suitable types are: :class:`int`, :class:`str` and
                    :class:`float`.
    """

    return map(type_of, timestring.split(":"))


def calendar_wrapper(function):
    """
    Decorator which checks if the calendar function was
    called as an ajax request or not, if so, then the
    the wrapper constructs the arguments for the call
    from the POST items

    :param function: Literally just gen_calendar.
    :rtype: Nothing directly because it returns gen_calendar's
    """

    @wraps(function)
    def inner(*args, **kwargs):
        """
        Checks argument length and constructs the call
        based on that.
        """

        if isinstance(args[0], WSGIRequest): # pragma: no cover
            request = args[0]
            try:
                eeid = request.POST.get('eeid', None)
                json_dict = {
                    'success': True,
                    'calendar': function(user=eeid)
                }
                return HttpResponse(simplejson.dumps(json_dict))

            except Exception as error:
                error_log.error(str(error))
                return HttpResponse(str(error))

        else:
            # if the function was called from a view
            # let it just do it's thing
            return function(*args, **kwargs)

    return inner


def gen_holiday_list(admin_user, year=None, month=None, process=None):
    """
    Outputs a holiday calendar for that month.

    For each user we get their tracking entries, then iterate over each of
    their entries checking if it is a holiday or not, if it is then we change
    the class entry for that number in the day class' dict. Adds a submit
    button along with passing the user_id to it.

    We also create a javascript datastructure string to store the holiday
    daytypes. We do this to minimize interactions with the DOM when querying
    which cells have which daytype.

    :param admin_user: :class:`timetracker.tracker.models.Tbluser` instance.
    :param year: :class:`int` of the year required to be output, defaults to
                 the current year.
    :param month: :class:`int` of the month required to be output, defaults to
                 the current month.
    :returns: A partially pretty printed html string.
    :returns: A list of comment strings
    :rtype: :class:`str` & :class:`List`
    """

    if year is None: # pragma: no cover
        year = datetime.datetime.today().year
    if month is None: # pragma: no cover
        month = datetime.datetime.today().month

    # we convert the arguments to ints because
    # we get given unicode objects
    year, month = int(year), int(month)

    str_output = []
    to_out = str_output.append
    to_out('<table year=%s month=%s process=%s id="holiday-table">' % (
            year, month, process)
           )
    to_out("""<tr>
                 <th align="centre" colspan="100">{0}</th>
              </tr>""".format(MONTH_MAP[month - 1][1]))

    # generate the calendar,
    datetime_cal = gen_datetime_cal(year, month)

    # get just the days for the td text
    calendar_array = [day.day for day in datetime_cal]

    # generate the top row, with day names
    day_names = [WEEK_MAP_SHORT[day.weekday()] for day in datetime_cal]
    to_out(
        """<tr id="theader">""" \
            """<td>Name</td>""" \
            """<td>Balance</td>""" \
            """<td>DOD</td>""" \
            """<td>Code</td>"""
        )
    [to_out("<td>%s</td>\n" % day) for day in day_names]
    to_out("</tr>")

    user_list = admin_user.get_subordinates().filter(process=process) \
        if process else admin_user.get_subordinates()

    isweekend = lambda num: {
        1: 'empty',
        2: 'empty',
        3: 'empty',
        4: 'empty',
        5: 'empty',
        6: 'WKEND',
        7: 'WKEND',
    }[datetime.date(year=year,month=month,day=num).isoweekday()]

    comments_list = []
    js_calendar = ["{\n"]
    to_js = js_calendar.append
    for idx, user in enumerate(user_list):
        day_classes = dict( [
            (num, isweekend(num)) for num in calendar_array
        ] )

        # We have a dict with each day as currently
        # empty, we iterate through the tracking
        # entries and apply the daytype from that.
        for entry in user.tracking_entries(year, month): # pragma: no cover
            day_classes[entry.entry_date.day] = entry.daytype
            if entry.comments:
                comment_string = map(
                    unicode,
                    [entry.entry_date, entry.user.name(), entry.comments]
                    )
                comments_list.append(' '.join(comment_string))

        # if we have a cached row for this user and this year, use that.
        cached_result = cache.get(
            "holidaytablerow%s%s" % (user.id,
                                     year)
        )

        if cached_result:
            to_out(cached_result)
        else:
            # output the table row title, which contains:-
            # Full name, Holiday Balance and the User's
            # job code.
            row = """
            <tr id="%d_row">
            <th onclick="highlight_row(%d)" class="user-td">%s</th>
            <td>%s</td>
            <td>%s</td>
            <td class="job_code">%s</td>""" % (
                user.id, user.id,
                user.name(),
                user.get_holiday_balance(year),
                user.get_dod_balance(year),
                user.get_job_code_display() if admin_user.can_view_jobcodes() else ""
            )
            to_out(row)
            cache.set("holidaytablerow%s%s" % (user.id, year), row)

        # We've mapped the users' days to the day number,
        # we can write the user_id as an attribute to the
        # table data and also the dayclass for styling,
        # also, the current day number so that the table
        # shows what number we're on.
        to_js('"%s":["empty",' % user.id)
        entries = sorted(day_classes.items())
        cached_text = cache.get(
            "holidayfields:%s%s%s" % (user.id, year, month)
        )
        if cached_text:
            to_js(cached_text[0])
            to_out(cached_text[1])
        else:
            text_js = ''
            text_out = ''
            for iidx, (klass, day) in enumerate(entries):
                text_js += '"%s"%s' % (
                    day if day != "WKEND" else "empty",
                    "," if iidx+1 != len(entries) else "]"
                )
                text_out += ('<td usrid=%s class=%s>%s\n' % (user.id, day, klass))
            to_js(text_js)
            to_out(text_out)
            cache.set(
                "holidayfields:%s%s%s" % (user.id, year, month),
                (text_js, text_out),
            )
        # user_id is added as attr to make mass calls
        if admin_user.user_type != "RUSER":
            to_out("""<td>
                    <input value="submit" type="button" user_id="{0}"
                           onclick="submit_holidays({0})" />
                  </td>""".format(user.id))
            to_out('</tr>')
        to_js(",\n" if idx+1 != len(user_list) else "")
    to_js("\n}")

    # generate the data for the month select box
    month_select_data = [(month_num + 1, month[1])
                         for month_num, month in MONTH_MAP.items()]

    # generate the select box for the years
    year_select = generate_year_box(year, id="year_select")
    # generate the select box for the months
    month_select = generate_select(month_select_data, id="month_select")
    # generate the select box for the process type
    process_select = "<td>%s</td>" \
        % generate_select( (("ALL","All"),) + PROCESS_CHOICES,
                           id="process_select") \
                           if admin_user.user_type != "RUSER" else ""
    # generate submit all button
    submit_all = '''<td>
                      <input id="submit_all" value="Submit All" type="button"
                       onclick="submit_all()" />
                    </td>''' if admin_user.user_type != "RUSER" else ""
    to_out("""
    <tr>
      <td colspan="100">
        <table>
          <tr>
            <td align="right">
              <input id="btn_change_td" value="Reload" type="button"
               onclick="change_table_data()" />
            </td>
            <td>{0}</td>
            <td>{1}</td>
            {2}
            {3}
          </tr>
        </table>
      </td>
     </tr>""".format(year_select,
                     month_select,
                     process_select,
                     submit_all))
    return ''.join(str_output), comments_list, ''.join(js_calendar)


@calendar_wrapper
def gen_calendar(year=None, month=None, day=None, user=None):
    """
    Returns a HTML calendar, calling a database user to get their day-by-day
    entries and gives each day a special CSS class so that days can be styled
    individually.

    How this works is that, we iterate through each of the entries found in the
    TrackingEntry QuerySet for {year}/{month}. Create the table>td for that entry
    then attach the CSS class to that td. This means that each different type of

    day can be individually styled per the front-end style that is required.
    The choice to use a custom calendar table is precisely *because of* this fact
    the jQueryUI calendar doesn't support the individual styling of days, nor does
    it support event handling with the level of detail which we require.

    Each day td has one of two functions assigned to it depending on whether the
    day was an 'empty' day or a non-empty day. The two functions are called:

        .. code-block:: javascript

           function toggleChangeEntries(st_hour, st_min, full_st,
                                        fi_hour, fi_min, full_fi,
                                        entry_date, daytype,
                                        change_id, breakLength,
                                        breakLength_full)
            // and

            function hideEntries(date)


    These two functions could be slightly more generically named, as the calendar
    markup is used in two different places, in the {templates}/calendar.html and
    the {templates}/admin_view.html therefore I will move to naming these based
    on their event names, i.e. 'calendarClickEventDay()' and
    'calendarClickEventEmpty'.

    The toggleChangeEntries() function takes 11 arguments, yes. 11. It's quite
    a lot but it's all the relevant data associated with a tracking entry.

    1) st_hour is the start hour of the tracking entry, just the hour.
    2) st_min is the start minute of the tracking entry, just the minute.
    3) full_st is the full start time of the tracking entry.
    4) fi_hour is the end hour of the tracking entry, just the hour.
    5) fi_min is the end minute of the tracking entry, just the minute.
    6) full_fi is the full end time of the tracking entry.
    7) entry_date is the entry date of the tracking entry.
    8) daytype is the daytype of the tracking entry.
    9) change_id this is the ID of the tracking entry.
    10) breakLength this is the break length's minutes. Such as '15'.
    11) This is the breaklength string such as "00:15:00"

    The hideEntries function takes a single parameter, date which is the date of
    the entry you want to fill in the Add Entry form.

    The generated HTML should be 'pretty printed' as well, so the output code
    should be pretty readable.

    :param year: Integer for the year required for output, defaults to the
                 current year.
    :param month: Integer for the month required for output, defaults to the
                 current month.
    :param day: Integer for the day required for output, defaults to the
                 current day.
    :param user: Integer ID for the user in the database, this will automatically,
                 be passed to this function. However, if you need to use it in
                 another setting make sure this is passed.
    :returns: HTML String
    """

    if year is None: # pragma: no cover
        year = datetime.datetime.today().year
    if month is None: # pragma: no cover
        month = datetime.datetime.today().month
    if day is None: # pragma: no cover
        day = datetime.datetime.today().day


    # django passes us Unicode strings
    year, month, day = int(year), int(month), int(day)

    if month - 1 not in MONTH_MAP.keys(): # pragma: no cover
        raise Http404

    # if we've generated December, link to the next year
    if month + 1 == 13: # pragma: no cover
        next_url = '"/calendar/%s/%s"' % (year + 1, 1)
    else: # pragma: no cover
        next_url = '"/calendar/%s/%s"' % (year, month + 1)

    # if we've generated January, link to the previous year
    if month - 1 == 0:
        previous_url = '"/calendar/%s/%s"' % (year - 1, 12)
    else:
        previous_url = '"/calendar/%s/%s"' % (year, month - 1)

    # user_id came from sessions or the ajax call
    # so this is pretty safe
    database = Tbluser.objects.get(id__exact=user)

    # pull out the entries for the given month
    try:
        database = TrackingEntry.objects.filter(
            user=database.id,
            entry_date__year=year,
            entry_date__month=month
            )

    except TrackingEntry.DoesNotExist: # pragma: no cover
        # it seems Django still follows through with the assignment
        # when it raises an error, this is actually quite good because
        # we can treat the query set like normal
        pass

    # create a semi-sparsely populated n-dimensional
    # array with the month's days per week
    calendar_array = cdr.monthcalendar(
        int(year),
        int(month)
    )

    # creating a list holder for the strings
    # this is faster than concatenating the
    # strings as we go.
    cal_html = list()
    to_cal = cal_html.append

    # create the table header
    to_cal("""<table id="calendar" border="1">\n\t\t\t""")

    to_cal("""<tr>
                <td class="table-header" colspan="2">
                  <a class="table-links" href={0}>&lt;</a>
                </td>

                <td class="table-header" colspan="3">{2}</td>

                <td class="table-header" colspan="2">
                  <a class="table-links" href={1}>&gt;</a>
                </td>
              </tr>\n""".format(previous_url,
                                next_url,
                                MONTH_MAP[int(month) - 1][1]
                        )
           )

    # insert day names
    to_cal("""\n\t\t\t<tr>
                <td class=day-names>Mon</td>
                <td class=day-names>Tue</td>
                <td class=day-names>Wed</td>
                <td class=day-names>Thu</td>
                <td class=day-names>Fri</td>
                <td class=day-names>Sat</td>
                <td class=day-names>Sun</td>
              </tr>\n""")

    # each row in the calendar_array is a week
    # in the calendar, so create a new row
    for week_ in calendar_array:
        to_cal("""\n\t\t\t<tr>\n""")

        for _day in week_:

            # the calendar_array fills extraneous days
            # with 0's, we can catch that and treat either
            # end of the calendar differently in the CSS
            if _day != 0:
                emptyclass = 'day-class empty-day'
            else:
                emptyclass = 'empty'

            # we've got the month in the query set,
            # so just query that set for individual days
            try:
                # get all the data from our in-memory query-set.
                data = database.get(entry_date__day=_day)

                # Pass these to the page so that the jQuery functions
                # get the function arguments to edit those elements
                vals = [
                    data.start_time.hour,
                    data.start_time.minute,
                    str(data.start_time)[0:5],
                    data.end_time.hour,
                    data.end_time.minute,
                    str(data.end_time)[0:5],
                    data.entry_date,
                    data.daytype,
                    _day,
                    data.id,
                    data.breaks.minute,
                    str(data.breaks)[0:5],
                    data.link.entry_date if data.is_linked() and data.daytype != "LINKD" else ""
                    ]

                to_cal("""\t\t\t\t
                       <td onclick="toggleChangeEntries({0}, {1}, '{2}',
                                                        {3}, {4}, '{5}',
                                                        '{6}', '{7}', {9},
                                                        {10}, '{11}', '{12}')"
                           class="day-class {7}">{8}</td>\n""".format(*vals)
                       )

            except TrackingEntry.DoesNotExist:

                # For clicking blank days to input the day quickly into the
                # box. An alternative to the datepicker
                if _day != 0:
                    entry_date_string = '-'.join(map(pad,
                                                     [year, month, _day]
                                                     )
                                                )
                else:
                    entry_date_string = ''

                # we don't want to write a 0 in the box
                _day = '&nbsp' if _day == 0 else _day

                # write in the box and give the empty boxes a way to clear
                # the form
                to_cal("""\t\t\t\t<td onclick="hideEntries('{0}')"
                    class="{1}">{2}</td>\n""".format(
                                                  entry_date_string,
                                                  emptyclass,
                                                  _day)
                                              )

        # close up that row
        to_cal("""\t\t\t</tr>\n""")

    # close up the table
    to_cal("""\n</table>""")

    # join up the html and push it back
    return ''.join(cal_html)


@request_check
@json_response
def ajax_add_entry(request):

    '''Adds a calendar entry asynchronously.

    This method is for RUSERs who wish to add a single entry to their
    TrackingEntries. This method is only available via ajax and obviously
    requires that users be logged in.

    The client-side code which POSTs to this view should contain a json map
    of, for example:

    .. code-block:: javascript

       json_map = {
           'entry_date': "2012-01-01",
           'start_time': "09:00",
           'end_time': "17:00",
           'daytype': "WRKDY",
           'breaks': "00:15:00",
       }


    Consider that the UserID will be in the session database, then we simply
    run some server-side validations and then enter the entry into the db,
    there are also some client-side validation, which is essentially the same
    as here. The redundancy for validation is just *good practice* because of
    the various malicious ways it is possible to subvert client-side
    javascript or turn it off completely. Therefore, redundancy.

    When this view is launched, we create a server-side counterpart of the
    json which is in request object. We then fill it, passing None if there
    are any items missing.

    We then create a json_data dict to store the json success/error codes in
    to pass back to the User and inform them of the status of the ajax
    request.

    We then validate the data. Which involves only time validation.

    The creation of the entry goes like this:
    The form object holds purely the data that the TrackingEntry needs to
    hold, it's also already validated, so, as insecure it looks, it's actually
    perfectly fine as there has been client-side side validation and
    server-side validation. There will also be validation on the database
    level. So we can use kwargs to instantiate the TrackingEntry and
    .save() it without much worry for saving some erroneous and/or harmful
    data.

    If all goes well with saving the TrackingEntry, i.e. the entry isn't a
    duplicate, or the database validation doesn't fail. We then generate the
    calendar again using the entry_date in the form. We use this date because
    it's logical to assume that if the user enters a TrackingEntry using this
    date, then their calendar will be showing this month.

    We create the calendar and push it all back to the client. The client-side
    code then updates the calendar display with the new data.

    :param request: HttpRequest object.
    :returns: :class:`HttpResponse` object with the mime/application type as
              json.
    :rtype: :class:`HttpResponse`
    '''
    # object to dump form data into
    form = {
        'entry_date': None,
        'link': None,
        'start_time': None,
        'end_time': None,
        'daytype': None,
        'breaks': None
    }

    # get the form data from the request object
    form.update(get_request_data(form, request))

    if form["daytype"] == "HOLIS": # pragma: no cover
        return ajax_add_holiday(form)

    if form['link'] == '':
        form.pop('link')
    else:
        try:
            form['link'], _ = TrackingEntry.objects.get_or_create(
                user_id=form['user_id'],
                entry_date=form['link'],
                start_time="00:00:00",
                end_time="00:00:00",
                breaks="00:00:00",
                daytype="LINKD",
            )
        except IntegrityError: # pragma: no cover
            json_data['error'] = "Duplicate entry"
            return json_data
        

    # create objects to put our data into
    json_data = {
        'success': False,
        'error': '',
        'calendar': ''
    }
    try:
        # server-side time validation
        if not validate_time(form['start_time'], form['end_time']): # pragma: no cover
            json_data['error'] = "Start time after end time"
            return json_data
    except ValueError:
        error_log.warn("Date error got through - %s and %s" %
                       (form['start_time'], form['end_time']))
        json_data['error'] = "Date Error"
        return json_data

    try:
        entry = TrackingEntry(**form)
        entry.full_clean()
        entry.save()
        if entry.is_undertime() and form.get('link'):
            entry.unlink()
            entry.delete()
            json_data['error'] = "You cannot link undertime entries."
            return json_data
        if form.get('link'):
            form['link'].save()
        entry.save()
        if form.get('link'):
            form['link'].save()
    except (IntegrityError, ValidationError) as error:
        error_log.error("Error adding new entry for %s: %s" % \
                        (request.session.get('user_id'), str(error)))
        json_data['error'] = str(error)
        return json_data

    entry.create_approval_request()
    year, month, day = map(int,
                           form['entry_date'].split("-")
                           )

    calendar = gen_calendar(year, month, day,
                            form['user_id'])

    # if all went well
    json_data['success'] = True
    json_data['calendar'] = calendar
    return json_data

def ajax_add_holiday(form):
    # create objects to put our data into
    json_data = {
        'success': False,
        'error': '',
        'calendar': ''
    }
    user = Tbluser.objects.get(id=form['user_id'])
    shiftlength_list = user.get_shiftlength_list()
    holiday_req = TrackingEntry(
        user_id=user.id,
        entry_date=form['entry_date'],
        start_time=shiftlength_list[0],
        end_time=shiftlength_list[1],
        breaks=shiftlength_list[2],
        daytype="PENDI",
    )
    try:
        holiday_req.save()
    except IntegrityError:
        json_data["error"] = "Duplicate holiday requests not allowed."
        return json_data
    except ValidationError as error:
        json_data["error"] = str(error)
        return json_data

    holiday_req.create_approval_request()
    # if all went well
    year, month, day = form['entry_date'].split("-")
    calendar = gen_calendar(year, month, day,
                            form['user_id'])
    json_data['success'] = True
    json_data['calendar'] = calendar

    return json_data

@request_check
@json_response
def ajax_delete_entry(request):
    """Asynchronously deletes an entry

    This method is for RUSERs who wish to delete a single entry from
    their TrackingEntries. This method is only available via ajax
    and obviously requires that users be logged in.

    We then create our json_data map to hold our success status and any
    error codes we may generate so that we may inform the user of the
    status of the request once we complete.

    This part of the code will catch all errors because, well, this is
    production code and there's no chance I'll be letting server 500
    errors bubble to the client without catching and making them
    sound pretty and plausable. Therefore we catch all errors.

    We then take the entry date, and generate the calendar for that year/
    month.

    :param request: :class:`HttpRequest`
    :returns: :class:`HttpResponse` object with mime/application of json
    :rtype: :class:`HttpResponse`
    """

    form = {
        'hidden-id': None,
        'entry_date': None
    }

    # get the form data from the request object
    form.update(get_request_data(form, request))

    # create our json structure
    json_data = {
        'success': False,
        'error': '',
        'calendar': ''
    }

    if form['hidden-id']:
        # get the user and make sure that the user
        # assigned to the TrackingEntry is the same
        # as what's requesting the deletion
        user = Tbluser.objects.get(id__exact=form['user_id'])
        entry = TrackingEntry.objects.get(id=form['hidden-id'],
                                          user=user)
        entry.delete()

    year, month, day = map(int,
                           form['entry_date'].split("-")
                           )

    calendar = gen_calendar(year, month, day,
                            user=form['user_id'])

    # if all went well
    json_data['success'] = True
    json_data['calendar'] = calendar
    return json_data


@json_response
def ajax_error(error):

    """Returns a HttpResponse with JSON as a payload

    This function is a simple way of instantiating an error when using
    json_functions. It is decorated with the json_response decorator so that
    the dict that we return is dumped into a json object.

    :param error: :class:`str` which contains the pretty
                  error, this will be seen by the user so
                  make sure it's understandable.
    :returns: :class:`HttpResponse` with mime/application of json.
    :rtype: :class:`HttpResponse`
    """

    return {
        'success': False,
        'error': str(error)
        }


@request_check
@json_response
def ajax_change_entry(request):

    '''Changes a calendar entry asynchronously

    This method works in an extremely similar fashion to :meth:`ajax_add_entry`,
    with modicum of difference. The main difference is that in the add_entry
    method, we are simply looking for the hidden-id and deleting it from the
    table. In this method we are *creating* an entry from the form object
    and saving it into the table.

    :param request: :class:`HttpRequest`
    :returns: :class:`HttpResponse` with mime/application of JSON
    :rtype: :class:`HttpResponse`
    '''

    # object to dump form data into
    form = {
        'entry_date': None,
        'start_time': None,
        'end_time': None,
        'daytype': None,
        'breaks': None,
        'hidden-id': None,
        'link': None
    }

    # get the form data from the request object
    form.update(get_request_data(form, request))

    # create objects to put our data into
    json_data = {
        'success': True,
        'error': ''
    }

    if not all([form['start_time'], form['end_time']]):
        json_data['error'] = "Invalid time formats"
        json_data['success'] = False
        return json_data

    # server-side time validation
    if not validate_time(form['start_time'], form['end_time']):
        json_data['error'] = "Start time after end time"
        return json_data

    year, month, day = map(int,
                           form['entry_date'].split("-")
                           )
    if form['hidden-id']:
        try:
            # get the user and make sure that the user
            # assigned to the TrackingEntry is the same
            # as what's requesting the change
            user = Tbluser.objects.get(id__exact=form['user_id'])
            entry = TrackingEntry.objects.get(id=form['hidden-id'])
            entry.unlink()
            # change the fields on the retrieved entry
            stored_data = {
                "entry_date": entry.entry_date,
                "start_time": entry.start_time,
                "end_time": entry.end_time,
                "daytype": entry.daytype,
                "breaks": entry.breaks,
            }
            entry.entry_date = form['entry_date']
            entry.start_time = form['start_time']
            entry.end_time = form['end_time']
            entry.daytype = form['daytype']
            entry.breaks = form['breaks']
            if form['link']:
                entry.link = get_or_create_link(user, form['link'])
            else:
                entry.unlink()
            entry.full_clean()
            if entry.is_undertime() and (entry.is_linked() or form.get('link')):
                entry.save()
                entry.unlink()
                entry.entry_date = stored_data['entry_date']
                entry.start_time = stored_data['start_time']
                entry.end_time = stored_data['end_time']
                entry.daytype = stored_data['daytype']
                entry.breaks = stored_data['breaks']
                entry.link = None
                entry.save()
                json_data['success'] = False
                json_data['error'] = "You cannot link an undertime entry."
                json_data['calendar'] = gen_calendar(year, month, day,
                                                     form['user_id'])
                return json_data
            entry.save()
            entry.create_approval_request()
            if (datetime.date.today() - entry.entry_date).days \
                    > SUSPICIOUS_DATE_DIFF:
                suspicious_log.debug(
                    "Suspicious Tracking Change - Who: %s - When: %s" %
                    (user.user_id, entry.entry_date)
                    )
        except Exception as error:
            error_log.error(str(error))
            json_data['success'] = False
            json_data['error'] = str(error)
            return json_data

    calendar = gen_calendar(year, month, day,
                            form['user_id'])

    # if all went well
    json_data['success'] = True
    json_data['calendar'] = calendar
    return json_data

@admin_check
@json_response
def get_tracking_entry_data(request): # pragma: no cover
    '''Function returns the JSON representation of a single tracking entry.
    '''
    form = {
        "who": None,
        "entry_date": None
        }
    form.update(get_request_data(form, request))
    debug_log.debug("JSON Request Tracking Entry Data: %s/%s" %
                  (form['entry_date'], form['who']))
    try:
        entry = TrackingEntry.objects.get(user=form['who'],
                                          entry_date=form['entry_date'])
    except TrackingEntry.DoesNotExist:
        return {
            "success": False,
            "error": "No entry on that date."
            }

    return {
        "success": True,
        "entry_date": str(entry.entry_date),
        "start_time": str(entry.start_time),
        "end_time": str(entry.worklength),
        "breaks": str(entry.breaks),
        "daytype": str(entry.daytype),
        "length": round_down(entry.total_working_time()),
        "link": str(entry.link.entry_date) if entry.link else ""
        }

@request_check
@admin_check
@json_response
def get_user_data(request): # pragma: no cover
    """Returns a user as a json object.

    This is a very simple method. First, the :class:`HttpRequest` POST is
    checked to see if it contains a user_id. If so, we grab that user from
    the database and take all their relevant information and encode it into
    JSON then send it back to the browser.

    :param request: :class:`HttpRequest` object
    :returns: :class:`HttpRequest` with mime/application of JSON
    :rtype: :class:`HttpResponse`
    """

    json_data = {
        'success': False,
        'error': ''
    }

    try:
        user = Tbluser.objects.get(
            id__exact=request.POST.get('user_id', None)
            )
    except Tbluser.DoesNotExist:
        json_data['error'] = "User does not exist"
        return json_data

    json_data = {
        'success': True,
        'username': user.user_id,
        'firstname': user.firstname,
        'lastname': user.lastname,
        'market': user.market,
        'process': user.process,
        'user_type': user.user_type,
        'start_date': str(user.start_date),
        'breaklength': str(user.breaklength),
        'shiftlength': str(user.shiftlength),
        'job_code': user.job_code,
        'holiday_balance': user.holiday_balance,
        'disabled': user.disabled
    }
    return json_data


@request_check
@admin_check
@json_response
def delete_user(request):
    """Asynchronously deletes a user.

    This function simply deletes a user. We asynchronously delete the user
    because it provides a better user-experience for the people doing data
    entry on the form. It also allows the page to not have to deal with a
    jerky nor have to create annoying 'loading' bars/spinners.

    :note: This function should not be called directly.

    This function should be POSTed to via an Ajax call. Like so:

    .. code-block:: javascript

       $.ajaxSetup({
           type: "POST",
           url: "/ajax/",       // "ajax" is the url we created in urls.py
           dataType: "json"
       });

       $.ajax({
           data: {
               user_id: 1
           }
       });

    Once this is received, we check that the user POSTing this data is an
    administrator, or at least a team leader and we go ahead and delete the
    user from the table.

    :param request: :class:`HttpRequest`
    :returns: :class:`HttpResponse` mime/application JSON
    :rtype: :class:`HttpResponse`
    """
    json_data = {
        'success': False,
        'error': '',
    }

    user_id = request.POST.get('user_id', None)
    logged_in_user = request.session.get("user_id")
    if str(user_id) == str(logged_in_user):
        json_data['error'] = "You cannot delete yourself."
        return json_data

    if user_id:
        try:
            user = Tbluser.objects.get(id=user_id)
            user.delete()
        except Tbluser.DoesNotExist:
            error_log.error("Tried to delete non-existant user")
            json_data['error'] = "User does not exist"
            return json_data

        json_data['success'] = True
        return json_data
    else:
        json_data['error'] = "Missing user"
    return json_data


@request_check
@admin_check
@json_response
def useredit(request):

    """
    This function both adds and edits a user

    * Adding a user

    Adding a user via ajax. This function cannot be used outside of an ajax
    request. This is simply because there's no need. If there ever is a need
    to synchronously add users then I will remove the @request_check from the
    function.

    The function shouldn't be called directly, instead, you should POST to the
    ajax view which points to this via :mod:`timetracker.urls` you also
    need to include in the POST data. Here is an example call using jQuery:

    .. code-block:: javascript

       $.ajaxSetup({
           type: "POST",
           dataType: "json"
       });

       $.ajax({
           url: "/ajax/",
           data: {
               'user_id': "aaron.france@hp.com",
               'firstname': "Aaron",
               'lastname': "France",
               'user_type': "RUSER",
               'market': "BK",
               'process': "AR",
               'start_date': "2012-01-01"
               'breaklength': "00:15:00"
               'shiftlength': "00:07:45"
               'job_code': "ABC123"
               'holiday_balance': 20,
               'disabled': "false",
               'mode': "false"
           }
       });

    You would also create success and error handlers but for the sake of
    documentation lets assume you know what you're doing with javascript. When
    the function receives this data, it first checks the 'mode' attribute of
    the json data. If it contains 'false' then we are looking at an 'add_user'
    kind of request. Because of this, and the client-side validation that is
    done. We simply use some kwargs magic on the
    :class:`timetracker.tracker.models.Tbluser` constructor and save our
    Tbluser object.

    Providing that this didn't throw an error and it may, the next step is to
    create a Tblauthorization link to make sure that the user that created
    this user instance has the newly created user assigned to their team (or
    to their manager's team in the case of team leaders). We make the team
    leader check, if it's a team leader we call get_administrator() on the
    authorized user and then save the newly created user into the
    Tblauthorization instance found. Once this has happened we send the user
    an e-mail informing them of their account details and the password that we
    generated for them.

    * Editing a user

    This function also deals with the *editing* of a user instance, it's
    possible that this functionality will be refactored into it's own function
    but for now, we have both in here.

    Editing a user happens much the same as adding a user save for some very
    minor differences:

        .. code-block:: javascript

           $.ajaxSetup({
              type: "POST",
              dataType: "json"
           });

           $.ajax({
               url: "/ajax/",
               data: {
                   'user_id': "aaron.france@hp.com",
                   'firstname': "Aaron",
                   'lastname': "France",
                   'user_type': "RUSER",
                   'job_code': "ABC456"
                   'holiday_balance': 50,
                   'mode': 1
               }
           });

    You may notice that the amount of data isn't the same. When editing a user
    it is not vital that all attributes of the user instance are changed
    and/or sent to this view. This is because of the method used to assign
    back to the user instance the changes of attributes (getattr/setattr).

    The attribute which determines that the call is an edit call and not a add
    user call is the mode, if the mode is not false and is a number.

    When we first step into this function we look for the mode attribute of
    the json data. If it's a number then we look up the user with that user_id
    we then step through each attribute on the request map and assign it to
    the user object which we retrieved from the database.

    :param request: :class:`HttpRequest`
    :returns: :class:`HttpResponse` with mime/application of JSON
    :raises: :class:`Integrity` :class:`Validation` and :class:`Exception`
    :note: Please remember that all exceptions are caught here and to make
           sure that things are working be sure to read the response in the
           browser to see if there are any errors.
    """
    # create a random enough password
    password = get_random_string(12)
    data = {}

    # get the data off the request object
    for item in request.POST:
        if item not in ["form_type", "mode"]:
            value = request.POST[item]
            if value == "false":
                value = False
            if value == "true":
                value = True
            data[item] = value

    json_data = {
        'success': False,
        'error': ''
    }

    session_id = request.session.get('user_id')
    # get the user object from the database
    base_user = Tbluser.objects.get(id=session_id)
    auth_user = base_user.get_administrator()

    try:
        if request.POST.get("mode") == "false":
            if Tbluser.USER_LEVELS[data["user_type"]] >= \
                    Tbluser.USER_LEVELS[base_user.user_type]:
                json_data["error"] = "Your access rights are not " + \
                                     "sufficient to create a " + \
                                     "user of this type."
                return json_data
            # create the user
            user = Tbluser(**data)
            user.update_password(password)
            user.save()
            # link the user to the admin
            try:
                auth = Tblauth.objects.get(admin=auth_user)
            except Tblauth.DoesNotExist:
                auth = Tblauth(
                    admin=Tbluser.objects.get(
                    id=session_id))
                auth.save()
            auth.users.add(user)
            auth.save()
            email_message = """
                Hi {0},
                \tYour account has been created with the timetracker.
                Please use the following password to login: {1}.\n

                Below is the link to the timetracker:\n
                {3}
                Regards,
                {2}
                """.format(
                    user.firstname, password, auth_user.firstname,
                    settings.DOMAIN_NAME
                )

            send_mail('Your account has been created',
                      email_message,
                      'timetracker@unmonitored.com',
                      [user.user_id],
                      fail_silently=False)
        else:
            # If the mode contains a user_id
            # get that user and update it's
            # attributes with what was on the form
            user = Tbluser.objects.get(id__exact=request.POST.get("mode"))
            for key, value in data.items():
                # Users cannot disable themselves, it would prevent them
                # logging back in!
                if key == "disabled" and value \
                        and user == base_user:
                    json_data["error"] = "You cannot disable yourself."
                    return json_data
                if key == "user_type": # pragma: no cover
                    # Super Users cannot change their user_type
                    # nor can users change themselves.
                    if user == base_user or user.is_super():
                        continue
                    else: # pragma: no cover
                        # Users cannot elevate other users to a higher
                        # or equal role than themselves.
                        if Tbluser.USER_LEVELS[value] >= \
                                Tbluser.USER_LEVELS[base_user.user_type]:
                            continue
                if key != 'password':
                    setattr(user, key, value)
            user.save()
    except IntegrityError as error:
        if error[0] == DUPLICATE_ENTRY: # pragma: no cover
            database_log.info("Duplicate entry - %s" % str(error))
            json_data['error'] = "Duplicate entry"
            return json_data
        database_log.error(str(error))
        json_data['error'] = str(error)
        return json_data
    except ValidationError:
        error_log.error("Invalid data in creating a user")
        json_data['error'] = "Invalid Data."
        return json_data
    json_data['success'] = True
    return json_data


@request_check
@admin_check
@json_response
def mass_holidays(request):
    """Adds a holidays for a specific user en masse

    This function takes a large amount of holidays as json input, iterates
    over them, adding or deleting each one from the database.

    The json data looks as such:

    .. code-block:: javascript

       mass_data = {
           user_id1 : ["array", "of", "daytypes"],
           user_id2 : ["array", "of", "daytypes"],
           user_id3 : ["array", "of", "daytypes"],
           ...
        }

    And so on, for the entire month. In the request object we also have the
    month and the year. We use this to create a date to filter the month by,
    this is so that we're not deleting/changing the wrong month. The
    year/month are taken from the current table headings on the client. We
    then check what kind of day it is.

    If the daytype is 'empty' then we attempt to retrieve the day mapped to
    that date, if there's an entry, we delete it. This is because when the
    holiday page is rendered it shows whether or not that day is assigned. If
    it was assigned and now it's empty, it means the user has marked it as
    empty.

    If the daytype is *not* empty, then we create a new TrackingEntry instance
    using the data that was the current step of iteration through the
    holiday_data dict. This will be a number and a daytype. We have the user
    we're uploading this for and the year/month from the request object. We
    also choose sensible defaults for what we're not supplied with, i.e. we're
    not supplied with start/end times, nor a break time. This is because the
    holiday page only deals with *non-working-days* therefore we can track
    these days with zeroed times.

    If all goes well, we mark the return object's success attribute with True
    and return.

    :param request: :class:`HttpRequest`
    :returns: :class:`HttpResponse` with mime/application as JSON
    :note: All exceptions are caught, however here is a list:
    :raises: :class:`IntegrityError` :class:`DoesNotExist`
             :class:`ValidationError` :class:`Exception`
    """

    json_data = {
        'success': False,
        'error': ''
        }

    form_data = {
        'year': None,
        'month': None,
        }

    for key in form_data:
        form_data[key] = str(request.POST[key])

    try:
        holidays = simplejson.loads(request.POST.get('mass_data'))
    except Exception as err:
        json_data['error'] = str(err)
        return json_data

    sick_sent = False
    for entry in holidays.items():
        for (day, daytype) in enumerate(entry[1]):
            if day == 0:
                continue
            # we check if the date is valid by trying to create a dt
            # object and catching ValueError.
            try:
                datetime.datetime(
                    int(form_data['year']), int(form_data['month']), day
                    )
            except ValueError:
                # if it's an invalid date, just ignore it.
                continue
            datestr = '-'.join([form_data['year'],
                                form_data['month'], str(day)])
            try:
                current_entry = TrackingEntry.objects.get(
                    entry_date=datestr,
                    user_id=entry[0]
                )
                if current_entry.is_linked() and daytype == "empty":
                    current_entry.unlink()
                    current_entry.delete()
                elif daytype == "empty":
                    current_entry.delete()
                else:
                    # we may have unlinked something before, and if
                    # we're here we don't want to set something to
                    # linked again.
                    if daytype == "LINKD":
                        continue
                    current_entry.daytype = daytype
                    current_entry.save()
            except TrackingEntry.DoesNotExist:
                if daytype in ["empty", "LINKD"]:
                    continue
                time_str = Tbluser.objects.get(
                    id=entry[0]
                    ).get_shiftlength_list()
                new_entry = TrackingEntry(
                        entry_date=datestr,
                        user_id=entry[0],
                        start_time=time_str[0],
                        end_time=time_str[1],
                        breaks=time_str[2],
                        daytype=daytype)
                new_entry.save()
                new_entry.create_approval_request()
                if not sick_sent and daytype == "SICKD":
                    sickuser = Tbluser.objects.get(id=entry[0])
                    if sickuser.shouldnotifysick(new_entry):
                        sickuser.sendsicknotification()
                        sick_sent = True
    json_data['success'] = True
    return json_data

@request_check
@json_response
def profile_edit(request):
    """Asynchronously edits a user's profile.

    Access Level: All

    First we pull out the user instance that is currently logged in. Then as
    with most ajax functions, we construct a map to receive what should be in
    the in the POST object. This view specifically deals with changing a Name,
    Surname and Password. Any other data is not required to be changed.

    Once this data has been populated from the POST object we then retrieve
    the string names for the attributes and use setattr to change them to what
    we've been supplied here.

    :param request: :class:`HttpRequest`
    :returns: :class:`HttpResponse` with mime/application as JSON
    """

    json_data = {
        "success": False,
        "error": ''
    }

    # get the user object from the db
    user = Tbluser.objects.get(id=request.session.get("user_id"))

    # pull the data out the form
    form_data = get_request_data({
        'firstname': None,
        'lastname': None,
        'password': None
        }, request)
    # get request data also pulls out the user_id,
    # we don't need it
    form_data.pop("user_id")

    # get the items from the form and save them onto the
    # user object
    for key, value in form_data.items():
        if key == "password":
            user.update_password(value)
        else:
            setattr(user, key, value)
    user.save()
    json_data['success'] = True
    return json_data


def gen_datetime_cal(year, month):
    '''Generates a datetime list of all days in a month

    :param year: :class:`int`
    :param month: :class:`int`
    :returns: A flat list of datetime objects for the given month
    :rtype: :class:`List` containing :class:`datetime.datetime` objects.

    '''
    days = []
    for week in cdr.monthcalendar(year, month):
        days.extend(week)

    # filter out zeroed days
    days = filter((lambda x: x > 0), days)
    return [datetime.datetime(year=year, month=month, day=day) for day in days]

def working_days(year, month):
    return filter(lambda day: day.isoweekday() < 5, gen_datetime_cal(year, month))

def last12months(year, month):
    d = datetime.datetime(year=year,month=month,day=1)
    dates = []
    rest = 0
    for x in range(12):
        try:
            dates.append(
                datetime.datetime(year=year,month=month-x,day=1)
            )
        except ValueError: # we've rolled over to the previous year
            dates.append(
                datetime.datetime(year=year-1,month=12-rest,day=1)
            )
            rest += 1
    return list(reversed(dates))

@admin_check
@json_response
def get_comments(request):
    """
    Function which gets the comments from a user's tracking entry
    """

    json_data = {
        'success': False,
        'error': '',
        'comment': ''
    }

    form_data = {
        'user': None,
        'year': None,
        'month': None,
        'day': None
    }

    for key in form_data:
        try:
            form_data[key] = pad(request.GET[key])
        except KeyError:
            json_data['error'] = 'Missing data: %s' % str(key)
            return json_data

    entry_date = "{year}-{month}-{day}".format(**form_data)
    try:
        entry = TrackingEntry.objects.get(entry_date=entry_date,
                                          user_id=form_data['user'])
    # DoesNotExist error because entries may not have any comments and
    # ValidationError because we have been given invalid date values.
    except (TrackingEntry.DoesNotExist, ValidationError):
        json_data['success'] = True
        return json_data

    json_data['success'] = True
    json_data['comment'] = entry.comments
    return json_data


@admin_check
@json_response
def add_comment(request):
    """
    Function which adds a comment to a tracking entry field.
    """
    json_data = {
        'success': False,
        'error': '',
    }

    form_data = {
        'user': None,
        'year': None,
        'month': None,
        'day': None,
        'comment': None
    }

    for key in form_data:
        try:
            if key in set(['month', 'day']):
                form_data[key] = pad(request.POST[key])
            else:
                form_data[key] = request.POST[key]
        except KeyError:
            json_data['error'] = 'Missing data: %s' % str(key)
            return json_data
    entry_date = "{year}-{month}-{day}".format(**form_data)
    try:
        entry = TrackingEntry.objects.get(entry_date=entry_date,
                                          user_id=form_data['user'])
    except TrackingEntry.DoesNotExist:
        json_data['success'] = False
        json_data['error'] = "No entry to add a comment to!"
        return json_data

    entry.comments = form_data['comment']
    entry.save()
    entry = TrackingEntry.objects.get(entry_date=entry_date,
                                      user_id=form_data['user'])
    json_data['success'] = True
    return json_data


@admin_check
@json_response
def remove_comment(request):
    """
    Function which removes a comment from a tracking field
    """

    json_data = {
        'success': False,
        'error': '',
    }

    form_data = {
        'user': None,
        'year': None,
        'month': None,
        'day': None,
    }

    for key in form_data:
        try:
            form_data[key] = pad(request.POST[key])
        except KeyError:
            json_data['error'] = 'Missing data: %s' % str(key)
            return json_data

    entry_date = "{year}-{month}-{day}".format(**form_data)
    try:
        entry = TrackingEntry.objects.get(entry_date=entry_date,
                                          user_id=form_data['user'])
    except TrackingEntry.DoesNotExist:
        json_data['success'] = True
        return json_data

    entry.comments = ''
    entry.save()
    json_data['success'] = True
    return json_data

def get_or_create_link(user, date):
    entry, created = TrackingEntry.objects.get_or_create(
        user=user,
        entry_date=date,
        start_time="00:00",
        end_time="00:00",
        breaks="00:00",
        daytype="LINKD"
    )
    if created:
        entry.save()
    return entry
