from django.http import Http404, HttpResponseRedirect
from django.test import TestCase

from timetracker.tests.basetests import create_users, delete_users
from timetracker.vcs.models import Activity, ActivityEntry
from timetracker.vcs.activities import createuseractivities
from timetracker.vcs.views import vcs_add, update

class BaseVCS(TestCase):
    class Req:
        pass
    req = Req()

    def setUp(self):
        create_users(self)
        createuseractivities()
        self.req.session = {
            "user_id": self.linked_user.id
        }

    def tearDown(self):
        delete_users(self)
        Activity.objects.all().delete()


class VCSAddTestCase(BaseVCS):

    def test_add_entry(self):
        self.req.POST = {
            "activity_key": str(Activity.objects.all()[0].id),
            "amount": "100",
            "date": "2012-01-01",
        }
        self.assertIsInstance(vcs_add(self.req), HttpResponseRedirect)

    def test_add_entry_no_date(self):
        self.req.POST = {
            "activity_key": str(Activity.objects.all()[0].id),
            "amount": "100",
        }
        self.assertRaises(Http404, vcs_add, self.req)

    def test_add_entry_no_amount(self):
        self.req.POST = {
            "activity_key": str(Activity.objects.all()[0].id),
            "date": "2012-01-01",
        }
        self.assertRaises(Http404, vcs_add, self.req)

    def test_add_entry_no_activity(self):
        self.req.POST = {
            "date": "2012-01-01",
            "amount": "100",
        }
        self.assertRaises(Http404, vcs_add, self.req)


class VCSUpdateTestCase(BaseVCS):

    def test_update_entry(self):
        self.req.POST = {
            "activity_key": str(Activity.objects.all()[0].id),
            "amount": 100,
            "date": "2012-01-01",
        }
        vcs_add(self.req)
        self.req.POST = {
            "volume": 1,
            "id": str(ActivityEntry.objects.all()[0].id)
        }
        entry = ActivityEntry.objects.all()[0]
        prevol = entry.amount
        id = entry.id
        update(self.req)
        self.assertEqual(ActivityEntry.objects.get(id=id).amount, 1)

    def test_update_fail_no_volume(self):
        self.req.POST = {
            "activity_key": str(Activity.objects.all()[0].id),
            "amount": 100,
            "date": "2012-01-01",
        }
        vcs_add(self.req)
        self.req.POST = {
            "id": str(ActivityEntry.objects.all()[0].id)
        }
        self.assertRaises(Http404, update, self.req)

    def test_update_fail_no_id(self):
        self.req.POST = {
            "activity_key": str(Activity.objects.all()[0].id),
            "amount": 100,
            "date": "2012-01-01",
        }
        vcs_add(self.req)
        self.req.POST = {
            "volume": 1,
        }
        self.assertRaises(Http404, update, self.req)

    def test_update_fail_no_data(self):
        self.req.POST = {
            "activity_key": str(Activity.objects.all()[0].id),
            "amount": 100,
            "date": "2012-01-01",
        }
        vcs_add(self.req)
        self.req.POST = {}
        self.assertRaises(Http404, update, self.req)