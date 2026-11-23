"""Pure fencing checks only; does not launch a browser/backend."""
import unittest
from pathlib import Path
from unittest.mock import patch
from probe_linux_packaged import ProbeFailure
import library_room_review as room

class RoomReviewGuards(unittest.TestCase):
    def test_local_capture_is_refused_before_using_the_page(self):
        with patch.object(room, 'require_capture_ci', side_effect=ProbeFailure('no_local_room')):
            with self.assertRaisesRegex(ProbeFailure, 'no_local_room'):
                room.review_library_room(None, Path('PRIVATE'), {})

if __name__ == '__main__': unittest.main()
