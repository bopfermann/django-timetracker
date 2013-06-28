import datetime

from django.test import TestCase
from django.core import mail

from timetracker.overtime.models import PendingApproval
from timetracker.tracker.models import TrackingEntry
from timetracker.tests.basetests import create_users, delete_users

class ApprovalTest(TestCase):

    def setUp(self):
        create_users(self)
        self.ot_entry = TrackingEntry(
            user=self.linked_user,
            entry_date=datetime.datetime.today(),
            start_time=datetime.time(0, 0, 0),
            end_time=datetime.time(17, 0, 0),
            breaks=datetime.time(0, 15, 0),
            daytype="WKDAY",
        )
        self.ot_entry.full_clean()
        self.ot_entry.save()
            
    def tearDown(self):
        delete_users(self)

    def testPendingApprovalDenied(self):
        self.doapprovaltest(False, "Request for Overtime: Denied.", 0)

    def testPendingApprovalApproved(self):
        self.doapprovaltest(True, "Your recent timetracker actions.", 1)

    def doapprovaltest(self, status, message, attachments):
        approval = PendingApproval(
            entry=self.ot_entry,
            approver=self.linked_manager
        )
        approval.save()
        approval.close(status)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, message)
        self.assertEqual(len(mail.outbox[0].attachments), attachments)
